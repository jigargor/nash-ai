import json
import logging
from dataclasses import asdict
from decimal import Decimal
from typing import cast

import redis.exceptions as redis_exc
from redis.asyncio import Redis

from app.agent.review_config import MaxModeConfig, ModelProvider, ReviewConfig, ReviewModelConfig
from app.config import settings

logger = logging.getLogger(__name__)

CONFIG_CACHE_TTL_SECONDS = 3600


def _cache_key(owner: str, repo: str, head_sha: str) -> str:
    return f"codereview_yml:{owner}:{repo}:{head_sha}"


def _serialize_config(config: ReviewConfig) -> str:
    payload = asdict(config)
    payload["model"]["input_per_1m_usd"] = str(config.model.input_per_1m_usd)
    payload["model"]["output_per_1m_usd"] = str(config.model.output_per_1m_usd)
    return json.dumps(payload)


def _deserialize_config(raw_value: str) -> ReviewConfig:
    data = json.loads(raw_value)
    model_data = dict(data.get("model") or {})
    model_provider = cast(ModelProvider, str(model_data.get("provider", "anthropic")))
    model = ReviewModelConfig(
        provider=model_provider,
        name=str(model_data.get("name", "")),
        input_per_1m_usd=Decimal(str(model_data.get("input_per_1m_usd", "3.00"))),
        output_per_1m_usd=Decimal(str(model_data.get("output_per_1m_usd", "15.00"))),
    )
    max_mode_data = dict(data.get("max_mode") or {})
    challenger_provider = cast(ModelProvider, str(max_mode_data.get("challenger_provider", "openai")))
    tie_break_provider = cast(ModelProvider, str(max_mode_data.get("tie_break_provider", "gemini")))
    max_mode = MaxModeConfig(
        enabled=bool(max_mode_data.get("enabled", False)),
        challenger_provider=challenger_provider,
        challenger_model=str(max_mode_data.get("challenger_model", "gpt-5.5")),
        tie_break_provider=tie_break_provider,
        tie_break_model=str(max_mode_data.get("tie_break_model", "gemini-2.5-pro")),
        conflict_threshold=int(max_mode_data.get("conflict_threshold", 35)),
        high_risk_severity=str(max_mode_data.get("high_risk_severity", "high")),
    )
    data["model"] = model
    data["max_mode"] = max_mode
    return ReviewConfig(**data)


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


async def set_cached_review_config(owner: str, repo: str, head_sha: str, config: ReviewConfig) -> None:
    key = _cache_key(owner, repo, head_sha)
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        await redis.setex(key, CONFIG_CACHE_TTL_SECONDS, _serialize_config(config))
    except redis_exc.RedisError:
        logger.exception("Failed to write review config cache key=%s", key)
    finally:
        await redis.aclose()
