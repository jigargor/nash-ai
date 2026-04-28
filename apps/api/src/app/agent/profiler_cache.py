import json
import logging
import asyncio

import redis.exceptions as redis_exc
from redis.asyncio import Redis

from app.agent.profiler import RepoProfile
from app.config import settings

logger = logging.getLogger(__name__)

PROFILE_CACHE_TTL_SECONDS = 3600
_redis_client: Redis | None = None
_redis_lock = asyncio.Lock()


def _cache_key(owner: str, repo: str, ref: str) -> str:
    return f"repo_profile:{owner}:{repo}:{ref}"


async def get_cached_repo_profile(owner: str, repo: str, ref: str) -> RepoProfile | None:
    key = _cache_key(owner, repo, ref)
    redis = await _get_redis_client()
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


async def set_cached_repo_profile(owner: str, repo: str, ref: str, profile: RepoProfile) -> None:
    key = _cache_key(owner, repo, ref)
    redis = await _get_redis_client()
    try:
        payload = json.dumps({"frameworks": profile.frameworks, "conventions": profile.conventions})
        await redis.setex(key, PROFILE_CACHE_TTL_SECONDS, payload)
    except redis_exc.RedisError:
        logger.exception("Failed to write repo profile cache key=%s", key)


async def _get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    async with _redis_lock:
        if _redis_client is None:
            _redis_client = Redis.from_url(
                settings.redis_url, encoding="utf-8", decode_responses=True
            )
    return _redis_client


async def _reset_redis_client_for_tests() -> None:
    global _redis_client
    async with _redis_lock:
        if _redis_client is not None:
            try:
                await _redis_client.aclose()
            except RuntimeError:
                # pytest-anyio may tear down the loop before fixture cleanup on Windows;
                # dropping the singleton is sufficient for test isolation in that case.
                logger.debug("Skipping Redis close after event loop shutdown during test cleanup.")
        _redis_client = None
