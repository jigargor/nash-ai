from app.agent.schema import Finding
from app.agent.validator import FindingValidator


def _base_finding(**overrides) -> Finding:
    payload = {
        "severity": "high",
        "category": "correctness",
        "message": "This line can throw and should be guarded.",
        "file_path": "a.py",
        "line_start": 1,
        "line_end": 1,
        "target_line_content": "value = int(user_input)",
        "suggestion": "try:\n    value = int(user_input)\nexcept ValueError:\n    value = 0",
        "confidence": 95,
        "evidence": "tool_verified",
        "evidence_tool_calls": ["fetch_file_content"],
    }
    payload.update(overrides)
    return Finding.model_validate(payload)


def test_validator_rejects_when_target_line_content_does_not_match() -> None:
    validator = FindingValidator({"a.py": "value = int(input_value)\nprint(value)"})
    finding = _base_finding()
    is_valid, reason, detail = validator.validate(finding)
    assert not is_valid
    assert reason == "target_line_mismatch"
    assert detail == "target_line_content does not match file content at line_start"


def test_validator_accepts_valid_replacement() -> None:
    validator = FindingValidator({"a.py": "value = int(user_input)\nprint(value)"})
    finding = _base_finding()
    is_valid, reason, detail = validator.validate(finding)
    assert is_valid
    assert reason is None
    assert detail is None


def test_validator_rejects_when_line_not_in_pr_diff() -> None:
    validator = FindingValidator(
        {"a.py": "value = int(user_input)\nprint(value)"},
        commentable_lines={("a.py", 2)},
    )
    finding = _base_finding()
    is_valid, reason, detail = validator.validate(finding)
    assert not is_valid
    assert reason == "line_not_in_diff"
    assert detail is not None
    assert "not part of the pull request diff" in detail


def test_validator_rejects_incoherent_suggestion() -> None:
    validator = FindingValidator({"a.py": "value = int(user_input)\nprint(value)"})
    finding = _base_finding(
        message="Completely unrelated feedback text",
        suggestion="print('hello world')",
    )
    is_valid, reason, detail = validator.validate(finding)
    assert not is_valid
    assert reason == "incoherent_suggestion"
    assert detail == "Suggestion does not coherently replace the target region"


def test_validator_accepts_target_line_with_crlf_file_content() -> None:
    validator = FindingValidator({"a.py": "value = int(user_input)\r\nprint(value)\r\n"})
    finding = _base_finding()
    is_valid, reason, detail = validator.validate(finding)
    assert is_valid
    assert reason is None
    assert detail is None


def test_validator_rejects_target_line_with_trailing_whitespace_mismatch() -> None:
    validator = FindingValidator({"a.py": "value = int(user_input)  \nprint(value)"})
    finding = _base_finding()
    is_valid, reason, detail = validator.validate(finding)
    assert not is_valid
    assert reason == "target_line_mismatch"
    assert detail == "target_line_content does not match file content at line_start"


def test_validator_rejects_target_line_with_bom_character_mismatch() -> None:
    validator = FindingValidator({"a.py": "\ufeffvalue = int(user_input)\nprint(value)"})
    finding = _base_finding()
    is_valid, reason, detail = validator.validate(finding)
    assert not is_valid
    assert reason == "target_line_mismatch"
    assert detail == "target_line_content does not match file content at line_start"


def test_validator_rejects_target_line_with_tab_space_mismatch() -> None:
    validator = FindingValidator({"a.py": "value\t= int(user_input)\nprint(value)"})
    finding = _base_finding(target_line_content="value    = int(user_input)")
    is_valid, reason, detail = validator.validate(finding)
    assert not is_valid
    assert reason == "target_line_mismatch"
    assert detail == "target_line_content does not match file content at line_start"


def test_validator_content_match_is_bounded_to_finding_range() -> None:
    content = "x = 1\ny = 2\nz = 3\nprint(y)"
    validator = FindingValidator({"a.py": content})
    # Content exists in the file, but only outside [line_start, line_end] -> must be rejected.
    outside = _base_finding(
        line_start=1,
        line_end=2,
        target_line_content="z = 3",
        suggestion=None,
        evidence="diff_visible",
        evidence_tool_calls=None,
    )
    is_valid, reason, _ = validator.validate(outside)
    assert not is_valid
    assert reason == "target_line_mismatch"


def test_validator_content_match_ignores_earlier_duplicate_outside_range() -> None:
    content = "x = 1\ny = 2\nx = 1\nprint(y)"
    validator = FindingValidator({"a.py": content})
    # First file-wide match (line 1) is before line_start; the in-range duplicate must win.
    finding = _base_finding(
        line_start=2,
        line_end=3,
        target_line_content="x = 1",
        suggestion=None,
        evidence="diff_visible",
        evidence_tool_calls=None,
    )
    is_valid, reason, _ = validator.validate(finding)
    assert is_valid
    assert reason is None


def test_validator_rejects_indented_suggestion_for_top_level_target() -> None:
    validator = FindingValidator({"a.py": "value = int(user_input)\nprint(value)"})
    finding = _base_finding(suggestion="    value = int(user_input) or 0")
    is_valid, reason, detail = validator.validate(finding)
    assert not is_valid
    assert reason == "incoherent_suggestion"
    assert detail == "Suggestion indentation does not match target line"


def test_validator_rejects_top_level_suggestion_whose_first_non_empty_line_is_indented() -> None:
    validator = FindingValidator({"a.py": "value = int(user_input)\nprint(value)"})
    finding = _base_finding(suggestion="\n    value = int(user_input) or 0")
    is_valid, reason, _ = validator.validate(finding)
    assert not is_valid
    assert reason == "incoherent_suggestion"