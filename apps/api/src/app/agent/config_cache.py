import json
import logging
from dataclasses import asdict
from decimal import Decimal
from typing import cast

import redis.exceptions as redis_exc
from redis.asyncio import Redis

from app.agent.review_config import AdaptiveThresholdConfig, ChunkingConfig, ContextPackagingConfig
from app.agent.review_config import FastPathConfig, MaxModeConfig, ReviewConfig, ReviewModelConfig
from app.agent.schema import ContextBudgets
from app.config import settings
from app.llm.router import ModelRoleRoutingConfig, ModelsRoutingConfig
from app.llm.types import ModelProvider, ModelTier

logger = logging.getLogger(__name__)

CONFIG_CACHE_TTL_SECONDS = 3600


def _cache_key(owner: str, repo: str, head_sha: str) -> str:
    return f"codereview_yml:{owner}:{repo}:{head_sha}"


def _serialize_config(config: ReviewConfig) -> str:
    payload = asdict(config)
    payload["budgets"] = config.budgets.model_dump(mode="json")
    payload["model"]["input_per_1m_usd"] = str(config.model.input_per_1m_usd)
    payload["model"]["output_per_1m_usd"] = str(config.model.output_per_1m_usd)
    payload["model"]["cached_input_per_1m_usd"] = (
        str(config.model.cached_input_per_1m_usd)
        if config.model.cached_input_per_1m_usd is not None
        else None
    )
    return json.dumps(payload)


