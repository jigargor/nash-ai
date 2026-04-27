from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent import finalize as finalize_module
from app.agent.finalize import _build_schema_feedback, _repair_review_input
from app.agent.schema import ReviewResult


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
async def test_finalize_anthropic_recovers_after_retry_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    bad_payload = {
        "summary": "Recovered summary.",
        "findings": [
            _minimal_finding(category="completeness"),
            _minimal_finding(severity="high", evidence="inference", confidence=87, is_vendor_claim=True),
            _minimal_finding(severity="high", evidence="diff_visible", is_vendor_claim=True, confidence=92),
        ],
    }

    class _FakeClient:
        class _Messages:
            @staticmethod
            async def create(**_kwargs: object) -> object:
                return SimpleNamespace(
                    usage=SimpleNamespace(),
                    content=[SimpleNamespace(type="tool_use", name="submit_review", input=bad_payload)],
                )

        messages = _Messages()

    class _FakeAdapter:
        @staticmethod
        def render_anthropic_system(system_prompt: str, _options: object) -> str:
            return system_prompt

        @staticmethod
        def parse_usage(_usage: object) -> dict[str, int]:
            return {}

    monkeypatch.setattr(finalize_module, "create_async_anthropic_client", lambda _api_key: _FakeClient())
    monkeypatch.setattr(finalize_module, "get_provider_api_key", lambda _provider: "test-key")
    monkeypatch.setattr(finalize_module, "get_provider_adapter", lambda _provider: _FakeAdapter())
    monkeypatch.setattr(finalize_module, "record_usage", lambda *_args, **_kwargs: None)

    result = await finalize_module._finalize_anthropic(
        system_prompt="sys",
        messages=[],
        context={},
        model_name="claude-sonnet-4-5",
        validation_feedback=None,
        allow_retry=False,
    )

    assert isinstance(result, ReviewResult)
    assert len(result.findings) == 3
    assert {finding.category for finding in result.findings} >= {"maintainability", "correctness"}
    assert all(finding.confidence <= 85 for finding in result.findings if finding.is_vendor_claim)
    assert "Recovered summary." in result.summary


@pytest.mark.anyio
async def test_finalize_anthropic_missing_submit_tool_returns_safe_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        class _Messages:
            @staticmethod
            async def create(**_kwargs: object) -> object:
                return SimpleNamespace(
                    usage=SimpleNamespace(),
                    content=[SimpleNamespace(type="text", text="No tool payload")],
                )

        messages = _Messages()

    class _FakeAdapter:
        @staticmethod
        def render_anthropic_system(system_prompt: str, _options: object) -> str:
            return system_prompt

        @staticmethod
        def parse_usage(_usage: object) -> dict[str, int]:
            return {}

    monkeypatch.setattr(finalize_module, "create_async_anthropic_client", lambda _api_key: _FakeClient())
    monkeypatch.setattr(finalize_module, "get_provider_api_key", lambda _provider: "test-key")
    monkeypatch.setattr(finalize_module, "get_provider_adapter", lambda _provider: _FakeAdapter())
    monkeypatch.setattr(finalize_module, "record_usage", lambda *_args, **_kwargs: None)

    result = await finalize_module._finalize_anthropic(
        system_prompt="sys",
        messages=[],
        context={},
        model_name="claude-sonnet-4-5",
        validation_feedback=None,
        allow_retry=False,
    )

    assert result.findings == []
    assert "safe empty result" in result.summary.lower()
