from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Mapping, Protocol, cast

import yaml
from pydantic import ValidationError

from app.agent.schema import ContextBudgets
from app.github.utils import safe_fetch_file


class _GitHubFileReader(Protocol):
    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str: ...

DEFAULT_CONFIDENCE_THRESHOLD = 85
ModelProvider = Literal["anthropic", "openai", "gemini"]
DEFAULT_MODEL_PROVIDER: ModelProvider = "anthropic"
DEFAULT_MODEL_NAME = "claude-sonnet-4-5"
DEFAULT_SEVERITY_THRESHOLD = "low"
DEFAULT_MAX_FINDINGS_PER_PR = 50
ALLOWED_SEVERITIES = {"critical", "high", "medium", "low"}
ALLOWED_CATEGORIES = {"security", "performance", "correctness", "style", "maintainability"}
DEFAULT_MODEL_PRICING_USD_PER_1M: dict[tuple[ModelProvider, str], tuple[Decimal, Decimal]] = {
    ("anthropic", "claude-sonnet-4-5"): (Decimal("3.00"), Decimal("15.00")),
    ("anthropic", "claude-3-7-sonnet-latest"): (Decimal("3.00"), Decimal("15.00")),
    ("anthropic", "claude-3-5-haiku-latest"): (Decimal("0.80"), Decimal("4.00")),
    ("openai", "gpt-5.5"): (Decimal("3.00"), Decimal("12.00")),
    ("gemini", "gemini-2.5-pro"): (Decimal("1.25"), Decimal("5.00")),
}
ALLOWED_MODEL_PROVIDERS: set[ModelProvider] = {"anthropic", "openai", "gemini"}


@dataclass
class ReviewModelConfig:
    provider: ModelProvider = DEFAULT_MODEL_PROVIDER
    name: str = DEFAULT_MODEL_NAME
    input_per_1m_usd: Decimal = Decimal("3.00")
    output_per_1m_usd: Decimal = Decimal("15.00")


@dataclass
class MaxModeConfig:
    enabled: bool = False
    challenger_provider: ModelProvider = "openai"
    challenger_model: str = "gpt-5.5"
    tie_break_provider: ModelProvider = "gemini"
    tie_break_model: str = "gemini-2.5-pro"
    conflict_threshold: int = 35
    high_risk_severity: str = "high"


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
    severity_threshold: str = DEFAULT_SEVERITY_THRESHOLD
    categories: list[str] = field(default_factory=list)
    ignore_paths: list[str] = field(default_factory=list)
    review_drafts: bool = False
    max_findings_per_pr: int = DEFAULT_MAX_FINDINGS_PER_PR
    prompt_additions: str | None = None
    model: ReviewModelConfig = field(default_factory=ReviewModelConfig)
    max_mode: MaxModeConfig = field(default_factory=MaxModeConfig)
    budgets: ContextBudgets = field(default_factory=ContextBudgets)
    packaging: ContextPackagingConfig = field(default_factory=ContextPackagingConfig)


async def load_review_config(gh: _GitHubFileReader, owner: str, repo: str, ref: str) -> ReviewConfig:
    raw_config = await safe_fetch_file(gh, owner, repo, ".codereview.yml", ref)
    if raw_config is None:
        return ReviewConfig()

    try:
        parsed_raw = yaml.safe_load(raw_config) or {}
    except yaml.YAMLError:
        return ReviewConfig()

    if not isinstance(parsed_raw, dict):
        return ReviewConfig()
    parsed = cast(dict[str, Any], parsed_raw)

    threshold = _normalize_threshold(parsed.get("confidence_threshold"))
    severity_threshold = _parse_severity_threshold(parsed.get("severity_threshold"))
    categories = _parse_categories(parsed.get("categories"))
    ignore_paths = _normalize_path_patterns(parsed.get("ignore_paths"))
    review_drafts = bool(parsed.get("review_drafts", False))
    max_findings_per_pr = _normalize_positive_int(parsed.get("max_findings_per_pr"), DEFAULT_MAX_FINDINGS_PER_PR)
    prompt_additions = parsed.get("prompt_additions")
    if prompt_additions is not None:
        prompt_additions = str(prompt_additions).strip() or None
    model_config = _parse_model_config(parsed.get("model"))
    max_mode = _parse_max_mode(parsed.get("max_mode"))
    budgets = _parse_budgets(parsed.get("budgets"))
    packaging = _parse_packaging(parsed)
    return ReviewConfig(
        confidence_threshold=threshold,
        severity_threshold=severity_threshold,
        categories=categories,
        ignore_paths=ignore_paths,
        review_drafts=review_drafts,
        max_findings_per_pr=max_findings_per_pr,
        prompt_additions=prompt_additions,
        model=model_config,
        max_mode=max_mode,
        budgets=budgets,
        packaging=packaging,
    )


