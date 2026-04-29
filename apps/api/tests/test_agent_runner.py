from collections import Counter
from decimal import Decimal
from types import SimpleNamespace
from time import monotonic

import pytest

from app.agent.chunking import ChunkPlan, ClassifiedDiffFile, PlannedChunk
from app.agent.context_builder import ContextTelemetry
from app.agent.anchors import attach_anchor_metadata, filter_findings_with_valid_anchors
from app.agent.dedupe import dedupe_findings
from app.agent.review_config import ReviewConfig, ReviewModelConfig
from app.agent.runner import (
    _apply_policy_filters,
    _apply_review_config_filters,
    _apply_confidence_threshold,
    _attach_debug_artifacts,
    _chunking_config_hash,
    _calculate_conflict_score,
    _merge_debate_results,
    _mark_review_done,
    _apply_missing_confidence_guardrail,
    _repair_findings_from_files,
    _review_config_for_fast_path_decision,
    _run_fast_path_stage,
    _run_chunked_review,
    _load_user_provider_keys,
    _summarize_target_line_mismatch_subtypes,
    _track_fast_path_confidence_anomaly,
    _validate_result,
    _validation_feedback,
    cross_check_fact_ids,
    cross_check_tool_evidence,
    extract_tool_call_history,
)
from app.agent.fast_path import FastPathDecision
from app.llm.errors import LLMQuotaOrRateLimitError
from app.llm.router import ModelResolution, ModelRoleRoutingConfig, ModelsRoutingConfig
from app.agent.diff_parser import FileInDiff, NumberedLine
from app.agent.schema import Finding, ReviewResult


class FakeValidator:
    def validate(self, finding: Finding) -> tuple[bool, str | None, str | None]:
        if finding.file_path == "bad.py":
            return False, "line_out_of_range", "line_start 99 out of range"
        return True, None, None


def _finding(file_path: str, confidence: int = 90) -> Finding:
    return Finding.model_validate(
        {
            "severity": "medium",
            "category": "correctness",
            "message": "Potential bug in this statement.",
            "file_path": file_path,
            "line_start": 1,
            "line_end": 1,
            "target_line_content": "x = 1",
            "suggestion": None,
            "confidence": confidence,
            "evidence": "diff_visible",
        }
    )


def test_validate_result_drops_invalid_findings() -> None:
    result = ReviewResult(findings=[_finding("ok.py"), _finding("bad.py")], summary="Summary")
    validated, dropped, generated = _validate_result(result, FakeValidator())
    assert generated == 2
    assert len(validated.findings) == 1
    assert validated.findings[0].file_path == "ok.py"
    assert len(dropped) == 1
    assert dropped[0][1] == "line_out_of_range"
    assert dropped[0][2] == "line_start 99 out of range"


def test_validation_feedback_contains_reason_and_location() -> None:
    dropped = [(_finding("bad.py"), "line_out_of_range", "line_start 99 out of range")]
    feedback = _validation_feedback(dropped)
    assert "bad.py:1-1" in feedback
    assert "line_start 99 out of range" in feedback


def test_apply_confidence_threshold_tracks_dropped_metadata() -> None:
    result = ReviewResult(
        findings=[_finding("ok.py", 90), _finding("low.py", 70)], summary="Summary"
    )
    filtered, dropped = _apply_confidence_threshold(result, threshold=85)
    assert len(filtered.findings) == 1
    assert filtered.findings[0].file_path == "ok.py"
    assert dropped[0]["file_path"] == "low.py"
    assert dropped[0]["threshold"] == 85


