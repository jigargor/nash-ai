from app.agent.normalization import normalize_file_content, normalize_for_match


def test_normalize_file_content_converts_crlf_and_cr() -> None:
    content = "a\r\nb\rc\n"
    assert normalize_file_content(content) == "a\nb\nc\n"


def test_normalize_for_match_handles_bom_tabs_and_trailing_whitespace() -> None:
    content = "\ufeff\tvalue = 1  "
    assert normalize_for_match(content) == "    value = 1"
