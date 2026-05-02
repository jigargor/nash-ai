from decimal import Decimal

from app.agent.review_config import ReviewConfig, ReviewModelConfig
from app.llm.catalog.loader import baseline_catalog_hash, load_baseline_catalog
from app.llm.router import (
    ModelRoleRoutingConfig,
    ModelsRoutingConfig,
    resolve_model_attempt_chain,
    resolve_model_for_role,
)


def test_baseline_catalog_validates_and_hashes() -> None:
    catalog = load_baseline_catalog()

    assert {"anthropic", "openai", "gemini"}.issubset(catalog.provider_ids())
    assert catalog.find_model("anthropic", "claude-sonnet-4-5") is not None
    assert catalog.find_model("gemini", "gemini-2.5-flash-lite") is not None
    assert len(baseline_catalog_hash(catalog)) == 40


def test_router_resolves_default_primary_role_from_available_provider() -> None:
    resolution = resolve_model_for_role(
        ReviewConfig(),
        "primary_review",
        available_providers={"anthropic"},
    )

    assert resolution.provider == "anthropic"
    assert resolution.model == "claude-sonnet-4-6"
    assert resolution.role == "primary_review"
    assert resolution.explicit_pin is False


def test_router_keeps_explicit_legacy_model_pin_when_usable() -> None:
    config = ReviewConfig(
        model=ReviewModelConfig(
            provider="openai",
            name="gpt-5.5",
            input_per_1m_usd=Decimal("3.00"),
            output_per_1m_usd=Decimal("12.00"),
            explicit=True,
        )
    )

    resolution = resolve_model_for_role(config, "primary_review", available_providers={"openai"})

    assert resolution.provider == "openai"
    assert resolution.model == "gpt-5.5"
    assert resolution.explicit_pin is True


def test_router_falls_back_when_explicit_pin_is_retired() -> None:
    catalog = load_baseline_catalog().model_copy(deep=True)
    pinned = catalog.find_model("openai", "gpt-5.5")
    assert pinned is not None
    pinned.status = "retired"

    config = ReviewConfig(
        model=ReviewModelConfig(provider="openai", name="gpt-5.5", explicit=True),
        models=ModelsRoutingConfig(provider_order=["openai"], allow_auto_fallback=True),
    )

    resolution = resolve_model_for_role(
        config,
        "primary_review",
        catalog=catalog,
        available_providers={"openai"},
    )

    assert resolution.provider == "openai"
    assert resolution.model != "gpt-5.5"
    assert resolution.fallback_reason == "explicit_pin_retired"


def test_router_filters_context_window_and_required_capabilities() -> None:
    resolution = resolve_model_for_role(
        ReviewConfig(),
        "primary_review",
        context_tokens=150_000,
        available_providers={"openai", "anthropic"},
    )

    assert resolution.provider == "anthropic"


def test_router_supports_role_tier_config_without_model_pin() -> None:
    config = ReviewConfig(
        models=ModelsRoutingConfig(
            provider_order=["openai", "anthropic"],
            roles={"fast_path": ModelRoleRoutingConfig(tier="economy")},
        )
    )

    resolution = resolve_model_for_role(
        config, "fast_path", available_providers={"openai", "anthropic"}
    )

    assert resolution.provider == "openai"
    assert resolution.model == "gpt-5-mini"
    assert resolution.tier == "economy"


def test_fast_path_prefers_lowest_cost_economy_model() -> None:
    config = ReviewConfig(
        models=ModelsRoutingConfig(
            provider_order=["anthropic", "openai", "gemini"],
            roles={"fast_path": ModelRoleRoutingConfig(tier="economy")},
        )
    )

    resolution = resolve_model_for_role(
        config, "fast_path", available_providers={"openai", "anthropic", "gemini"}
    )

    assert resolution.provider == "gemini"
    assert resolution.model == "gemini-2.5-flash-lite"