def test_attach_debug_artifacts_includes_drop_buckets() -> None:
    context: dict = {}
    _attach_debug_artifacts(
        context=context,
        generated=4,
        validator_dropped=[(_finding("bad.py"), "line_out_of_range", "invalid range")],
        confidence_dropped=[
            {
                "file_path": "low.py",
                "line_start": 1,
                "line_end": 1,
                "confidence": 50,
                "threshold": 85,
            }
        ],
        draft_findings=3,
        final_findings=2,
        editor_actions=Counter({"keep": 1, "drop": 1, "modify": 1}),
        editor_drop_reasons=Counter({"duplicate": 1}),
        severity_draft=Counter({"medium": 2, "high": 1}),
        severity_final=Counter({"medium": 2}),
        confidence_draft=Counter({"80-94": 2, "60-79": 1}),
        confidence_final=Counter({"80-94": 2}),
        evidence_distribution=Counter({"diff_visible": 2}),
        evidence_rejections_total=1,
        evidence_rejection_reasons=Counter({"unknown fact id: bad_id": 1}),
        retry_triggered=True,
        retry_mode="repair_only",
        retry_attempted=1,
        retry_recovered=1,
        threshold=85,
        context_telemetry=ContextTelemetry(anchor_coverage=1.0),
        mismatch_subtypes={"target_line_mismatch_whitespace": 1},
        debate_conflict_score=28,
    )
    artifacts = context["debug_artifacts"]
    assert artifacts["generated_findings_count"] == 4
    assert artifacts["retry_triggered"] is True
    assert artifacts["retry_mode"] == "repair_only"
    assert artifacts["retry_attempted"] == 1
    assert artifacts["retry_recovered"] == 1
    assert artifacts["draft_findings_total"] == 3
    assert artifacts["final_findings_total"] == 2
    assert artifacts["editor_actions"]["keep"] == 1
    assert artifacts["evidence_distribution"]["diff_visible"] == 2
    assert artifacts["evidence_rejections_total"] == 1
    assert artifacts["validator_dropped"][0]["reason"] == "line_out_of_range"
    assert artifacts["validator_dropped"][0]["detail"] == "invalid range"
    assert artifacts["confidence_dropped"][0]["file_path"] == "low.py"
    assert artifacts["target_line_mismatch_subtypes"]["target_line_mismatch_whitespace"] == 1
    assert artifacts["acceptance_quality_check"]["target_sample_size"] == 50
    assert artifacts["debate_conflict_score"] == 28


