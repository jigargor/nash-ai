from datetime import datetime, timezone
import time

from redis.asyncio import Redis


async def check_installation_review_rate_limit(
    redis: Redis,
    installation_id: int,
    *,
    limit: int,
    window_seconds: int = 3600,
) -> bool:
    key = f"ratelimit:install:{installation_id}"
    now = time.time()
    cutoff = now - window_seconds

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, cutoff)
    pipe.zcard(key)
    pipe.zadd(key, {str(now): now})
    pipe.expire(key, window_seconds)
    _, count, _, _ = await pipe.execute()

    return int(count) < limit


def token_budget_key(installation_id: int, now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return f"tokens:install:{installation_id}:{current.strftime('%Y-%m-%d')}"


async def check_and_consume_daily_token_budget(
    redis: Redis,
    installation_id: int,
    *,
    tokens: int,
    daily_limit: int,
) -> bool:
    key = token_budget_key(installation_id)
    current = int(await redis.get(key) or 0)
    if current + tokens > daily_limit:
        return False
    await redis.incrby(key, tokens)
    await redis.expire(key, 86400 * 2)
    return True


async def current_daily_token_usage(redis: Redis, installation_id: int) -> int:
    key = token_budget_key(installation_id)
    return int(await redis.get(key) or 0)
