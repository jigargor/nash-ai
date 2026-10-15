"""Per-generation cost attribution from catalog pricing."""

from __future__ import annotations

from decimal import Decimal

from app.llm.catalog.loader import load_baseline_catalog
from app.llm.types import LLMUsage


def estimate_usage_cost_usd(provider: str, model_name: str, usage: LLMUsage) -> float:
    record = load_baseline_catalog().find_model(provider, model_name)
    if record is None:
        return 0.0
    pricing = record.pricing
    total = Decimal("0")
    billed_input = max(usage.input_tokens - usage.cached_input_tokens, 0)
    if pricing.input_per_1m is not None:
        total += (Decimal(billed_input) / Decimal(1_000_000)) * pricing.input_per_1m
    if pricing.cached_input_per_1m is not None and usage.cached_input_tokens:
        total += (
            Decimal(usage.cached_input_tokens) / Decimal(1_000_000)
        ) * pricing.cached_input_per_1m
    if pricing.output_per_1m is not None:
        total += (Decimal(max(usage.output_tokens, 0)) / Decimal(1_000_000)) * pricing.output_per_1m
    return float(total)
