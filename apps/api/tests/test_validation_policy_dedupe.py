"""Validation module: exception safety, suggestion checks, near-dedupe, policy, vendor tags."""

from __future__ import annotations

from typing import Any

from app.agent.dedupe import dedupe_findings
from app.agent.languages import language_for_path
from app.agent.policy import apply_policy_filters
from app.agent.schema import Finding, ReviewResult
from app.agent.validator import FindingValidator, apply_suggestion_github_exact
from app.agent.vendor_detect import looks_like_vendor_claim

CONTENT = "def f(x):\n    if x:\n        return 1\n    return 0\n"


def _finding(**overrides: Any) -> Finding:
    payload: dict[str, Any] = {
        "severity": "medium",
        "category": "correctness",
        "message": "Return value is inverted for falsy input; swap the branches.",
        "file_path": "m.py",
        "line_start": 3,
        "target_line_content": "        return 1",
        "confidence": 88,
        "evidence": "diff_visible",
    }
    payload.update(overrides)
    return Finding.model_validate(payload)


def test_validate_never_raises_on_broken_file_map() -> None:
    validator = FindingValidator({"m.py": None})  # type: ignore[dict-item]
    ok, reason, detail = validator.validate(_finding())
    assert ok is False
    assert reason == "validator_error"
    assert detail and "validator exception" in detail


def test_validate_rejects_suggestion_over_20_lines_and_bad_indent() -> None:
    validator = FindingValidator({"m.py": CONTENT})
    too_long = _finding(suggestion="\n".join(["        pass"] * 21))
    assert validator.validate(too_long)[1] == "incoherent_suggestion"
    bad_indent = _finding(suggestion="return 2  # dedented")
    assert validator.validate(bad_indent)[1] == "incoherent_suggestion"


def test_validate_accepts_github_exact_suggestion() -> None:
    validator = FindingValidator({"m.py": CONTENT}, commentable_lines={("m.py", 3)})
    good = _finding(suggestion="        return 2")
    ok, reason, _ = validator.validate(good)
    assert ok is True and reason is None
    assert apply_suggestion_github_exact(CONTENT, good) == "def f(x):\n    if x:\n        return 2\n    return 0\n"


def test_language_map_covers_pack_languages() -> None:
    assert language_for_path("a.kt") == "kotlin"
    assert language_for_path("a.rb") == "ruby"
    assert language_for_path("a.cs") == "c_sharp"
    assert language_for_path("Makefile") is None


def test_near_duplicates_collapse_to_highest_severity() -> None:
    a = _finding(line_start=3, severity="medium", confidence=80)
    b = _finding(line_start=4, target_line_content="    return 0", severity="high", confidence=70)
    deduped = dedupe_findings([a, b])
    assert len(deduped) == 1
    assert deduped[0].severity == "high"


def test_policy_filters_threshold_and_tool_evidence() -> None:
    low = _finding(confidence=60)
    claimed = _finding(
        evidence="tool_verified", evidence_tool_calls=["fetch_file_content"], confidence=95
    )
    result, confidence_dropped, rejections, reasons = apply_policy_filters(
        ReviewResult(findings=[low, claimed], summary="s"),
        threshold=85,
        tool_call_history=[],  # nothing was actually called
        known_fact_ids=set(),
    )
    assert result.findings == []
    assert len(confidence_dropped) == 1
    assert len(rejections) == 1 and "missing" not in rejections[0][1]
    assert sum(reasons.values()) == 1


def test_vendor_detection_ignores_common_programming_words() -> None:
    assert looks_like_vendor_claim("Use a lambda here to defer evaluation.") is False
    assert looks_like_vendor_claim("Sanitize before you render as text.") is False
    assert looks_like_vendor_claim("Vercel strips this header at the edge.") is True
    assert looks_like_vendor_claim("AWS Lambda cold starts will spike.") is True
