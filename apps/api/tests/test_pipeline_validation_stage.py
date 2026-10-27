"""Golden-ish tests for the shared validation stage (runner + review_pipeline both use it)."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.diff_parser import parse_diff, right_side_diff_line_set
from app.agent.pipeline.review_pipeline import review_pipeline
from app.agent.pipeline.validation_stage import (
    apply_config_filters,
    run_validation_stage,
    validate_findings,
)
from app.agent.review_config import ReviewConfig
from app.agent.schema import Finding, PRContext, ReviewResult

FILE = "app/webhooks/verify.py"
CONTENT = (
    "import hmac\n"
    "\n"
    "def verify(secret: bytes, body: bytes, signature: str) -> bool:\n"
    "    expected = hmac.new(secret, body, 'sha256').hexdigest()\n"
    "    return expected == signature\n"
)
DIFF = (
    f"diff --git a/{FILE} b/{FILE}\n"
    f"--- a/{FILE}\n"
    f"+++ b/{FILE}\n"
    "@@ -2,4 +2,4 @@\n"
    " \n"
    " def verify(secret: bytes, body: bytes, signature: str) -> bool:\n"
    "     expected = hmac.new(secret, body, 'sha256').hexdigest()\n"
    "-    return hmac.compare_digest(expected, signature)\n"
    "+    return expected == signature\n"
)


def _finding(**overrides: Any) -> Finding:
    payload: dict[str, Any] = {
        "severity": "high",
        "category": "security",
        "message": "Signature compared with == instead of hmac.compare_digest (timing leak).",
        "file_path": FILE,
        "line_start": 5,
        "target_line_content": "    return expected == signature",
        "suggestion": "    return hmac.compare_digest(expected, signature)",
        "confidence": 92,
        "evidence": "diff_visible",
    }
    payload.update(overrides)
    return Finding.model_validate(payload)


def _run(findings: list[Finding], config: ReviewConfig | None = None, **kwargs: Any):  # type: ignore[no-untyped-def]
    files_in_diff = parse_diff(DIFF)
    return run_validation_stage(
        findings,
        summary="summary",
        file_contents={FILE: CONTENT},
        files_in_diff=files_in_diff,
        commentable_lines=right_side_diff_line_set(files_in_diff),
        config=config or ReviewConfig(confidence_threshold=85),
        ignore_paths=kwargs.pop("ignore_paths", []),
        tool_call_history=[],
        known_fact_ids=set(),
        **kwargs,
    )


def test_validation_stage_keeps_valid_finding_with_no_drops() -> None:
    outcome = _run([_finding()])

    assert len(outcome.kept) == 1
    assert outcome.drops == []


def test_validation_stage_drop_reasons_match_per_stage() -> None:
    findings = [
        _finding(),  # kept
        _finding(file_path="missing/file.py"),  # validation:file_not_in_context
        _finding(line_start=999, target_line_content="nope"),  # validation:line_out_of_range
        _finding(
            line_start=3,
            target_line_content="def verify(secret: bytes, body: bytes, signature: str) -> bool:",
            suggestion=None,
            confidence=40,
            message="Low confidence nit about the signature of verify.",
        ),  # validation passes (line 3 is context-only?) -> policy:below_confidence_threshold
    ]
    outcome = _run(findings)

    keys = outcome.drop_keys()
    assert "validation:file_not_in_context" in keys
    assert "validation:line_out_of_range" in keys or "validation:line_not_in_diff" in keys
    assert [f.line_start for f in outcome.kept] == [5]
    # Every dropped finding is accounted for exactly once.
    assert len(outcome.kept) + len(outcome.drops) == len(findings)


def test_validation_stage_confidence_and_severity_filters_report_policy_drops() -> None:
    config = ReviewConfig(confidence_threshold=85, severity_threshold="high")
    findings = [
        _finding(),
        _finding(
            severity="medium",
            message="Medium severity variant of the same signature comparison issue.",
        ),
    ]
    outcome = _run(findings, config)

    assert [f.severity for f in outcome.kept] == ["high"]
    assert outcome.drop_keys() == ["policy:below_severity_threshold"]


def test_validation_stage_dedupes_exact_duplicates() -> None:
    outcome = _run([_finding(), _finding(confidence=90)])

    assert len(outcome.kept) == 1
    assert outcome.drop_keys() == ["dedupe:duplicate"]


def test_validation_stage_ignore_paths_and_cap() -> None:
    outcome = _run([_finding()], ignore_paths=["app/webhooks/*"])
    assert outcome.kept == []
    assert outcome.drop_keys() == ["policy:ignored_path"]

    capped, drops = apply_config_filters(
        [_finding(), _finding(line_start=4, message="Second distinct issue on the hmac line.")],
        ReviewConfig(max_findings_per_pr=1),
        [],
    )
    assert len(capped) == 1
    assert [d.reason for d in drops] == ["max_findings_per_pr"]


def test_validate_findings_returns_dropped_snapshot_with_detail() -> None:
    kept, drops = validate_findings(
        [_finding(file_path="missing/file.py")],
        file_contents={FILE: CONTENT},
        commentable_lines=None,
    )

    assert kept == []
    assert drops[0].reason == "file_not_in_context"
    assert drops[0].stage == "validation"
    assert drops[0].detail and "missing/file.py" in drops[0].detail


class _FakeGitHub:
    """Minimal GitHubReader for the context-bundle path (only get_file_content is used)."""

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        assert path == FILE
        return CONTENT


async def _agent(
    system_prompt: str, user_prompt: str, context: dict[str, Any], **_: Any
) -> list[dict[str, Any]]:
    context["captured_user_prompt"] = user_prompt
    context["llm_mode"] = "test"
    return [{"role": "user", "content": user_prompt}]


@pytest.mark.anyio
async def test_review_pipeline_uses_context_bundle_when_github_reader_present() -> None:
    async def _finalize(*_a: Any, **_k: Any) -> ReviewResult:
        return ReviewResult(findings=[_finding()], summary="One issue.")

    pr = PRContext(
        owner="acme",
        repo="demo",
        pr_number=7,
        head_sha="a" * 40,
        diff_text=DIFF,
    )
    report = await review_pipeline(
        pr,
        github=_FakeGitHub(),  # type: ignore[arg-type]
        agent_runner=_agent,
        finalizer=_finalize,
    )

    assert report.debug_artifacts["context_source"] == "context_bundle"
    assert len(report.result.findings) == 1  # file contents came from the bundle fetch
    assert report.pipeline_errors == []