def _normalize_threshold(raw_value: object) -> int:
    if raw_value is None:
        return DEFAULT_CONFIDENCE_THRESHOLD
    try:
        if isinstance(raw_value, bool):
            return DEFAULT_CONFIDENCE_THRESHOLD
        if isinstance(raw_value, (int, float)):
            value = float(raw_value)
        elif isinstance(raw_value, str):
            value = float(raw_value.strip())
        else:
            return DEFAULT_CONFIDENCE_THRESHOLD
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
    raw_provider = raw_value.get("provider")
    provider = _normalize_provider(raw_provider)
    raw_name = raw_value.get("name")
    fallback_name = _default_model_name_for_provider(provider)
    name = str(raw_name).strip() if isinstance(raw_name, str) and raw_name.strip() else fallback_name
    default_input, default_output = DEFAULT_MODEL_PRICING_USD_PER_1M.get(
        (provider, name),
        DEFAULT_MODEL_PRICING_USD_PER_1M[(DEFAULT_MODEL_PROVIDER, DEFAULT_MODEL_NAME)],
    )
    pricing = raw_value.get("pricing")
    if not isinstance(pricing, dict):
        return ReviewModelConfig(
            provider=provider,
            name=name,
            input_per_1m_usd=default_input,
            output_per_1m_usd=default_output,
        )
    input_per_1m = _normalize_decimal(pricing.get("input_per_1m"), default_input)
    output_per_1m = _normalize_decimal(pricing.get("output_per_1m"), default_output)
    return ReviewModelConfig(
        provider=provider,
        name=name,
        input_per_1m_usd=input_per_1m,
        output_per_1m_usd=output_per_1m,
    )


def _default_model_config() -> ReviewModelConfig:
    default_input, default_output = DEFAULT_MODEL_PRICING_USD_PER_1M[(DEFAULT_MODEL_PROVIDER, DEFAULT_MODEL_NAME)]
    return ReviewModelConfig(
        provider=DEFAULT_MODEL_PROVIDER,
        name=DEFAULT_MODEL_NAME,
        input_per_1m_usd=default_input,
        output_per_1m_usd=default_output,
    )


def _parse_max_mode(raw_value: object) -> MaxModeConfig:
    if not isinstance(raw_value, dict):
        return MaxModeConfig()
    enabled = bool(raw_value.get("enabled", False))
    conflict_threshold = _normalize_percentage(raw_value.get("conflict_threshold"), default=35)
    high_risk_severity = _parse_severity_threshold(raw_value.get("high_risk_severity"))
    challenger = _parse_model_ref(raw_value.get("challenger"), default_provider="openai", default_name="gpt-5.5")
    tie_break = _parse_model_ref(
        raw_value.get("tie_break"),
        default_provider="gemini",
        default_name="gemini-2.5-pro",
    )
    return MaxModeConfig(
        enabled=enabled,
        challenger_provider=challenger[0],
        challenger_model=challenger[1],
        tie_break_provider=tie_break[0],
        tie_break_model=tie_break[1],
        conflict_threshold=conflict_threshold,
        high_risk_severity=high_risk_severity,
    )


def _parse_model_ref(raw_value: object, *, default_provider: ModelProvider, default_name: str) -> tuple[ModelProvider, str]:
    if not isinstance(raw_value, dict):
        return default_provider, default_name
    provider = _normalize_provider(raw_value.get("provider"), default=default_provider)
    raw_name = raw_value.get("name")
    name = str(raw_name).strip() if isinstance(raw_name, str) and raw_name.strip() else default_name
    return provider, name


def _normalize_provider(raw_value: object, *, default: ModelProvider = DEFAULT_MODEL_PROVIDER) -> ModelProvider:
    if not isinstance(raw_value, str):
        return default
    normalized = cast(ModelProvider, raw_value.strip().lower())
    if normalized not in ALLOWED_MODEL_PROVIDERS:
        return default
    return normalized


def _default_model_name_for_provider(provider: ModelProvider) -> str:
    if provider == "openai":
        return "gpt-5.5"
    if provider == "gemini":
        return "gemini-2.5-pro"
    return DEFAULT_MODEL_NAME


def _parse_budgets(raw_value: object) -> ContextBudgets:
    if not isinstance(raw_value, dict):
        return ContextBudgets()
    try:
        return ContextBudgets.model_validate(raw_value)
    except ValidationError:
        return ContextBudgets()


def _parse_packaging(parsed: Mapping[str, Any]) -> ContextPackagingConfig:
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


def _parse_severity_threshold(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        return DEFAULT_SEVERITY_THRESHOLD
    value = raw_value.strip().lower()
    if value not in ALLOWED_SEVERITIES:
        return DEFAULT_SEVERITY_THRESHOLD
    return value


def _parse_categories(raw_value: object) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    out: list[str] = []
    for item in raw_value:
        if not isinstance(item, str):
            continue
        normalized = item.strip().lower()
        if normalized and normalized in ALLOWED_CATEGORIES and normalized not in out:
            out.append(normalized)
    return out


def _normalize_positive_int(raw_value: object, default: int) -> int:
    if isinstance(raw_value, bool):
        return default
    if isinstance(raw_value, int):
        value = raw_value
    elif isinstance(raw_value, float):
        value = int(raw_value)
    elif isinstance(raw_value, str):
        try:
            value = int(raw_value.strip())
        except ValueError:
            return default
    else:
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
    except (InvalidOperation, ValueError):
        return default
    if value <= 0:
        return default
    return value


def _normalize_percentage(raw_value: object, *, default: int) -> int:
    if raw_value is None:
        return default
    try:
        if isinstance(raw_value, bool):
            return default
        if isinstance(raw_value, (int, float)):
            value = float(raw_value)
        elif isinstance(raw_value, str):
            value = float(raw_value.strip())
        else:
            return default
    except (TypeError, ValueError):
        return default
    if 0.0 <= value <= 1.0:
        value *= 100
    if value < 0.0 or value > 100.0:
        return default
    return int(round(value))
