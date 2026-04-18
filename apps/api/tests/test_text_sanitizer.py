from app.agent.text_sanitizer import sanitize_markdown_text, truncate_markdown_text


def test_sanitize_markdown_text_removes_trailing_empty_bullet() -> None:
    text = "## Summary\n- Item one\n-"
    assert sanitize_markdown_text(text) == "## Summary\n- Item one"


def test_truncate_markdown_text_prefers_safe_boundary() -> None:
    text = "Header\n\n- point one\n- point two\n- point three"
    truncated = truncate_markdown_text(text, 25)
    assert len(truncated) <= 25
    assert not truncated.endswith("-")
