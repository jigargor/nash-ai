from app.agent.runner import _validate_result, _validation_feedback
from app.agent.schema import Finding, ReviewResult


class FakeValidator:
    def validate(self, finding: Finding) -> tuple[bool, str | None]:
        if finding.file_path == "bad.py":
            return False, "line_start 99 out of range"
        return True, None


def _finding(file_path: str, confidence: float = 0.9) -> Finding:
    return Finding.model_validate(
        {
            "severity": "medium",
            "category": "correctness",
            "message": "Potential bug in this statement.",
            "file_path": file_path,
            "line_start": 1,
            "line_end": 1,
            "target_line_content": "x = 1",
            "target_line_content_reasoning": "This value is overwritten unexpectedly.",
            "suggestion": None,
            "confidence": confidence,
        }
    )


def test_validate_result_drops_invalid_findings() -> None:
    result = ReviewResult(findings=[_finding("ok.py"), _finding("bad.py")], summary="Summary")
    validated, dropped, generated = _validate_result(result, FakeValidator())
    assert generated == 2
    assert len(validated.findings) == 1
    assert validated.findings[0].file_path == "ok.py"
    assert len(dropped) == 1
    assert dropped[0][1] == "line_start 99 out of range"


def test_validation_feedback_contains_reason_and_location() -> None:
    dropped = [(_finding("bad.py"), "line_start 99 out of range")]
    feedback = _validation_feedback(dropped)
    assert "bad.py:1-1" in feedback
    assert "line_start 99 out of range" in feedback