def test_resolve_model_attempt_chain_rotates_providers_then_lower_tiers() -> None:
    config = ReviewConfig(
        models=ModelsRoutingConfig(
            provider_order=["openai", "anthropic", "gemini"],
            roles={"primary_review": ModelRoleRoutingConfig(tier="frontier")},
        )
    )
    attempts = resolve_model_attempt_chain(
        config,
        "primary_review",
        available_providers={"openai", "anthropic", "gemini"},
    )

    assert len(attempts) >= 3
    assert attempts[0].provider in {"openai", "anthropic", "gemini"}
    assert len({(item.provider, item.model) for item in attempts}) == len(attempts)
    assert any(item.tier == "economy" for item in attempts)


# ---------------------------------------------------------------------------
# Fallback on deprecated / retired explicit pins
# ---------------------------------------------------------------------------


def test_router_fallback_on_deprecated_model() -> None:
    catalog = load_baseline_catalog().model_copy(deep=True)
    pinned = catalog.find_model("openai", "gpt-5.5")
    assert pinned is not None
    pinned.status = "deprecated"

    config = ReviewConfig(
        model=ReviewModelConfig(provider="openai", name="gpt-5.5", explicit=True),
        models=ModelsRoutingConfig(provider_order=["openai", "anthropic"], allow_auto_fallback=True),
    )

    resolution = resolve_model_for_role(
        config,
        "primary_review",
        catalog=catalog,
        available_providers={"openai", "anthropic"},
    )

    assert resolution.model != "gpt-5.5"
    assert resolution.fallback_reason == "explicit_pin_deprecated"


def test_router_fallback_on_retired_model() -> None:
    catalog = load_baseline_catalog().model_copy(deep=True)
    pinned = catalog.find_model("openai", "gpt-5.5")
    assert pinned is not None
    pinned.status = "retired"

    config = ReviewConfig(
        model=ReviewModelConfig(provider="openai", name="gpt-5.5", explicit=True),
        models=ModelsRoutingConfig(provider_order=["openai", "anthropic"], allow_auto_fallback=True),
    )

    resolution = resolve_model_for_role(
        config,
        "primary_review",
        catalog=catalog,
        available_providers={"openai", "anthropic"},
    )

    assert resolution.model != "gpt-5.5"
    assert resolution.fallback_reason == "explicit_pin_retired"


def test_router_no_fallback_when_auto_fallback_disabled() -> None:
    catalog = load_baseline_catalog().model_copy(deep=True)
    pinned = catalog.find_model("openai", "gpt-5.5")
    assert pinned is not None
    pinned.status = "retired"

    config = ReviewConfig(
        model=ReviewModelConfig(provider="openai", name="gpt-5.5", explicit=True),
        models=ModelsRoutingConfig(allow_auto_fallback=False),
    )

    resolution = resolve_model_for_role(
        config,
        "primary_review",
        catalog=catalog,
        available_providers={"openai", "anthropic"},
    )

    # Forced back to the pin even though retired
    assert resolution.model == "gpt-5.5"


# ---------------------------------------------------------------------------
# Context token limit filtering
# ---------------------------------------------------------------------------


def test_router_respects_context_token_limit() -> None:
    # Baseline catalog caps are finite (<= ~1M). A billion-token context cannot
    # fit any model, so the router returns the configured default as an unknown
    # pin (fallback_reason=no_candidate). When a real candidate is chosen, its
    # advertised cap must be 0 (no enforced limit) or >= requested context.
    huge = 999_999_999
    resolution = resolve_model_for_role(
        ReviewConfig(),
        "primary_review",
        context_tokens=huge,
        available_providers={"anthropic", "openai", "gemini"},
    )

    catalog = load_baseline_catalog()
    record = catalog.find_model(resolution.provider, resolution.model)
    assert record is not None

    if resolution.fallback_reason == "no_candidate":
        assert resolution.status == "unknown"
        assert resolution.explicit_pin is True
        return

    cap = record.capabilities.max_context_tokens
    assert cap == 0 or cap >= huge


# ---------------------------------------------------------------------------
# Fast-path economy ordering by cost
# ---------------------------------------------------------------------------