@pytest.mark.anyio
async def test_load_user_provider_keys_sets_user_context(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_user_context: list[int] = []

    async def fake_set_user_context(_session: object, github_id: int) -> None:
        seen_user_context.append(github_id)

    class FakeSession:
        def __init__(self) -> None:
            self.execute_calls = 0

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def execute(self, _stmt: object) -> object:
            self.execute_calls += 1
            if self.execute_calls == 1:
                return SimpleNamespace(
                    scalar_one_or_none=lambda: SimpleNamespace(id=42, deleted_at=None)
                )
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(
                    all=lambda: [SimpleNamespace(provider="openai", key_enc="encrypted")]
                )
            )

    monkeypatch.setattr("app.agent.runner.AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr("app.agent.runner.set_user_context", fake_set_user_context)
    monkeypatch.setattr("app.agent.runner.decrypt_secret", lambda _value: "plain-openai-key")

    keys = await _load_user_provider_keys(123456)
    assert keys == {"openai": "plain-openai-key"}
    assert seen_user_context == [123456]


def test_repair_findings_from_files_rewrites_line_start_when_match_in_window() -> None:
    finding = _finding("a.py")
    finding.line_start = 1
    finding.line_end = 1
    finding.target_line_content = "value = int(user_input)"
    repaired = _repair_findings_from_files(
        [finding],
        {"a.py": "x = 1\nvalue = int(user_input)\nprint(value)"},
        commentable_lines={("a.py", 1), ("a.py", 2), ("a.py", 3)},
        window=3,
    )
    assert repaired[0].line_start == 2
    assert repaired[0].line_end == 2
    assert repaired[0].target_line_content == "value = int(user_input)"


def test_repair_findings_from_files_keeps_original_when_repaired_line_not_commentable() -> None:
    finding = _finding("a.py")
    finding.line_start = 1
    finding.line_end = 1
    finding.target_line_content = "value = int(user_input)"
    repaired = _repair_findings_from_files(
        [finding],
        {"a.py": "x = 1\nvalue = int(user_input)\nprint(value)"},
        commentable_lines={("a.py", 1), ("a.py", 3)},
        window=3,
    )
    assert repaired[0].line_start == 1


def test_summarize_target_line_mismatch_subtypes_breaks_down_reasons() -> None:
    mismatch = _finding("a.py")
    mismatch.line_start = 1
    mismatch.target_line_content = "value = int(user_input)\t"
    dropped = [
        (
            mismatch,
            "target_line_mismatch",
            "target_line_content does not match file content at line_start",
        )
    ]
    counts = _summarize_target_line_mismatch_subtypes(
        dropped,
        {"a.py": "value = int(user_input)"},
        commentable_lines=None,
        window=3,
    )
    assert counts["target_line_mismatch_whitespace"] == 1


@pytest.mark.anyio
async def test_mark_review_done_persists_runtime_model(monkeypatch: pytest.MonkeyPatch) -> None:
    review = SimpleNamespace(
        status="running",
        model_provider="anthropic",
        model="claude-sonnet-4-5",
        findings=None,
        debug_artifacts={"chunking_state": {"prior": {"status": "done"}}},
        github_review_node_id=None,
        tokens_used=None,
        cost_usd=None,
        completed_at=None,
    )

    class FakeSession:
        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, _model: object, _review_id: int) -> object:
            return review

        async def commit(self) -> None:
            return None

    async def fake_set_installation_context(_session: object, _installation_id: int) -> None:
        return None

    monkeypatch.setattr("app.agent.runner.AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr("app.agent.runner.set_installation_context", fake_set_installation_context)

    context = {
        "installation_id": 1,
        "review_id": 123,
        "tokens_used": 1000,
        "input_tokens": 800,
        "output_tokens": 200,
        "debug_artifacts": {"quality": {"final_findings_total": 0}},
        "github_review_node_id": "PRR_kwDOExampleNode",
    }
    review_config = ReviewConfig(
        model=ReviewModelConfig(
            name="claude-3-5-haiku-latest",
            input_per_1m_usd=Decimal("0.80"),
            output_per_1m_usd=Decimal("4.00"),
        )
    )
    await _mark_review_done(ReviewResult(findings=[], summary="ok"), context, "done", review_config)

    assert review.status == "done"
    assert review.model_provider == "anthropic"
    assert review.model == "claude-3-5-haiku-latest"
    assert review.github_review_node_id == "PRR_kwDOExampleNode"
    assert "chunking_state" in review.debug_artifacts
    assert "quality" in review.debug_artifacts


@pytest.mark.anyio
async def test_run_fast_path_stage_records_audit_and_debug_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolution = ModelResolution(
        role="fast_path",
        provider="openai",
        model="gpt-5-mini",
        tier="economy",
        status="active",
        catalog_version_hash="abc123",
    )
    audits: list[dict[str, object]] = []

    def fake_resolve_attempts(*_args: object, **_kwargs: object) -> list[ModelResolution]:
        return [resolution]

    async def fake_prepass(**kwargs: object) -> tuple[FastPathDecision, list[object], str, str]:
        return (
            FastPathDecision(
                decision="skip_review",
                risk_labels=["docs_only"],
                reason="Only docs changed.",
                confidence=95,
                review_surface=["docs/README.md"],
                requires_full_context=False,
            ),
            [],
            "system",
            "user",
        )

    async def fake_audit(**kwargs: object) -> None:
        audits.append(kwargs)

    monkeypatch.setattr("app.agent.runner._resolve_runtime_attempt_chain", fake_resolve_attempts)
    monkeypatch.setattr("app.agent.runner.run_fast_path_prepass", fake_prepass)
    monkeypatch.setattr("app.agent.runner._record_model_audit", fake_audit)

    context = {
        "review_id": 123,
        "installation_id": 1,
        "run_id": "run",
        "owner": "acme",
        "repo": "repo",
        "pr_number": 7,
        "head_sha": "sha",
        "input_tokens": 0,
        "output_tokens": 0,
        "tokens_used": 0,
    }

    decision, used_resolution = await _run_fast_path_stage(
        context=context,
        diff_text="diff --git a/docs/README.md b/docs/README.md\n+hello",
        pr={"title": "Docs", "body": ""},
        commits=[],
        review_config=ReviewConfig(),
        diff_tokens=20,
    )

    assert decision.decision == "skip_review"
    assert used_resolution == resolution
    assert context["debug_artifacts"]["fast_path_decision"]["decision"] == "skip_review"
    assert context["debug_artifacts"]["fast_path_decision"]["review_surface_count"] == 1
    assert context["debug_artifacts"]["fast_path_decision"]["produces_findings"] is False
    assert audits[0]["stage"] == "fast_path"
    assert audits[0]["decision"] == "skip_review"
    assert audits[0]["extra_metadata"]["confidence"] == 95
    assert audits[0]["extra_metadata"]["produces_findings"] is False


@pytest.mark.anyio
async def test_track_fast_path_confidence_anomaly_flags_repeated_zeros() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.store: dict[str, int] = {}

        async def incr(self, key: str) -> int:
            self.store[key] = int(self.store.get(key, 0)) + 1
            return self.store[key]

        async def expire(self, _key: str, _seconds: int) -> bool:
            return True

        async def delete(self, key: str) -> int:
            self.store.pop(key, None)
            return 1

    context = {"installation_id": 42, "_redis": FakeRedis()}
    count_1, flagged_1 = await _track_fast_path_confidence_anomaly(
        context=context,
        provider="openai",
        model="gpt-5-mini",
        confidence=0,
        limit=2,
        enabled=True,
    )
    count_2, flagged_2 = await _track_fast_path_confidence_anomaly(
        context=context,
        provider="openai",
        model="gpt-5-mini",
        confidence=0,
        limit=2,
        enabled=True,
    )

    assert count_1 == 1
    assert flagged_1 is False
    assert count_2 == 2
    assert flagged_2 is True


@pytest.mark.anyio
async def test_run_fast_path_stage_falls_back_to_full_review_on_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolution = ModelResolution(
        role="fast_path",
        provider="openai",
        model="gpt-5-mini",
        tier="economy",
        status="active",
        catalog_version_hash="abc123",
    )

    def fake_resolve_attempts(*_args: object, **_kwargs: object) -> list[ModelResolution]:
        return [resolution]

    async def fake_prepass(**_kwargs: object) -> tuple[FastPathDecision, list[object], str, str]:
        raise RuntimeError("provider unavailable")

    async def fake_audit(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.agent.runner._resolve_runtime_attempt_chain", fake_resolve_attempts)
    monkeypatch.setattr("app.agent.runner.run_fast_path_prepass", fake_prepass)
    monkeypatch.setattr("app.agent.runner._record_model_audit", fake_audit)

    context = {
        "review_id": 123,
        "installation_id": 1,
        "run_id": "run",
        "owner": "acme",
        "repo": "repo",
        "pr_number": 7,
        "head_sha": "sha",
        "input_tokens": 0,
        "output_tokens": 0,
        "tokens_used": 0,
    }

    decision, used_resolution = await _run_fast_path_stage(
        context=context,
        diff_text="diff --git a/src/app.py b/src/app.py\n+print('hi')",
        pr={"title": "Code", "body": ""},
        commits=[],
        review_config=ReviewConfig(),
        diff_tokens=20,
    )

    assert decision.decision == "full_review"
    assert "fast_path_error" in decision.risk_labels
    assert used_resolution == resolution
    assert context["debug_artifacts"]["fast_path_decision"]["fallback_reason"] == "fast_path_error"


@pytest.mark.anyio
async def test_run_fast_path_stage_rotates_to_next_provider_after_quota_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = ModelResolution(
        role="fast_path",
        provider="openai",
        model="gpt-5-mini",
        tier="economy",
        status="active",
        catalog_version_hash="abc123",
    )
    second = ModelResolution(
        role="fast_path",
        provider="anthropic",
        model="claude-sonnet-4-6",
        tier="economy",
        status="active",
        catalog_version_hash="abc123",
    )
    call_count = 0

    def fake_resolve_attempts(*_args: object, **_kwargs: object) -> list[ModelResolution]:
        return [first, second]

    async def fake_prepass(**kwargs: object) -> tuple[FastPathDecision, list[object], str, str]:
        nonlocal call_count
        call_count += 1
        provider = kwargs.get("provider")
        if provider == "openai":
            raise LLMQuotaOrRateLimitError(
                provider="openai",
                model="gpt-5-mini",
                detail="insufficient_quota",
            )
        return (
            FastPathDecision(
                decision="light_review",
                risk_labels=["low_risk"],
                reason="fallback provider succeeded",
                confidence=86,
                review_surface=["src/app.py"],
                requires_full_context=False,
            ),
            [],
            "system",
            "user",
        )

    async def fake_audit(**_kwargs: object) -> None:
        return None

    async def noop_rate_limit_sleep(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.agent.runner._resolve_runtime_attempt_chain", fake_resolve_attempts)
    monkeypatch.setattr("app.agent.runner.run_fast_path_prepass", fake_prepass)
    monkeypatch.setattr("app.agent.runner._record_model_audit", fake_audit)
    monkeypatch.setattr("app.agent.runner.sleep_after_llm_rate_limit", noop_rate_limit_sleep)

    context = {
        "review_id": 123,
        "installation_id": 1,
        "run_id": "run",
        "owner": "acme",
        "repo": "repo",
        "pr_number": 7,
        "head_sha": "sha",
        "input_tokens": 0,
        "output_tokens": 0,
        "tokens_used": 0,
    }

    decision, used_resolution = await _run_fast_path_stage(
        context=context,
        diff_text="diff --git a/src/app.py b/src/app.py\n+print('hi')",
        pr={"title": "Code", "body": ""},
        commits=[],
        review_config=ReviewConfig(),
        diff_tokens=20,
    )

    assert call_count == 2
    assert decision.decision == "light_review"
    assert used_resolution == second


@pytest.mark.anyio
async def test_run_fast_path_stage_rotates_to_next_provider_after_non_quota_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = ModelResolution(
        role="fast_path",
        provider="openai",
        model="gpt-5-mini",
        tier="economy",
        status="active",
        catalog_version_hash="abc123",
    )
    second = ModelResolution(
        role="fast_path",
        provider="gemini",
        model="gemini-2.5-flash-lite",
        tier="economy",
        status="active",
        catalog_version_hash="abc123",
    )
    call_count = 0

    def fake_resolve_attempts(*_args: object, **_kwargs: object) -> list[ModelResolution]:
        return [first, second]

    async def fake_prepass(**kwargs: object) -> tuple[FastPathDecision, list[object], str, str]:
        nonlocal call_count
        call_count += 1
        provider = kwargs.get("provider")
        if provider == "openai":
            raise RuntimeError("temperature unsupported")
        return (
            FastPathDecision(
                decision="light_review",
                risk_labels=["low_risk"],
                reason="fallback provider succeeded",
                confidence=86,
                review_surface=["src/app.py"],
                requires_full_context=False,
            ),
            [],
            "system",
            "user",
        )

    async def fake_audit(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.agent.runner._resolve_runtime_attempt_chain", fake_resolve_attempts)
    monkeypatch.setattr("app.agent.runner.run_fast_path_prepass", fake_prepass)
    monkeypatch.setattr("app.agent.runner._record_model_audit", fake_audit)

    context = {
        "review_id": 123,
        "installation_id": 1,
        "run_id": "run",
        "owner": "acme",
        "repo": "repo",
        "pr_number": 7,
        "head_sha": "sha",
        "input_tokens": 0,
        "output_tokens": 0,
        "tokens_used": 0,
    }

    decision, used_resolution = await _run_fast_path_stage(
        context=context,
        diff_text="diff --git a/src/app.py b/src/app.py\n+print('hi')",
        pr={"title": "Code", "body": ""},
        commits=[],
        review_config=ReviewConfig(),
        diff_tokens=20,
    )

    assert call_count == 2
    assert decision.decision == "light_review"
    assert used_resolution == second


def test_light_review_forces_economy_primary_when_primary_is_not_explicit() -> None:
    config = ReviewConfig(
        models=ModelsRoutingConfig(
            roles={"primary_review": ModelRoleRoutingConfig(tier="balanced")}
        )
    )
    decision = FastPathDecision(
        decision="light_review",
        risk_labels=["low_risk"],
        reason="Small low-risk change.",
        confidence=90,
        review_surface=["tests/test_app.py"],
        requires_full_context=False,
    )

    effective = _review_config_for_fast_path_decision(config, decision)

    assert effective.models.roles["primary_review"].tier == "economy"


def test_light_review_keeps_explicit_primary_model_pin() -> None:
    config = ReviewConfig(
        model=ReviewModelConfig(provider="openai", name="gpt-5.5", explicit=True),
        models=ModelsRoutingConfig(
            roles={"primary_review": ModelRoleRoutingConfig(tier="balanced")}
        ),
    )
    decision = FastPathDecision(
        decision="light_review",
        risk_labels=["low_risk"],
        reason="Small low-risk change.",
        confidence=90,
        review_surface=["tests/test_app.py"],
        requires_full_context=False,
    )

    effective = _review_config_for_fast_path_decision(config, decision)

    assert effective is config
    assert effective.models.roles["primary_review"].tier == "balanced"


def test_missing_confidence_guardrail_forces_economy_and_tighter_budgets() -> None:
    config = ReviewConfig()
    decision = FastPathDecision(
        decision="full_review",
        risk_labels=["missing_confidence"],
        reason="Fast-path model omitted confidence; escalated for safety.",
        confidence=None,
        review_surface=[],
        requires_full_context=True,
    )

    effective, applied = _apply_missing_confidence_guardrail(config, decision)

    assert applied is True
    assert effective.models.roles["primary_review"].tier == "economy"
    assert effective.budgets.diff_hunks <= config.budgets.diff_hunks
    assert effective.budgets.surrounding_context <= config.budgets.surrounding_context


def test_missing_confidence_guardrail_noop_when_label_absent() -> None:
    config = ReviewConfig()
    decision = FastPathDecision(
        decision="full_review",
        risk_labels=["low_confidence"],
        reason="Escalated for low confidence.",
        confidence=60,
        review_surface=[],
        requires_full_context=True,
    )

    effective, applied = _apply_missing_confidence_guardrail(config, decision)

    assert applied is False
    assert effective is config


def test_extract_tool_call_history_collects_tool_use_blocks() -> None:
    history = extract_tool_call_history(
        [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "fetch_file_content", "input": {"path": "a.py"}},
                    {"type": "text", "text": "ignored"},
                ],
            }
        ]
    )
    assert history == [{"name": "fetch_file_content", "input": {"path": "a.py"}}]


def test_cross_check_tool_evidence_rejects_missing_claimed_tool() -> None:
    finding = _finding("a.py")
    finding.evidence = "tool_verified"
    finding.evidence_tool_calls = ["search_codebase"]
    accepted, rejected = cross_check_tool_evidence(
        [finding],
        [{"name": "fetch_file_content", "input": {"path": "a.py"}}],
    )
    assert not accepted
    assert len(rejected) == 1
    assert "claimed tool calls not in history" in rejected[0][1]


def test_cross_check_fact_ids_rejects_unknown_fact() -> None:
    finding = _finding("a.py")
    finding.evidence = "verified_fact"
    finding.evidence_fact_id = "unknown_id"
    accepted, rejected = cross_check_fact_ids([finding], {"known_id"})
    assert not accepted
    assert len(rejected) == 1
    assert "unknown fact id" in rejected[0][1]


def test_apply_review_config_filters_enforces_category_severity_ignore_and_cap() -> None:
    high_security = _finding("src/auth.py", confidence=95)
    high_security.severity = "high"
    high_security.category = "security"

    medium_correctness = _finding("src/core.py", confidence=90)
    medium_correctness.severity = "medium"
    medium_correctness.category = "correctness"

    ignored_file = _finding("docs/guide.md", confidence=99)
    ignored_file.severity = "high"
    ignored_file.category = "security"

    result = ReviewResult(
        findings=[high_security, medium_correctness, ignored_file], summary="Summary"
    )
    config = ReviewConfig(
        severity_threshold="medium",
        categories=["security", "correctness"],
        ignore_paths=["docs/**"],
        max_findings_per_pr=1,
    )
    filtered = _apply_review_config_filters(result, config)
    assert len(filtered.findings) == 1
    assert filtered.findings[0].file_path == "src/auth.py"


def test_calculate_conflict_score_accounts_for_overlap() -> None:
    primary = [_finding("a.py"), _finding("b.py")]
    challenger = [_finding("a.py"), _finding("c.py")]
    score = _calculate_conflict_score(primary, challenger)
    # Union size 3, overlap 1 → disagreement 2 → round(2/3 * 100) == 67
    assert score == 67


def test_merge_debate_results_keeps_consensus_findings() -> None:
    primary = ReviewResult(findings=[_finding("a.py"), _finding("b.py")], summary="Primary")
    challenger = ReviewResult(findings=[_finding("a.py"), _finding("c.py")], summary="Challenger")
    tie_break = ReviewResult(findings=[_finding("a.py"), _finding("c.py")], summary="Tie")
    merged = _merge_debate_results(primary=primary, challenger=challenger, tie_break=tie_break)
    assert len(merged.findings) == 2
    assert {item.file_path for item in merged.findings} == {"a.py", "c.py"}


def test_dedupe_findings_preserves_distinct_categories_for_same_line() -> None:
    security_finding = _finding("src/auth.py", confidence=91)
    security_finding.category = "security"
    security_finding.message = "Unsanitized redirect target."
    correctness_finding = _finding("src/auth.py", confidence=89)
    correctness_finding.category = "correctness"
    correctness_finding.message = "Unsanitized redirect target."
    deduped = dedupe_findings([security_finding, correctness_finding])
    assert len(deduped) == 2


def test_anchor_metadata_and_validation_drop_invalid_anchor_lines() -> None:
    finding = _finding("src/core.py")
    finding.line_start = 8
    finding.line_end = 8
    files = [
        FileInDiff(
            path="src/core.py",
            language="Python",
            is_new=False,
            is_deleted=False,
            numbered_lines=[
                NumberedLine(
                    new_line_no=8, old_line_no=7, kind="add", content="value = transform(raw)"
                ),
                NumberedLine(new_line_no=9, old_line_no=8, kind="ctx", content="return value"),
            ],
            context_window=[],
        )
    ]
    with_anchor = attach_anchor_metadata([finding], files)
    assert with_anchor[0].patch_hunk is not None
    assert with_anchor[0].new_line_no == 8
    assert with_anchor[0].side == "RIGHT"

    invalid = _finding("src/core.py")
    invalid.line_start = 999
    invalid.line_end = 999
    filtered = filter_findings_with_valid_anchors([*with_anchor, invalid], files)
    assert len(filtered) == 1


def test_policy_filters_contract_equivalence_for_same_raw_findings() -> None:
    raw_findings = [_finding("src/a.py", confidence=92), _finding("src/b.py", confidence=70)]
    raw_findings[0].evidence = "diff_visible"
    raw_findings[1].evidence = "inference"
    left, _, _, _ = _apply_policy_filters(
        ReviewResult(findings=[item.model_copy(deep=True) for item in raw_findings], summary="raw"),
        threshold=85,
        tool_call_history=[],
        known_fact_ids=set(),
    )
    right, _, _, _ = _apply_policy_filters(
        ReviewResult(findings=[item.model_copy(deep=True) for item in raw_findings], summary="raw"),
        threshold=85,
        tool_call_history=[],
        known_fact_ids=set(),
    )
    assert [item.model_dump(mode="json") for item in left.findings] == [
        item.model_dump(mode="json") for item in right.findings
    ]


def test_chunking_config_hash_changes_when_chunking_knobs_change() -> None:
    base = ReviewConfig()
    changed = ReviewConfig()
    changed.chunking.max_chunks = base.chunking.max_chunks + 1
    base_hash = _chunking_config_hash(base)
    assert base_hash == _chunking_config_hash(base)
    assert len(base_hash) == 64
    assert _chunking_config_hash(base) != _chunking_config_hash(changed)


@pytest.mark.anyio
async def test_run_chunked_review_skips_failed_chunk_and_returns_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_in_diff = FileInDiff(
        path="src/example.py",
        language="Python",
        is_new=False,
        is_deleted=False,
        numbered_lines=[
            NumberedLine(new_line_no=1, old_line_no=1, kind="add", content="print('x')")
        ],
        context_window=[],
    )
    classified = ClassifiedDiffFile(
        path=file_in_diff.path,
        file_class="reviewable",
        changed_lines=1,
        estimated_diff_tokens=8,
        integration_key="src/example.py",
        touched_package="src",
        dependency_hint=None,
        file_in_diff=file_in_diff,
    )
    chunk_plan = ChunkPlan(
        chunks=(
            PlannedChunk(
                chunk_id="chunk-1",
                files=(classified,),
                estimated_prompt_tokens=64,
                estimated_output_tokens=64,
            ),
        ),
        skipped_files=(),
        is_partial=False,
        coverage_note="Chunked coverage note.",
        total_estimated_prompt_tokens=64,
        total_estimated_output_tokens=64,
        touched_packages=("src",),
        dependency_hints=(),
        full_manifest=("src/example.py",),
    )

    monkeypatch.setattr("app.agent.runner.parse_diff", lambda _diff: [file_in_diff])
    monkeypatch.setattr("app.agent.runner._filter_diff_files", lambda files, _ignore: files)
    monkeypatch.setattr("app.agent.runner.plan_chunks", lambda *_args, **_kwargs: chunk_plan)

    async def _fake_profile_repo(*_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(frameworks=[])

    monkeypatch.setattr("app.agent.runner.profile_repo", _fake_profile_repo)
    monkeypatch.setattr("app.agent.runner._build_repo_segments", lambda *_args, **_kwargs: [])

    async def _fake_load_chunk_state(
        *_args: object, **_kwargs: object
    ) -> dict[str, dict[str, object]]:
        return {}

    monkeypatch.setattr("app.agent.runner.load_chunk_state", _fake_load_chunk_state)
    monkeypatch.setattr(
        "app.agent.runner.merge_chunk_state_with_plan", lambda *_args, **_kwargs: {}
    )
    monkeypatch.setattr("app.agent.runner.chunk_status", lambda *_args, **_kwargs: "pending")

    async def _fake_build_context_bundle(*_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(
            rendered="ctx",
            fetched_files={file_in_diff.path: "print('x')"},
            telemetry=ContextTelemetry(anchor_coverage=1.0),
        )

    monkeypatch.setattr("app.agent.runner.build_context_bundle", _fake_build_context_bundle)
    monkeypatch.setattr(
        "app.agent.runner.render_chunk_diff", lambda *_args, **_kwargs: "diff -- chunk"
    )
    monkeypatch.setattr("app.agent.runner.build_system_prompt", lambda *_args, **_kwargs: "system")
    monkeypatch.setattr(
        "app.agent.runner.build_initial_user_prompt", lambda *_args, **_kwargs: "user"
    )
    monkeypatch.setattr(
        "app.agent.runner._resolve_runtime_model",
        lambda *_args, **_kwargs: ModelResolution(
            role="chunk_review",
            provider="anthropic",
            model="claude-sonnet-4-5",
            tier="balanced",
            status="active",
            catalog_version_hash="hash",
        ),
    )
    monkeypatch.setattr("app.agent.runner.count_tokens", lambda _text: 1)

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.agent.runner.persist_chunk_state", _noop)

    async def _ok_run_agent(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return [{"role": "assistant", "content": []}]

    async def _failing_finalize(*_args: object, **_kwargs: object) -> ReviewResult:
        raise RuntimeError("finalize exploded")

    monkeypatch.setattr("app.agent.runner.run_agent", _ok_run_agent)
    monkeypatch.setattr("app.agent.runner.finalize_review", _failing_finalize)

    async def _fake_synthesis(**_kwargs: object) -> ReviewResult:
        return ReviewResult(findings=[], summary="Cross-chunk synthesis summary.")

    monkeypatch.setattr("app.agent.runner._run_cross_chunk_synthesis", _fake_synthesis)
    monkeypatch.setattr("app.agent.runner.dedupe_findings", lambda findings: findings)

    result = await _run_chunked_review(
        gh=SimpleNamespace(),
        context={"owner": "o", "repo": "r", "pr_number": 1, "head_sha": "abc", "tokens_used": 0},
        diff_text="diff --git a/src/example.py b/src/example.py\n+print('x')\n",
        pr={"title": "T", "body": "B"},
        commits=[],
        review_config=ReviewConfig(),
        started_at=monotonic(),
    )

    assert isinstance(result, ReviewResult)
    assert result.findings == []
    assert "Chunked coverage note." in result.summary
