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
        "target_line_content_reasoning": "Direct int conversion can raise ValueError.",
        "suggestion": "try:\n    value = int(user_input)\nexcept ValueError:\n    value = 0",
        "confidence": 0.95,
    }
    payload.update(overrides)
    return Finding.model_validate(payload)


def test_validator_rejects_when_target_line_content_does_not_match() -> None:
    validator = FindingValidator({"a.py": "value = int(input_value)\nprint(value)"})
    finding = _base_finding()
    is_valid, reason = validator.validate(finding)
    assert not is_valid
    assert reason == "target_line_content does not match file content at line_start"


def test_validator_accepts_valid_replacement() -> None:
    validator = FindingValidator({"a.py": "value = int(user_input)\nprint(value)"})
    finding = _base_finding()
    is_valid, reason = validator.validate(finding)
    assert is_valid
    assert reason is None


def test_validator_rejects_incoherent_suggestion() -> None:
    validator = FindingValidator({"a.py": "value = int(user_input)\nprint(value)"})
    finding = _base_finding(
        message="Completely unrelated feedback text",
        suggestion="print('hello world')",
    )
    is_valid, reason = validator.validate(finding)
    assert not is_valid
    assert reason == "Suggestion does not coherently replace the target region"
