from pydantic import ValidationError

from app.agent.finalize import _build_schema_feedback, _repair_review_input
from app.agent.schema import ReviewResult


def test_repair_review_input_truncates_long_summary() -> None:
    long_summary = "a" * 1200
    repaired = _repair_review_input({"findings": [], "summary": long_summary})
    assert isinstance(repaired, dict)
    assert len(repaired["summary"]) == 1000


def test_repair_review_input_removes_dangling_bullet_from_summary() -> None:
    repaired = _repair_review_input(
        {
            "findings": [],
            "summary": "## Overview\n- First point\n-",
        }
    )
    assert isinstance(repaired, dict)
    assert repaired["summary"].endswith("- First point")


def test_repair_review_input_sanitizes_finding_message() -> None:
    repaired = _repair_review_input(
        {
            "summary": "ok",
            "findings": [
                {
                    "message": "Looks risky\n-",
                    "file_path": "a.py",
                    "line_start": 1,
                    "target_line_content": "x=1",
                    "target_line_content_reasoning": "reason",
                    "severity": "low",
                    "category": "style",
                    "confidence": 0.9,
                }
            ],
        }
    )
    assert isinstance(repaired, dict)
    assert repaired["findings"][0]["message"] == "Looks risky"


def test_build_schema_feedback_includes_error_locations() -> None:
    try:
        ReviewResult.model_validate({"findings": [], "summary": "b" * 1201})
    except ValidationError as exc:
        feedback = _build_schema_feedback(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValidationError was not raised")

    assert "summary" in feedback
    assert "at most 1000 characters" in feedback
