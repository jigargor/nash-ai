from pydantic import ValidationError

from app.agent.finalize import _build_schema_feedback, _repair_review_input
from app.agent.schema import ReviewResult


def test_repair_review_input_truncates_long_summary() -> None:
    long_summary = "a" * 1200
    repaired = _repair_review_input({"findings": [], "summary": long_summary})
    assert isinstance(repaired, dict)
    assert len(repaired["summary"]) == 1000


def test_build_schema_feedback_includes_error_locations() -> None:
    try:
        ReviewResult.model_validate({"findings": [], "summary": "b" * 1201})
    except ValidationError as exc:
        feedback = _build_schema_feedback(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValidationError was not raised")

    assert "summary" in feedback
    assert "at most 1000 characters" in feedback