def test_router_fast_path_cheapest_economy_model() -> None:
    config = ReviewConfig(
        models=ModelsRoutingConfig(
            provider_order=["anthropic", "openai", "gemini"],
            roles={"fast_path": ModelRoleRoutingConfig(tier="economy")},
        )
    )

    resolution = resolve_model_for_role(
        config, "fast_path", available_providers={"anthropic", "openai", "gemini"}
    )

    catalog = load_baseline_catalog()
    record = catalog.find_model(resolution.provider, resolution.model)
    assert record is not None
    assert record.tier == "economy"

    # Verify it is actually the cheapest (or tied-cheapest) economy model available
    economy_models = [
        m for m in catalog.models
        if m.tier == "economy" and m.status not in {"retired", "deprecated"}
        and m.provider in {"anthropic", "openai", "gemini"}
        and m.capabilities.tool_calling and m.capabilities.structured_output
    ]
    if economy_models and record.pricing.input_per_1m is not None:
        min_price = min(
            float(m.pricing.input_per_1m) for m in economy_models
            if m.pricing.input_per_1m is not None
        )
        assert float(record.pricing.input_per_1m) <= min_price + 0.001


# ---------------------------------------------------------------------------
# Provider diversity
# ---------------------------------------------------------------------------


def test_router_provider_diversity_excludes_previous() -> None:
    config = ReviewConfig(
        models=ModelsRoutingConfig(
            provider_order=["anthropic", "openai", "gemini"],
            roles={"primary_review": ModelRoleRoutingConfig(require_provider_diversity=True)},
        )
    )

    resolution = resolve_model_for_role(
        config,
        "primary_review",
        previous_provider="anthropic",
        available_providers={"anthropic", "openai", "gemini"},
    )

    assert resolution.provider != "anthropic"


# ---------------------------------------------------------------------------
# All eight roles resolve to something
# ---------------------------------------------------------------------------

_ALL_ROLES = [
    "fast_path",
    "primary_review",
    "chunk_review",
    "synthesis",
    "editor",
    "challenger",
    "tie_break",
    "config_generator",
]


def test_router_all_eight_roles_resolve() -> None:
    config = ReviewConfig()

    for role in _ALL_ROLES:
        resolution = resolve_model_for_role(
            config,
            role,  # type: ignore[arg-type]
            available_providers={"anthropic", "openai", "gemini"},
        )
        assert resolution.provider in {"anthropic", "openai", "gemini"}
        assert resolution.model
        assert resolution.role == role


# ---------------------------------------------------------------------------
# Attempt chain spans providers
# ---------------------------------------------------------------------------


def test_router_attempt_chain_spans_providers() -> None:
    config = ReviewConfig(
        models=ModelsRoutingConfig(
            provider_order=["openai", "anthropic", "gemini"],
        )
    )

    attempts = resolve_model_attempt_chain(
        config,
        "primary_review",
        available_providers={"openai", "anthropic", "gemini"},
    )

    providers_seen = {a.provider for a in attempts}
    assert len(providers_seen) >= 2


def test_router_attempt_chain_has_no_duplicates() -> None:
    config = ReviewConfig(
        models=ModelsRoutingConfig(
            provider_order=["openai", "anthropic", "gemini"],
        )
    )

    attempts = resolve_model_attempt_chain(
        config,
        "primary_review",
        available_providers={"openai", "anthropic", "gemini"},
    )

    pairs = [(a.provider, a.model) for a in attempts]
    assert len(pairs) == len(set(pairs))


# ---------------------------------------------------------------------------
# BYOK (user provider key override) — routing is not blocked when provider
# is listed in available_providers
# ---------------------------------------------------------------------------


def test_router_byok_provider_available() -> None:
    """Router resolves normally when the BYOK provider is in available_providers."""
    config = ReviewConfig(
        models=ModelsRoutingConfig(provider_order=["openai"])
    )

    resolution = resolve_model_for_role(
        config,
        "primary_review",
        available_providers={"openai"},
    )

    assert resolution.provider == "openai"
    assert resolution.model


# ---------------------------------------------------------------------------
# Resolution carries pricing metadata
# ---------------------------------------------------------------------------


def test_resolution_includes_pricing_metadata() -> None:
    resolution = resolve_model_for_role(
        ReviewConfig(),
        "primary_review",
        available_providers={"anthropic"},
    )

    meta = resolution.as_metadata()
    assert "pricing" in meta
    assert "input_per_1m_usd" in meta["pricing"]
