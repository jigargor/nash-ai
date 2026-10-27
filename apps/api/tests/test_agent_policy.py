from __future__ import annotations

from typing import Any

from app.agent.policy import (
    INFERENCE_CONFIDENCE_FLOOR,
    apply_confidence_threshold,
    apply_policy_filters,
    effective_confidence_threshold,
)
from app.agent.schema import Finding, ReviewResult


def _finding(**overrides: Any) -> Finding:
    payload: dict[str, Any] = {
        "severity": "medium",
        "category": "correctness",
        "message": "Return value is inverted for falsy input; swap the branches.",
        "file_path": "m.py",
        "line_start": 3,
        "target_line_content": "        return 1",
        "confidence": 90,
        "evidence": "diff_visible",
    }
    payload.update(overrides)
    return Finding.model_validate(payload)


def test_inference_finding_above_floor_survives_default_threshold() -> None:
    finding = _finding(evidence="inference", confidence=70)

    result, dropped = apply_confidence_threshold(
        ReviewResult(findings=[finding], summary="s"), threshold=85
    )

    assert result.findings == [finding]
    assert dropped == []


def test_inference_finding_at_schema_cap_survives() -> None:
    finding = _finding(evidence="inference", confidence=75, severity="low")

    result, dropped = apply_confidence_threshold(
        ReviewResult(findings=[finding], summary="s"), threshold=85
    )

    assert len(result.findings) == 1
    assert dropped == []


def test_inference_finding_below_floor_is_dropped_with_effective_threshold() -> None:
    finding = _finding(evidence="inference", confidence=INFERENCE_CONFIDENCE_FLOOR - 1)

    result, dropped = apply_confidence_threshold(
        ReviewResult(findings=[finding], summary="s"), threshold=85
    )

    assert result.findings == []
    assert dropped[0]["threshold"] == INFERENCE_CONFIDENCE_FLOOR
    assert dropped[0]["evidence"] == "inference"


def test_non_inference_tiers_still_use_configured_threshold() -> None:
    kept = _finding(evidence="diff_visible", confidence=90)
    dropped_diff = _finding(evidence="diff_visible", confidence=70, file_path="b.py")
    dropped_tool = _finding(
        evidence="tool_verified",
        evidence_tool_calls=["fetch_file_content"],
        confidence=70,
        file_path="c.py",
    )

    result, dropped = apply_confidence_threshold(
        ReviewResult(findings=[kept, dropped_diff, dropped_tool], summary="s"), threshold=85
    )

    assert [item.file_path for item in result.findings] == ["m.py"]
    assert {item["file_path"] for item in dropped} == {"b.py", "c.py"}
    assert all(item["threshold"] == 85 for item in dropped)


def test_effective_threshold_never_exceeds_configured_threshold() -> None:
    finding = _finding(evidence="inference", confidence=40)

    assert effective_confidence_threshold(finding, threshold=30) == 30
    assert effective_confidence_threshold(finding, threshold=85) == INFERENCE_CONFIDENCE_FLOOR


def test_policy_filters_keep_inference_but_reject_unverified_tool_claims() -> None:
    inference = _finding(evidence="inference", confidence=65)
    claimed = _finding(
        evidence="tool_verified",
        evidence_tool_calls=["fetch_file_content"],
        confidence=95,
        file_path="other.py",
    )

    result, confidence_dropped, rejections, _ = apply_policy_filters(
        ReviewResult(findings=[inference, claimed], summary="s"),
        threshold=85,
        tool_call_history=[],
        known_fact_ids=set(),
    )

    assert result.findings == [inference]
    assert confidence_dropped == []
    assert len(rejections) == 1
