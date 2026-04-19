from app.agent.schema import Finding
from app.github.comments import build_review_comment_payload, format_finding


def test_build_review_comment_payload_adds_start_line_for_multiline() -> None:
    finding = Finding.model_validate(
        {
            "severity": "medium",
            "category": "correctness",
            "message": "Multi-line issue.",
            "file_path": "x.ts",
            "line_start": 2,
            "line_end": 5,
            "target_line_content": "first",
            "target_line_content_reasoning": "Reason",
            "suggestion": None,
            "confidence": 0.9,
        }
    )
    payload = build_review_comment_payload(finding)
    assert payload["line"] == 5
    assert payload["start_line"] == 2
    assert payload["start_side"] == "RIGHT"


def test_build_review_comment_payload_omits_start_line_when_single_line() -> None:
    finding = Finding.model_validate(
        {
            "severity": "low",
            "category": "style",
            "message": "Nit.",
            "file_path": "x.ts",
            "line_start": 1,
            "line_end": None,
            "target_line_content": "x",
            "target_line_content_reasoning": "Reason",
            "suggestion": None,
            "confidence": 0.9,
        }
    )
    payload = build_review_comment_payload(finding)
    assert payload["line"] == 1
    assert "start_line" not in payload


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
