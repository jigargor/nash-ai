from decimal import Decimal

from app.agent.config_cache import _deserialize_config, _serialize_config
from app.agent.review_config import ContextPackagingConfig, ReviewConfig, ReviewModelConfig
from app.agent.schema import ContextBudgets


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
