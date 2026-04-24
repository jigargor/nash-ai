import json
import logging
from dataclasses import asdict
from decimal import Decimal

from redis.asyncio import Redis

from app.agent.review_config import ReviewConfig, ReviewModelConfig
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
    model = ReviewModelConfig(
        name=str(model_data.get("name", "")),
        input_per_1m_usd=Decimal(str(model_data.get("input_per_1m_usd", "3.00"))),
        output_per_1m_usd=Decimal(str(model_data.get("output_per_1m_usd", "15.00"))),
    )
    data["model"] = model
    return ReviewConfig(**data)


async def get_cached_review_config(owner: str, repo: str, head_sha: str) -> ReviewConfig | None:
    key = _cache_key(owner, repo, head_sha)
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        cached = await redis.get(key)
        if not cached:
            return None
        return _deserialize_config(cached)
    except Exception:
        logger.exception("Failed to read review config cache key=%s", key)
        return None
    finally:
        await redis.aclose()


async def set_cached_review_config(owner: str, repo: str, head_sha: str, config: ReviewConfig) -> None:
    key = _cache_key(owner, repo, head_sha)
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        await redis.setex(key, CONFIG_CACHE_TTL_SECONDS, _serialize_config(config))
    except Exception:
        logger.exception("Failed to write review config cache key=%s", key)
    finally:
        await redis.aclose()
