from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.review_config import ReviewConfig
from app.llm.fallback_chain import (
    LLMQuotaOrRateLimitError,
    build_model_attempt_chain,
    classify_quota_or_rate_limit_error,
    execute_with_fallback,
)
from app.llm.router import ModelResolution
from app.agent.review_chain_graph.graph import compute_branch_flags


def _resolution(provider: str, model: str) -> ModelResolution:
    return ModelResolution(
        role="primary_review",
        provider=provider,
        model=model,
        tier="balanced",
        status="active",
        catalog_version_hash="hash",
    )


def test_classify_quota_or_rate_limit_error_is_conservative() -> None:
    class RateError(Exception):
        status_code = 429

    detected = classify_quota_or_rate_limit_error(RateError("too many requests"))
    assert isinstance(detected, LLMQuotaOrRateLimitError)
    assert classify_quota_or_rate_limit_error(RuntimeError("bad request schema")) is None


def test_build_model_attempt_chain_includes_each_provider_first(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_resolve(
        _config: ReviewConfig,
        _role: str,
        *,
        context_tokens: int = 0,
        previous_provider: str | None = None,
        catalog: object | None = None,
        available_providers: set[str] | None = None,
    ) -> ModelResolution:
        provider = sorted(available_providers or {"anthropic"})[0]
        calls.append((provider, str(context_tokens)))
        return _resolution(provider, f"{provider}-model")

    monkeypatch.setattr("app.llm.fallback_chain.resolve_model_for_role", fake_resolve)
    monkeypatch.setattr("app.llm.fallback_chain.settings", SimpleNamespace(anthropic_api_key="a", openai_api_key="o", gemini_api_key="g"))
    config = ReviewConfig()
    attempts = build_model_attempt_chain(
        review_config=config,
        role="primary_review",
        context_tokens=123,
        user_provider_keys={},
    )
    providers = [attempt.provider for attempt in attempts[:3]]
    assert providers == ["anthropic", "openai", "gemini"]
    assert len(calls) >= 3


@pytest.mark.anyio
async def test_execute_with_fallback_advances_after_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = [_resolution("anthropic", "a"), _resolution("openai", "o")]
    monkeypatch.setattr(
        "app.llm.fallback_chain.build_model_attempt_chain",
        lambda **_kwargs: attempts,
    )

    async def operation(resolution: ModelResolution) -> str:
        if resolution.provider == "anthropic":
            raise RuntimeError("insufficient_quota")
        return "ok"

    result, used = await execute_with_fallback(
        context={},
        review_config=ReviewConfig(),
        role="primary_review",
        context_tokens=0,
        operation=operation,
    )
    assert result == "ok"
    assert used.provider == "openai"


def test_compute_branch_flags_short_circuits_editor_when_no_findings() -> None:
    state = compute_branch_flags(
        findings_after_policy=0,
        max_mode_enabled=True,
        is_light_review=False,
    )
    assert state["should_run_max_mode"] is False
    assert state["should_run_editor"] is False
    assert state["chain_short_circuit"] is True
