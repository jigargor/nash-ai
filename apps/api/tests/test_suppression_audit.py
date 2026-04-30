from app.agent.schema import EditedReview, ReviewResult
from app.agent.suppression_audit import candidate_summary_hash, run_suppression_audit


def _finding(
    *, severity: str = "high", message: str = "Unsafe SQL query.", line_start: int = 10
) -> dict[str, object]:
    return {
        "severity": severity,
        "category": "security",
        "message": message,
        "file_path": "src/app.py",
        "line_start": line_start,
        "line_end": line_start,
        "target_line_content": "query = f'SELECT * FROM users'",
        "suggestion": None,
        "confidence": 90,
        "evidence": "diff_visible",
    }


def test_summary_hash_is_stable() -> None:
    finding = ReviewResult.model_validate({"findings": [_finding()], "summary": "x"}).findings[0]
    assert candidate_summary_hash(finding) == candidate_summary_hash(finding)


def test_suppression_audit_marks_missing_high_risk_as_unresolved() -> None:
    draft = ReviewResult.model_validate({"findings": [_finding()], "summary": "draft"})
    edited = EditedReview.model_validate({"findings": [], "summary": "final", "decisions": []})

    audit = run_suppression_audit(draft, edited, high_critical_only=True)
    assert len(audit.suppressed) == 1
    assert audit.suppressed[0].reason_code == "missing_from_final"
    assert audit.suppressed[0].unresolved is True
    assert len(audit.unresolved_high_risk) == 1


def test_suppression_audit_detects_severity_downgrade() -> None:
    draft = ReviewResult.model_validate({"findings": [_finding(severity="high")], "summary": "draft"})
    edited = EditedReview.model_validate(
        {
            "findings": [_finding(severity="medium")],
            "summary": "final",
            "decisions": [{"original_index": 0, "action": "modify", "reason": "tone down"}],
        }
    )

    audit = run_suppression_audit(draft, edited, high_critical_only=False)
    assert len(audit.suppressed) == 1
    assert audit.suppressed[0].reason_code == "severity_downgraded_without_evidence"


def test_suppression_audit_respects_high_critical_only_filter() -> None:
    draft = ReviewResult.model_validate(
        {"findings": [_finding(severity="medium")], "summary": "draft"}
    )
    edited = EditedReview.model_validate({"findings": [], "summary": "final", "decisions": []})

    audit = run_suppression_audit(draft, edited, high_critical_only=True)
    assert not audit.suppressed

