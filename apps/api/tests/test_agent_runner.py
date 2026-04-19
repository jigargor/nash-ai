from app.agent.runner import _apply_confidence_threshold, _attach_debug_artifacts, _validate_result, _validation_feedback
from app.agent.schema import Finding, ReviewResult


class FakeValidator:
    def validate(self, finding: Finding) -> tuple[bool, str | None, str | None]:
        if finding.file_path == "bad.py":
            return False, "line_out_of_range", "line_start 99 out of range"
        return True, None, None


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
    assert dropped[0][1] == "line_out_of_range"
    assert dropped[0][2] == "line_start 99 out of range"


def test_validation_feedback_contains_reason_and_location() -> None:
    dropped = [(_finding("bad.py"), "line_out_of_range", "line_start 99 out of range")]
    feedback = _validation_feedback(dropped)
    assert "bad.py:1-1" in feedback
    assert "line_start 99 out of range" in feedback


def test_apply_confidence_threshold_tracks_dropped_metadata() -> None:
    result = ReviewResult(findings=[_finding("ok.py", 0.9), _finding("low.py", 0.7)], summary="Summary")
    filtered, dropped = _apply_confidence_threshold(result, threshold=0.85)
    assert len(filtered.findings) == 1
    assert filtered.findings[0].file_path == "ok.py"
    assert dropped[0]["file_path"] == "low.py"
    assert dropped[0]["threshold"] == 0.85


def test_attach_debug_artifacts_includes_drop_buckets() -> None:
    context: dict = {}
    _attach_debug_artifacts(
        context=context,
        generated=4,
        validator_dropped=[(_finding("bad.py"), "line_out_of_range", "invalid range")],
        confidence_dropped=[{"file_path": "low.py", "line_start": 1, "line_end": 1, "confidence": 0.5, "threshold": 0.85}],
        retry_triggered=True,
        threshold=0.85,
        context_telemetry={"anchor_coverage": 1.0},
    )
    artifacts = context["debug_artifacts"]
    assert artifacts["generated_findings_count"] == 4
    assert artifacts["retry_triggered"] is True
    assert artifacts["validator_dropped"][0]["reason"] == "line_out_of_range"
    assert artifacts["validator_dropped"][0]["detail"] == "invalid range"
    assert artifacts["confidence_dropped"][0]["file_path"] == "low.py"
