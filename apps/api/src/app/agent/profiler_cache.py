import json
import logging

import redis.exceptions as redis_exc
from redis.asyncio import Redis

from app.agent.profiler import RepoProfile
from app.config import settings

logger = logging.getLogger(__name__)

PROFILE_CACHE_TTL_SECONDS = 3600


def _cache_key(owner: str, repo: str, ref: str) -> str:
    return f"repo_profile:{owner}:{repo}:{ref}"


async def get_cached_repo_profile(owner: str, repo: str, ref: str) -> RepoProfile | None:
    key = _cache_key(owner, repo, ref)
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        cached = await redis.get(key)
        if not cached:
            return None
        data = json.loads(cached)
        return RepoProfile(
            frameworks=list(data.get("frameworks", [])),
            conventions=dict(data.get("conventions", {})),
        )
    except (redis_exc.RedisError, json.JSONDecodeError, ValueError):
        logger.exception("Failed to read repo profile cache key=%s", key)
        return None
    finally:
        await redis.aclose()


async def set_cached_repo_profile(owner: str, repo: str, ref: str, profile: RepoProfile) -> None:
    key = _cache_key(owner, repo, ref)
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        payload = json.dumps({"frameworks": profile.frameworks, "conventions": profile.conventions})
        await redis.setex(key, PROFILE_CACHE_TTL_SECONDS, payload)
    except redis_exc.RedisError:
        logger.exception("Failed to write repo profile cache key=%s", key)
    finally:
        await redis.aclose()
