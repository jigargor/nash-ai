from dataclasses import dataclass, field
from decimal import Decimal

import httpx
import yaml

from app.agent.schema import ContextBudgets

DEFAULT_CONFIDENCE_THRESHOLD = 85
DEFAULT_MODEL_NAME = "claude-sonnet-4-5"
DEFAULT_MODEL_PRICING_USD_PER_1M: dict[str, tuple[Decimal, Decimal]] = {
    "claude-sonnet-4-5": (Decimal("3.00"), Decimal("15.00")),
    "claude-3-7-sonnet-latest": (Decimal("3.00"), Decimal("15.00")),
    "claude-3-5-haiku-latest": (Decimal("0.80"), Decimal("4.00")),
}


@dataclass
class ReviewModelConfig:
    name: str = DEFAULT_MODEL_NAME
    input_per_1m_usd: Decimal = Decimal("3.00")
    output_per_1m_usd: Decimal = Decimal("15.00")


@dataclass
class ContextPackagingConfig:
    layered_context_enabled: bool = True
    partial_review_mode_enabled: bool = True
    summarization_enabled: bool = False
    partial_review_changed_lines_threshold: int = 600
    max_summary_calls_per_review: int = 3
    generated_paths: list[str] = field(default_factory=list)
    vendor_paths: list[str] = field(default_factory=list)


@dataclass
class ReviewConfig:
    confidence_threshold: int = DEFAULT_CONFIDENCE_THRESHOLD
    prompt_additions: str | None = None
    model: ReviewModelConfig = field(default_factory=ReviewModelConfig)
    budgets: ContextBudgets = field(default_factory=ContextBudgets)
    packaging: ContextPackagingConfig = field(default_factory=ContextPackagingConfig)


async def load_review_config(gh, owner: str, repo: str, ref: str) -> ReviewConfig:
    try:
        raw_config = await gh.get_file_content(owner, repo, ".codereview.yml", ref)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return ReviewConfig()
        return ReviewConfig()
    except Exception:
        return ReviewConfig()

    try:
        parsed = yaml.safe_load(raw_config) or {}
    except yaml.YAMLError:
        return ReviewConfig()

    threshold = _normalize_threshold(parsed.get("confidence_threshold"))
    prompt_additions = parsed.get("prompt_additions")
    if prompt_additions is not None:
        prompt_additions = str(prompt_additions).strip() or None
    model_config = _parse_model_config(parsed.get("model"))
    budgets = _parse_budgets(parsed.get("budgets"))
    packaging = _parse_packaging(parsed)
    return ReviewConfig(
        confidence_threshold=threshold,
        prompt_additions=prompt_additions,
        model=model_config,
        budgets=budgets,
        packaging=packaging,
    )


def _normalize_threshold(raw_value: object) -> int:
    if raw_value is None:
        return DEFAULT_CONFIDENCE_THRESHOLD
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_CONFIDENCE_THRESHOLD
    if 0.0 <= value <= 1.0:
        value *= 100
    if value < 0.0 or value > 100.0:
        return DEFAULT_CONFIDENCE_THRESHOLD
    return int(round(value))


def _parse_model_config(raw_value: object) -> ReviewModelConfig:
    if not isinstance(raw_value, dict):
        return _default_model_config()
    raw_name = raw_value.get("name")
    name = str(raw_name).strip() if isinstance(raw_name, str) and raw_name.strip() else DEFAULT_MODEL_NAME
    default_input, default_output = DEFAULT_MODEL_PRICING_USD_PER_1M.get(
        name,
        DEFAULT_MODEL_PRICING_USD_PER_1M[DEFAULT_MODEL_NAME],
    )
    pricing = raw_value.get("pricing")
    if not isinstance(pricing, dict):
        return ReviewModelConfig(name=name, input_per_1m_usd=default_input, output_per_1m_usd=default_output)
    input_per_1m = _normalize_decimal(pricing.get("input_per_1m"), default_input)
    output_per_1m = _normalize_decimal(pricing.get("output_per_1m"), default_output)
    return ReviewModelConfig(name=name, input_per_1m_usd=input_per_1m, output_per_1m_usd=output_per_1m)


def _default_model_config() -> ReviewModelConfig:
    default_input, default_output = DEFAULT_MODEL_PRICING_USD_PER_1M[DEFAULT_MODEL_NAME]
    return ReviewModelConfig(
        name=DEFAULT_MODEL_NAME,
        input_per_1m_usd=default_input,
        output_per_1m_usd=default_output,
    )


def _parse_budgets(raw_value: object) -> ContextBudgets:
    if not isinstance(raw_value, dict):
        return ContextBudgets()
    try:
        return ContextBudgets.model_validate(raw_value)
    except Exception:
        return ContextBudgets()


def _parse_packaging(parsed: dict) -> ContextPackagingConfig:
    return ContextPackagingConfig(
        layered_context_enabled=bool(parsed.get("layered_context_enabled", True)),
        partial_review_mode_enabled=bool(parsed.get("partial_review_mode_enabled", True)),
        summarization_enabled=bool(parsed.get("summarization_enabled", False)),
        partial_review_changed_lines_threshold=_normalize_positive_int(
            parsed.get("partial_review_changed_lines_threshold"),
            600,
        ),
        max_summary_calls_per_review=_normalize_positive_int(parsed.get("max_summary_calls_per_review"), 3),
        generated_paths=_normalize_path_patterns(parsed.get("generated_paths")),
        vendor_paths=_normalize_path_patterns(parsed.get("vendor_paths")),
    )


def _normalize_positive_int(raw_value: object, default: int) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return value


def _normalize_path_patterns(raw_value: object) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    out: list[str] = []
    for item in raw_value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        if normalized:
            out.append(normalized)
    return out


def _normalize_decimal(raw_value: object, default: Decimal) -> Decimal:
    try:
        value = Decimal(str(raw_value))
    except Exception:
        return default
    if value <= 0:
        return default
    return value
