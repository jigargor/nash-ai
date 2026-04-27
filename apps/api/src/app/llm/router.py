from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from app.llm.catalog.loader import baseline_catalog_hash, load_baseline_catalog
from app.llm.types import ModelCatalog, ModelProvider, ModelRecord, ModelTier

ReviewModelRole = Literal[
    "fast_path",
    "primary_review",
    "chunk_review",
    "synthesis",
    "editor",
    "challenger",
    "tie_break",
    "config_generator",
]

ROLE_DEFAULT_TIERS: dict[ReviewModelRole, ModelTier] = {
    "fast_path": "economy",
    "primary_review": "balanced",
    "chunk_review": "balanced",
    "synthesis": "balanced",
    "editor": "economy",
    "challenger": "frontier",
    "tie_break": "frontier",
    "config_generator": "economy",
}
TIER_SCORE: dict[ModelTier, int] = {"frontier": 4, "balanced": 3, "economy": 2, "fallback": 1}
STATUS_SCORE = {"active": 40, "legacy": 10, "unknown": 0, "deprecated": -100, "retired": -1000}


@dataclass
class ModelRoleRoutingConfig:
    tier: ModelTier | None = None
    provider: ModelProvider | None = None
    model: str | None = None
    require_provider_diversity: bool = False
    require_tool_calling: bool = True
    require_structured_output: bool = True
    require_prompt_caching: bool = False


@dataclass
class ModelsRoutingConfig:
    policy: ModelTier = "balanced"
    provider_order: list[ModelProvider] = field(
        default_factory=lambda: ["anthropic", "openai", "gemini"]
    )
    roles: dict[str, ModelRoleRoutingConfig] = field(default_factory=dict)
    allow_auto_fallback: bool = True
    allow_default_model_promotion: bool = False


@dataclass(frozen=True)
class ModelResolution:
    role: ReviewModelRole
    provider: ModelProvider
    model: str
    tier: ModelTier
    status: str
    catalog_version_hash: str
    explicit_pin: bool = False
    fallback_reason: str | None = None
    cache_strategy: str = "none"
    input_per_1m_usd: Decimal | None = None
    cached_input_per_1m_usd: Decimal | None = None
    output_per_1m_usd: Decimal | None = None

    def as_metadata(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "tier": self.tier,
            "status": self.status,
            "catalog_version_hash": self.catalog_version_hash,
            "explicit_pin": self.explicit_pin,
            "fallback_reason": self.fallback_reason,
            "cache_strategy": self.cache_strategy,
            "pricing": {
                "input_per_1m_usd": str(self.input_per_1m_usd)
                if self.input_per_1m_usd is not None
                else None,
                "cached_input_per_1m_usd": (
                    str(self.cached_input_per_1m_usd)
                    if self.cached_input_per_1m_usd is not None
                    else None
                ),
                "output_per_1m_usd": str(self.output_per_1m_usd)
                if self.output_per_1m_usd is not None
                else None,
            },
        }


def resolve_model_for_role(
    review_config: object | None,
    role: ReviewModelRole,
    *,
    context_tokens: int = 0,
    previous_provider: str | None = None,
    catalog: ModelCatalog | None = None,
    available_providers: set[str] | None = None,
) -> ModelResolution:
    active_catalog = catalog or load_baseline_catalog()
    routing = _routing_config_from_review_config(review_config)
    role_config = routing.roles.get(role, ModelRoleRoutingConfig(tier=ROLE_DEFAULT_TIERS[role]))
    explicit = _explicit_model_for_role(review_config, role, role_config)
    if explicit is not None:
        provider, model = explicit
        record = active_catalog.find_model(provider, model)
        if record is not None and _model_usable(record, role_config, context_tokens=context_tokens):
            return _resolution_from_record(role, record, explicit_pin=True, catalog=active_catalog)
        # Model not in catalog at all (e.g. newly released, not yet cataloged) — trust the pin.
        if record is None:
            return _resolution_from_unknown_pin(
                role, provider, model, active_catalog, fallback_reason=None
            )
        # Model IS in catalog but not usable (deprecated/retired) — allow_auto_fallback decides.
        if not routing.allow_auto_fallback:
            return _resolution_from_unknown_pin(
                role, provider, model, active_catalog, fallback_reason=None
            )
        fallback = _select_best_candidate(
            active_catalog,
            role=role,
            routing=routing,
            role_config=role_config,
            context_tokens=context_tokens,
            available_providers=available_providers,
            previous_provider=previous_provider,
        )
        if fallback is not None:
            reason = (
                "explicit_pin_unavailable" if record is None else f"explicit_pin_{record.status}"
            )
            return _resolution_from_record(
                role, fallback, explicit_pin=False, catalog=active_catalog, fallback_reason=reason
            )
        return _resolution_from_unknown_pin(
            role, provider, model, active_catalog, fallback_reason="no_catalog_fallback"
        )

    candidate = _select_best_candidate(
        active_catalog,
        role=role,
        routing=routing,
        role_config=role_config,
        context_tokens=context_tokens,
        available_providers=available_providers,
        previous_provider=previous_provider,
    )
    if candidate is not None:
        return _resolution_from_record(role, candidate, explicit_pin=False, catalog=active_catalog)

    default_model = getattr(getattr(review_config, "model", None), "name", "claude-sonnet-4-5")
    default_provider = getattr(getattr(review_config, "model", None), "provider", "anthropic")
    return _resolution_from_unknown_pin(
        role,
        str(default_provider),
        str(default_model),
        active_catalog,
        fallback_reason="no_candidate",
    )


