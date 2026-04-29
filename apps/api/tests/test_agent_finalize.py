import pytest
from pydantic import ValidationError

from app.agent import finalize as finalize_module
from app.agent.finalize import (
    _build_schema_feedback,
    _repair_review_input,
    repair_edited_review_payload,
)
from app.agent.schema import EditedReview
from app.agent.review_config import ModelProvider
from app.agent.schema import ReviewResult
from app.llm.providers import StructuredOutputResult


def _minimal_finding(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "severity": "medium",
        "category": "correctness",
        "message": "Example finding within word limit for validation.",
        "file_path": "apps/api/src/x.py",
        "line_start": 1,
        "target_line_content": "pass",
        "confidence": 70,
        "evidence": "diff_visible",
    }
    row.update(overrides)
    return row


def test_repair_review_input_truncates_long_summary() -> None:
    long_summary = "a" * 1200
    repaired = _repair_review_input({"findings": [], "summary": long_summary})
    assert isinstance(repaired, dict)
    assert len(repaired["summary"]) == 800


def test_repair_review_input_removes_dangling_bullet_from_summary() -> None:
    repaired = _repair_review_input(
        {
            "findings": [],
            "summary": "## Overview\n- First point\n-",
        }
    )
    assert isinstance(repaired, dict)
    assert repaired["summary"].endswith("- First point")


def test_repair_review_input_sanitizes_finding_message() -> None:
    repaired = _repair_review_input(
        {
            "summary": "ok",
            "findings": [
                {
                    "message": "Looks risky\n-",
                    "file_path": "a.py",
                    "line_start": 1,
                    "target_line_content": "x=1",
                    "severity": "low",
                    "category": "style",
                    "confidence": 90,
                    "evidence": "diff_visible",
                }
            ],
        }
    )
    assert isinstance(repaired, dict)
    assert repaired["findings"][0]["message"] == "Looks risky"


def test_repair_review_input_coerces_invalid_category_to_schema() -> None:
    repaired = _repair_review_input(
        {
            "summary": "Summary within limits.",
            "findings": [_minimal_finding(category="completeness")],
        }
    )
    ReviewResult.model_validate(repaired)
    assert repaired["findings"][0]["category"] == "maintainability"


def test_repair_review_input_coerces_inference_confidence_and_vendor_high() -> None:
    repaired = _repair_review_input(
        {
            "summary": "Summary within limits.",
            "findings": [
                _minimal_finding(
                    severity="high",
                    evidence="inference",
                    confidence=87,
                    is_vendor_claim=True,
                )
            ],
        }
    )
    ReviewResult.model_validate(repaired)
    f = repaired["findings"][0]
    assert f["confidence"] <= 75
    assert f["severity"] == "medium"


def test_repair_edited_review_payload_coerces_editor_severity_evidence_pairs() -> None:
    raw = {
        "summary": "Summary within limits.",
        "findings": [
            _minimal_finding(
                severity="critical",
                evidence="diff_visible",
                line_start=1,
            ),
            _minimal_finding(
                severity="high",
                evidence="inference",
                line_start=2,
                target_line_content="x",
            ),
        ],
        "decisions": [
            {"original_index": 0, "action": "keep"},
            {"original_index": 1, "action": "keep"},
        ],
    }
    repaired = repair_edited_review_payload(raw)
    edited = EditedReview.model_validate(repaired)
    assert edited.findings[0].severity == "high"
    assert edited.findings[0].evidence == "diff_visible"
    assert edited.findings[1].severity == "medium"
    assert edited.findings[1].evidence == "inference"
    assert edited.findings[1].confidence <= 75


def test_repair_edited_review_payload_demotes_tool_verified_without_calls() -> None:
    raw = {
        "summary": "ok",
        "findings": [
            _minimal_finding(
                severity="critical",
                evidence="tool_verified",
                evidence_tool_calls=[],
                line_start=1,
            )
        ],
        "decisions": [{"original_index": 0, "action": "keep"}],
    }
    repaired = repair_edited_review_payload(raw)
    edited = EditedReview.model_validate(repaired)
    assert edited.findings[0].evidence == "diff_visible"
    assert edited.findings[0].severity == "high"


