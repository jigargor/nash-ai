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
