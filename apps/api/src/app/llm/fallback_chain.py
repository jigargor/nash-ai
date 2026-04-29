from __future__ import annotations

from dataclasses import replace
from typing import Any, Awaitable, Callable, TypeVar, cast

from app.agent.exceptions import ReviewRetryableError
from app.agent.review_config import ReviewConfig
from app.config import settings
from app.llm.router import (
    ROLE_DEFAULT_TIERS,
    ModelRoleRoutingConfig,
    ModelResolution,
    ReviewModelRole,
    resolve_model_for_role,
)
from app.llm.types import ModelTier

T = TypeVar("T")

_TIER_DOWNGRADE_ORDER = ("frontier", "balanced", "economy", "fallback")


class LLMQuotaOrRateLimitError(ReviewRetryableError):
    """Conservative classification for provider quota/rate-limit exhaustion."""


def classify_quota_or_rate_limit_error(exc: Exception) -> LLMQuotaOrRateLimitError | None:
    raw_message = f"{type(exc).__name__}: {exc}".lower()
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return LLMQuotaOrRateLimitError(str(exc))
    if not isinstance(raw_message, str):
        return None
    quota_markers = (
        "insufficient_quota",
        "rate limit",
        "rate_limit",
        "too many requests",
        "resource exhausted",
        "quota exceeded",
        "overloaded",
    )
    if any(marker in raw_message for marker in quota_markers):
        return LLMQuotaOrRateLimitError(str(exc))
    return None


def build_model_attempt_chain(
    *,
    review_config: ReviewConfig,
    role: ReviewModelRole,
    context_tokens: int,
    user_provider_keys: dict[str, str] | None = None,
) -> list[ModelResolution]:
    configured_providers = _configured_provider_ids(user_provider_keys or {})
    provider_order = [
        provider
        for provider in review_config.models.provider_order
        if provider in configured_providers
    ]
    if not provider_order:
        provider_order = sorted(configured_providers)
    if not provider_order:
        return [resolve_model_for_role(review_config, role, context_tokens=context_tokens)]

    attempts: list[ModelResolution] = []
    seen_attempts: set[tuple[str, str]] = set()
    role_config = review_config.models.roles.get(role)
    default_tier = (role_config.tier if role_config is not None and role_config.tier else ROLE_DEFAULT_TIERS[role])
    tier_sequence = _tier_fallback_sequence(default_tier)

    # Round 1: ensure at least one attempt per configured provider.
    for provider in provider_order:
        candidate = resolve_model_for_role(
            review_config,
            role,
            context_tokens=context_tokens,
            available_providers={provider},
        )
        key = (candidate.provider, candidate.model)
        if key not in seen_attempts:
            attempts.append(candidate)
            seen_attempts.add(key)

    # Round 2+: continue downgrading tiers where available.
    for tier in tier_sequence[1:]:
        tier_config = _with_role_tier(review_config, role, tier)
        for provider in provider_order:
            candidate = resolve_model_for_role(
                tier_config,
                role,
                context_tokens=context_tokens,
                available_providers={provider},
            )
            key = (candidate.provider, candidate.model)
            if key not in seen_attempts:
                attempts.append(candidate)
                seen_attempts.add(key)
    return attempts


async def execute_with_fallback(
    *,
    context: dict[str, Any],
    review_config: ReviewConfig,
    role: ReviewModelRole,
    context_tokens: int,
    operation: Callable[[ModelResolution], Awaitable[T]],
) -> tuple[T, ModelResolution]:
    attempts = build_model_attempt_chain(
        review_config=review_config,
        role=role,
        context_tokens=context_tokens,
        user_provider_keys=context.get("user_provider_keys") if isinstance(context, dict) else None,
    )
    last_error: Exception | None = None
    attempt_log: list[dict[str, str]] = []
    for resolution in attempts:
        try:
            result = await operation(resolution)
            attempt_log.append(
                {
                    "provider": resolution.provider,
                    "model": resolution.model,
                    "status": "success",
                }
            )
            _store_attempt_log(context, role, attempt_log)
            return result, resolution
        except Exception as exc:  # pragma: no cover - exercised through callers
            quota = classify_quota_or_rate_limit_error(exc)
            if quota is None:
                raise
            last_error = quota
            attempt_log.append(
                {
                    "provider": resolution.provider,
                    "model": resolution.model,
                    "status": "quota_or_rate_limited",
                }
            )
    _store_attempt_log(context, role, attempt_log)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"No fallback candidates resolved for role={role}")


def _configured_provider_ids(user_provider_keys: dict[str, str]) -> set[str]:
    configured: set[str] = set()
    if settings.anthropic_api_key or user_provider_keys.get("anthropic"):
        configured.add("anthropic")
    if settings.openai_api_key or user_provider_keys.get("openai"):
        configured.add("openai")
    if settings.gemini_api_key or user_provider_keys.get("gemini"):
        configured.add("gemini")
    return configured


def _tier_fallback_sequence(start_tier: str) -> list[str]:
    if start_tier not in _TIER_DOWNGRADE_ORDER:
        return ["balanced", "economy", "fallback"]
    start_idx = _TIER_DOWNGRADE_ORDER.index(start_tier)
    return list(_TIER_DOWNGRADE_ORDER[start_idx:])


def _with_role_tier(review_config: ReviewConfig, role: ReviewModelRole, tier: str) -> ReviewConfig:
    tier_name = cast(ModelTier, tier)
    role_map = dict(review_config.models.roles)
    existing = role_map.get(role)
    if existing is None:
        role_map[role] = ModelRoleRoutingConfig(tier=tier_name)
    else:
        role_map[role] = replace(existing, tier=tier_name)
    return replace(review_config, models=replace(review_config.models, roles=role_map))


def _store_attempt_log(
    context: dict[str, Any],
    role: ReviewModelRole,
    attempts: list[dict[str, str]],
) -> None:
    debug_artifacts = context.setdefault("debug_artifacts", {})
    if not isinstance(debug_artifacts, dict):
        return
    attempt_chains = debug_artifacts.setdefault("model_attempt_chains", {})
    if isinstance(attempt_chains, dict):
        attempt_chains[role] = attempts
