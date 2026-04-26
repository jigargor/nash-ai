from collections import Counter
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.agent.context_builder import ContextTelemetry
from app.agent.review_config import ReviewConfig, ReviewModelConfig
from app.agent.runner import (
    _apply_review_config_filters,
    _apply_confidence_threshold,
    _attach_debug_artifacts,
    _calculate_conflict_score,
    _merge_debate_results,
    _mark_review_done,
    _repair_findings_from_files,
    _summarize_target_line_mismatch_subtypes,
    _validate_result,
    _validation_feedback,
    cross_check_fact_ids,
    cross_check_tool_evidence,
    extract_tool_call_history,
)
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
    result = ReviewResult(findings=[_finding("ok.py", 90), _finding("low.py", 70)], summary="Summary")
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
        confidence_dropped=[{"file_path": "low.py", "line_start": 1, "line_end": 1, "confidence": 50, "threshold": 85}],
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
    dropped = [(mismatch, "target_line_mismatch", "target_line_content does not match file content at line_start")]
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
        debug_artifacts=None,
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

    result = ReviewResult(findings=[high_security, medium_correctness, ignored_file], summary="Summary")
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