def _deserialize_config(raw_value: str) -> ReviewConfig:
    data = json.loads(raw_value)
    model_data = dict(data.get("model") or {})
    model_provider = _provider_value(model_data.get("provider"), "anthropic")
    model = ReviewModelConfig(
        provider=model_provider,
        name=str(model_data.get("name", "")),
        input_per_1m_usd=Decimal(str(model_data.get("input_per_1m_usd", "3.00"))),
        output_per_1m_usd=Decimal(str(model_data.get("output_per_1m_usd", "15.00"))),
        cached_input_per_1m_usd=(
            Decimal(str(model_data["cached_input_per_1m_usd"]))
            if model_data.get("cached_input_per_1m_usd") is not None
            else None
        ),
        explicit=bool(model_data.get("explicit", False)),
    )
    max_mode_data = dict(data.get("max_mode") or {})
    challenger_provider = _provider_value(max_mode_data.get("challenger_provider"), "openai")
    tie_break_provider = _provider_value(max_mode_data.get("tie_break_provider"), "gemini")
    max_mode = MaxModeConfig(
        enabled=bool(max_mode_data.get("enabled", False)),
        challenger_provider=challenger_provider,
        challenger_model=str(max_mode_data.get("challenger_model", "gpt-5.5")),
        tie_break_provider=tie_break_provider,
        tie_break_model=str(max_mode_data.get("tie_break_model", "gemini-2.5-pro")),
        conflict_threshold=int(max_mode_data.get("conflict_threshold", 35)),
        high_risk_severity=str(max_mode_data.get("high_risk_severity", "high")),
    )
    budgets_data = dict(data.get("budgets") or {})
    budgets = ContextBudgets.model_validate(budgets_data)
    packaging_data = dict(data.get("packaging") or {})
    packaging = ContextPackagingConfig(
        layered_context_enabled=bool(packaging_data.get("layered_context_enabled", True)),
        partial_review_mode_enabled=bool(packaging_data.get("partial_review_mode_enabled", True)),
        summarization_enabled=bool(packaging_data.get("summarization_enabled", False)),
        partial_review_changed_lines_threshold=int(
            packaging_data.get("partial_review_changed_lines_threshold", 600)
        ),
        max_summary_calls_per_review=int(packaging_data.get("max_summary_calls_per_review", 3)),
        generated_paths=[str(item) for item in list(packaging_data.get("generated_paths") or [])],
        vendor_paths=[str(item) for item in list(packaging_data.get("vendor_paths") or [])],
    )
    chunking_data = dict(data.get("chunking") or {})
    chunking = ChunkingConfig(
        enabled=bool(chunking_data.get("enabled", True)),
        proactive_threshold_tokens=int(chunking_data.get("proactive_threshold_tokens", 35_000)),
        target_chunk_tokens=int(chunking_data.get("target_chunk_tokens", 18_000)),
        max_chunks=int(chunking_data.get("max_chunks", 8)),
        min_files_per_chunk=int(chunking_data.get("min_files_per_chunk", 1)),
        include_file_classes=[
            str(item) for item in list(chunking_data.get("include_file_classes") or [])
        ]
        or ["reviewable", "config_only", "test_only"],
        max_total_prompt_tokens=int(chunking_data.get("max_total_prompt_tokens", 120_000)),
        max_latency_seconds=int(chunking_data.get("max_latency_seconds", 240)),
        output_headroom_tokens=int(chunking_data.get("output_headroom_tokens", 4096)),
    )
    fast_path_data = dict(data.get("fast_path") or {})
    fast_path = FastPathConfig(
        enabled=bool(fast_path_data.get("enabled", True)),
        skip_min_confidence=int(fast_path_data.get("skip_min_confidence", 90)),
        light_review_min_confidence=int(fast_path_data.get("light_review_min_confidence", 80)),
        force_economy_on_light_review=bool(
            fast_path_data.get("force_economy_on_light_review", False)
        ),
        max_diff_excerpt_tokens=int(fast_path_data.get("max_diff_excerpt_tokens", 3000)),
        allow_skip=bool(fast_path_data.get("allow_skip", True)),
        confidence_bug_check=bool(fast_path_data.get("confidence_bug_check", True)),
        zero_confidence_limit=int(fast_path_data.get("zero_confidence_limit", 5)),
        post_classification_context_comment=bool(
            fast_path_data.get("post_classification_context_comment", False)
        ),
    )
    adaptive_threshold_data = dict(data.get("adaptive_threshold") or {})
    adaptive_threshold = AdaptiveThresholdConfig(
        enabled=bool(adaptive_threshold_data.get("enabled", True)),
        initial_threshold=int(adaptive_threshold_data.get("initial_threshold", 90)),
        minimum_threshold=int(adaptive_threshold_data.get("minimum_threshold", 60)),
        step_down=int(adaptive_threshold_data.get("step_down", 2)),
        target_disagreement_low=int(adaptive_threshold_data.get("target_disagreement_low", 5)),
        target_disagreement_high=int(adaptive_threshold_data.get("target_disagreement_high", 15)),
        max_false_accept_rate=int(adaptive_threshold_data.get("max_false_accept_rate", 5)),
        max_dismiss_rate=int(adaptive_threshold_data.get("max_dismiss_rate", 25)),
        min_samples=int(adaptive_threshold_data.get("min_samples", 100)),
    )
    models_data = dict(data.get("models") or {})
    roles: dict[str, ModelRoleRoutingConfig] = {}
    roles_data = dict(models_data.get("roles") or {})
    for role_name, role_data_raw in roles_data.items():
        role_data = dict(role_data_raw or {})
        roles[str(role_name)] = ModelRoleRoutingConfig(
            tier=role_data.get("tier"),
            provider=role_data.get("provider"),
            model=role_data.get("model"),
            require_provider_diversity=bool(role_data.get("require_provider_diversity", False)),
            require_tool_calling=bool(role_data.get("require_tool_calling", True)),
            require_structured_output=bool(role_data.get("require_structured_output", True)),
            require_prompt_caching=bool(role_data.get("require_prompt_caching", False)),
        )
    models = ModelsRoutingConfig(
        policy=cast(ModelTier, str(models_data.get("policy", "balanced"))),
        provider_order=[
            str(item)
            for item in list(models_data.get("provider_order") or ["anthropic", "openai", "gemini"])
        ],
        roles=roles,
        allow_auto_fallback=bool(models_data.get("allow_auto_fallback", True)),
        allow_default_model_promotion=bool(models_data.get("allow_default_model_promotion", False)),
    )
    data["model"] = model
    data["max_mode"] = max_mode
    data["budgets"] = budgets
    data["packaging"] = packaging
    data["chunking"] = chunking
    data["models"] = models
    data["fast_path"] = fast_path
    data["adaptive_threshold"] = adaptive_threshold
    return ReviewConfig(**data)


def _provider_value(raw_value: object, default: ModelProvider) -> ModelProvider:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return default
    return raw_value.strip()


async def get_cached_review_config(owner: str, repo: str, head_sha: str) -> ReviewConfig | None:
    key = _cache_key(owner, repo, head_sha)
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        cached = await redis.get(key)
        if not cached:
            return None
        return _deserialize_config(cached)
    except (redis_exc.RedisError, json.JSONDecodeError, ValueError):
        logger.exception("Failed to read review config cache key=%s", key)
        return None
    finally:
        await redis.aclose()


async def set_cached_review_config(
    owner: str, repo: str, head_sha: str, config: ReviewConfig
) -> None:
    key = _cache_key(owner, repo, head_sha)
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        await redis.setex(key, CONFIG_CACHE_TTL_SECONDS, _serialize_config(config))
    except redis_exc.RedisError:
        logger.exception("Failed to write review config cache key=%s", key)
    finally:
        await redis.aclose()
