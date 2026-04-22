import pytest
from pydantic import ValidationError

from app.agent.schema import Finding


def _base_payload() -> dict[str, object]:
    return {
        "severity": "medium",
        "category": "correctness",
        "message": "Potential bug in this statement.",
        "file_path": "a.py",
        "line_start": 1,
        "line_end": 1,
        "target_line_content": "x = 1",
        "confidence": 70,
        "evidence": "diff_visible",
    }


def test_finding_rejects_critical_without_tool_verified() -> None:
    payload = _base_payload()
    payload["severity"] = "critical"
    payload["evidence"] = "diff_visible"
    with pytest.raises(ValidationError):
        Finding.model_validate(payload)


def test_finding_rejects_high_with_inference() -> None:
    payload = _base_payload()
    payload["severity"] = "high"
    payload["evidence"] = "inference"
    with pytest.raises(ValidationError):
        Finding.model_validate(payload)


def test_finding_requires_tool_calls_for_tool_verified() -> None:
    payload = _base_payload()
    payload["severity"] = "high"
    payload["evidence"] = "tool_verified"
    with pytest.raises(ValidationError):
        Finding.model_validate(payload)


def test_finding_rejects_inference_with_high_confidence() -> None:
    payload = _base_payload()
    payload["severity"] = "medium"
    payload["confidence"] = 90
    payload["evidence"] = "inference"
    with pytest.raises(ValidationError):
        Finding.model_validate(payload)


def test_vendor_claim_rejects_critical_without_tool_verified() -> None:
    payload = _base_payload()
    payload["is_vendor_claim"] = True
    payload["severity"] = "critical"
    payload["evidence"] = "verified_fact"
    payload["evidence_fact_id"] = "vercel_forwarded_for"
    with pytest.raises(ValidationError):
        Finding.model_validate(payload)


def test_vendor_claim_rejects_high_without_verified_evidence() -> None:
    payload = _base_payload()
    payload["is_vendor_claim"] = True
    payload["severity"] = "high"
    payload["evidence"] = "diff_visible"
    with pytest.raises(ValidationError):
        Finding.model_validate(payload)


def test_vendor_claim_caps_confidence_without_tool_verification() -> None:
    payload = _base_payload()
    payload["is_vendor_claim"] = True
    payload["severity"] = "medium"
    payload["evidence"] = "verified_fact"
    payload["evidence_fact_id"] = "vercel_forwarded_for"
    payload["confidence"] = 90
    with pytest.raises(ValidationError):
        Finding.model_validate(payload)