def test_repair_review_input_coerces_critical_without_tool_for_vendor() -> None:
    repaired = _repair_review_input(
        {
            "summary": "Summary within limits.",
            "findings": [
                _minimal_finding(
                    severity="critical",
                    evidence="diff_visible",
                    is_vendor_claim=True,
                    confidence=95,
                )
            ],
        }
    )
    ReviewResult.model_validate(repaired)
    assert repaired["findings"][0]["severity"] == "medium"


def test_build_schema_feedback_includes_error_locations() -> None:
    try:
        ReviewResult.model_validate({"findings": [], "summary": "b" * 801})
    except ValidationError as exc:
        feedback = _build_schema_feedback(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValidationError was not raised")

    assert "summary" in feedback
    assert "at most 800 characters" in feedback


@pytest.mark.anyio
async def test_finalize_anthropic_recovers_after_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_payload = {
        "summary": "Recovered summary.",
        "findings": [
            _minimal_finding(category="completeness"),
            _minimal_finding(
                severity="high", evidence="inference", confidence=87, is_vendor_claim=True
            ),
            _minimal_finding(
                severity="high", evidence="diff_visible", is_vendor_claim=True, confidence=92
            ),
        ],
    }

    class _FakeAdapter:
        async def structured_output(self, *, request: object) -> StructuredOutputResult:  # noqa: ARG002
            usage = type("Usage", (), {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})()
            return StructuredOutputResult(
                payload=bad_payload, raw_response={"fake": True}, usage=usage
            )

    monkeypatch.setattr(finalize_module, "get_provider_adapter", lambda _provider: _FakeAdapter())

    result = await finalize_module.finalize_review(
        system_prompt="sys",
        messages=[],
        context={},
        model_name="claude-sonnet-4-5",
        provider="anthropic",
        validation_feedback=None,
        allow_retry=False,
    )

    assert isinstance(result, ReviewResult)
    assert len(result.findings) == 3
    assert {finding.category for finding in result.findings} >= {"maintainability", "correctness"}
    assert all(finding.confidence <= 85 for finding in result.findings if finding.is_vendor_claim)
    assert "Recovered summary." in result.summary


@pytest.mark.anyio
async def test_finalize_anthropic_missing_submit_tool_returns_safe_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeAdapter:
        async def structured_output(self, *, request: object) -> StructuredOutputResult:  # noqa: ARG002
            raise RuntimeError("submit_review tool missing")

    monkeypatch.setattr(finalize_module, "get_provider_adapter", lambda _provider: _FakeAdapter())

    result = await finalize_module.finalize_review(
        system_prompt="sys",
        messages=[],
        context={},
        model_name="claude-sonnet-4-5",
        provider="anthropic",
        validation_feedback=None,
        allow_retry=False,
    )

    assert result.findings == []
    assert "safe empty result" in result.summary.lower()


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini"])
async def test_finalize_review_same_payload_all_providers(
    monkeypatch: pytest.MonkeyPatch,
    provider: ModelProvider,
) -> None:
    payload = {"summary": "Looks good.", "findings": [_minimal_finding()]}

    class _FakeAdapter:
        async def structured_output(self, *, request: object) -> StructuredOutputResult:  # noqa: ARG002
            usage = type("Usage", (), {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})()
            return StructuredOutputResult(payload=payload, raw_response={"fake": True}, usage=usage)

    monkeypatch.setattr(finalize_module, "get_provider_adapter", lambda _provider: _FakeAdapter())

    result = await finalize_module.finalize_review(
        system_prompt="sys",
        messages=[],
        context={},
        model_name="model",
        provider=provider,
    )

    assert isinstance(result, ReviewResult)
    assert len(result.findings) == 1
    assert result.summary == "Looks good."
