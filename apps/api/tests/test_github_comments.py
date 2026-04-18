from app.agent.schema import Finding
from app.github.comments import format_finding


def test_format_finding_sanitizes_message_tail() -> None:
    finding = Finding.model_validate(
        {
            "severity": "medium",
            "category": "correctness",
            "message": "Details\n-",
            "file_path": "a.py",
            "line_start": 1,
            "target_line_content": "x = 1",
            "target_line_content_reasoning": "Reason",
            "suggestion": None,
            "confidence": 0.9,
        }
    )
    body = format_finding(finding)
    assert "Details\n-" not in body
    assert "Details" in body