def _routing_config_from_review_config(review_config: object | None) -> ModelsRoutingConfig:
    raw = getattr(review_config, "models", None)
    if isinstance(raw, ModelsRoutingConfig):
        return raw
    return ModelsRoutingConfig()


def _explicit_model_for_role(
    review_config: object | None,
    role: ReviewModelRole,
    role_config: ModelRoleRoutingConfig,
) -> tuple[str, str] | None:
    if role_config.provider and role_config.model:
        return role_config.provider, role_config.model
    if role in {"primary_review", "chunk_review", "synthesis", "editor", "config_generator"}:
        model_config = getattr(review_config, "model", None)
        if bool(getattr(model_config, "explicit", False)):
            return str(getattr(model_config, "provider")), str(getattr(model_config, "name"))
    max_mode = getattr(review_config, "max_mode", None)
    if role == "challenger" and max_mode is not None:
        return str(getattr(max_mode, "challenger_provider")), str(
            getattr(max_mode, "challenger_model")
        )
    if role == "tie_break" and max_mode is not None:
        return str(getattr(max_mode, "tie_break_provider")), str(
            getattr(max_mode, "tie_break_model")
        )
    return None


def _select_best_candidate(
    catalog: ModelCatalog,
    *,
    role: ReviewModelRole,
    routing: ModelsRoutingConfig,
    role_config: ModelRoleRoutingConfig,
    context_tokens: int,
    available_providers: set[str] | None,
    previous_provider: str | None,
) -> ModelRecord | None:
    provider_order = routing.provider_order or ["anthropic", "openai", "gemini"]
    available = (
        available_providers if available_providers is not None else _configured_provider_ids()
    )
    scored: list[tuple[int, int, ModelRecord]] = []
    desired_tier = role_config.tier or ROLE_DEFAULT_TIERS[role]
    active_providers = catalog.active_provider_ids()
    for record in catalog.models:
        if record.provider not in active_providers:
            continue
        if record.provider not in available:
            continue
        if role_config.provider and record.provider != role_config.provider:
            continue
        if (
            role_config.require_provider_diversity
            and previous_provider
            and record.provider == previous_provider
        ):
            continue
        if not _model_usable(record, role_config, context_tokens=context_tokens):
            continue
        score = _score_model(record, desired_tier)
        provider_preference = (
            provider_order.index(record.provider)
            if record.provider in provider_order
            else len(provider_order)
        )
        scored.append((score, -provider_preference, record))
    if not scored:
        return None
    # Provider order is an explicit policy control; when candidates are usable,
    # honor it before tie-breaking on score.
    scored.sort(key=lambda item: (item[1], item[0], item[2].score), reverse=True)
    return scored[0][2]


def _model_usable(
    record: ModelRecord, role_config: ModelRoleRoutingConfig, *, context_tokens: int
) -> bool:
    if record.status in {"retired", "deprecated"}:
        return False
    if role_config.require_tool_calling and not record.capabilities.tool_calling:
        return False
    if role_config.require_structured_output and not record.capabilities.structured_output:
        return False
    if role_config.require_prompt_caching and record.capabilities.prompt_caching == "none":
        return False
    if (
        context_tokens > 0
        and record.capabilities.max_context_tokens > 0
        and context_tokens > record.capabilities.max_context_tokens
    ):
        return False
    if record.shutdown_at and record.shutdown_at <= datetime.now(timezone.utc):
        return False
    return True


def _score_model(record: ModelRecord, desired_tier: ModelTier) -> int:
    tier_distance = abs(TIER_SCORE[record.tier] - TIER_SCORE[desired_tier])
    return record.score + STATUS_SCORE.get(record.status, -50) - (tier_distance * 12)


def _configured_provider_ids() -> set[str]:
    from app.config import settings

    configured: set[str] = set()
    if settings.anthropic_api_key:
        configured.add("anthropic")
    if settings.openai_api_key:
        configured.add("openai")
    if settings.gemini_api_key:
        configured.add("gemini")
    return configured


def _resolution_from_record(
    role: ReviewModelRole,
    record: ModelRecord,
    *,
    explicit_pin: bool,
    catalog: ModelCatalog,
    fallback_reason: str | None = None,
) -> ModelResolution:
    return ModelResolution(
        role=role,
        provider=record.provider,
        model=record.model,
        tier=record.tier,
        status=record.status,
        catalog_version_hash=baseline_catalog_hash(catalog),
        explicit_pin=explicit_pin,
        fallback_reason=fallback_reason,
        cache_strategy=record.capabilities.prompt_caching,
        input_per_1m_usd=record.pricing.input_per_1m,
        cached_input_per_1m_usd=record.pricing.cached_input_per_1m,
        output_per_1m_usd=record.pricing.output_per_1m,
    )


def _resolution_from_unknown_pin(
    role: ReviewModelRole,
    provider: str,
    model: str,
    catalog: ModelCatalog,
    *,
    fallback_reason: str | None,
) -> ModelResolution:
    return ModelResolution(
        role=role,
        provider=provider,
        model=model,
        tier=ROLE_DEFAULT_TIERS[role],
        status="unknown",
        catalog_version_hash=baseline_catalog_hash(catalog),
        explicit_pin=True,
        fallback_reason=fallback_reason,
        cache_strategy="none",
    )
