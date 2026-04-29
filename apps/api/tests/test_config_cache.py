from decimal import Decimal

from app.agent.config_cache import _deserialize_config, _serialize_config
from app.agent.review_config import (
    ContextPackagingConfig,
    FastPathConfig,
    ReviewConfig,
    ReviewModelConfig,
)
from app.agent.schema import ContextBudgets
from app.llm.router import ModelRoleRoutingConfig, ModelsRoutingConfig


def test_serialize_config_handles_context_budgets() -> None:
    config = ReviewConfig(
        model=ReviewModelConfig(
            provider="anthropic",
            name="claude-sonnet-4-5",
            input_per_1m_usd=Decimal("3.00"),
            output_per_1m_usd=Decimal("15.00"),
        ),
        budgets=ContextBudgets(system_prompt=1234, total_cap=4567),
    )

    serialized = _serialize_config(config)

    assert '"system_prompt": 1234' in serialized
    assert '"total_cap": 4567' in serialized


def test_deserialize_config_restores_budgets_and_packaging_types() -> None:
    config = ReviewConfig(
        budgets=ContextBudgets(diff_hunks=2222),
        packaging=ContextPackagingConfig(
            layered_context_enabled=False,
            partial_review_mode_enabled=False,
            generated_paths=["dist/**"],
        ),
    )

    rehydrated = _deserialize_config(_serialize_config(config))

    assert isinstance(rehydrated.budgets, ContextBudgets)
    assert rehydrated.budgets.diff_hunks == 2222
    assert isinstance(rehydrated.packaging, ContextPackagingConfig)
    assert rehydrated.packaging.generated_paths == ["dist/**"]


def test_deserialize_config_restores_model_routing_types() -> None:
    config = ReviewConfig(
        models=ModelsRoutingConfig(
            provider_order=["openai", "anthropic"],
            roles={"fast_path": ModelRoleRoutingConfig(tier="economy")},
        )
    )

    rehydrated = _deserialize_config(_serialize_config(config))

    assert isinstance(rehydrated.models, ModelsRoutingConfig)
    assert rehydrated.models.provider_order == ["openai", "anthropic"]
    assert rehydrated.models.roles["fast_path"].tier == "economy"


def test_deserialize_config_restores_fast_path_types() -> None:
    config = ReviewConfig(
        fast_path=FastPathConfig(
            enabled=False,
            skip_min_confidence=96,
            light_review_min_confidence=84,
            max_diff_excerpt_tokens=1500,
            allow_skip=False,
            confidence_bug_check=False,
            zero_confidence_limit=9,
            post_classification_context_comment=True,
        )
    )

    rehydrated = _deserialize_config(_serialize_config(config))

    assert isinstance(rehydrated.fast_path, FastPathConfig)
    assert rehydrated.fast_path.enabled is False
    assert rehydrated.fast_path.skip_min_confidence == 96
    assert rehydrated.fast_path.light_review_min_confidence == 84
    assert rehydrated.fast_path.max_diff_excerpt_tokens == 1500
    assert rehydrated.fast_path.allow_skip is False
    assert rehydrated.fast_path.confidence_bug_check is False
    assert rehydrated.fast_path.zero_confidence_limit == 9
    assert rehydrated.fast_path.post_classification_context_comment is True
