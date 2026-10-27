import time
from datetime import datetime, timezone

from redis.asyncio import Redis

# Atomic check-and-increment: reads current value, aborts if over limit, otherwise
# increments and refreshes TTL — all in one round-trip so two concurrent reviews
# cannot both pass the budget check at the same time.
_BUDGET_INCR_SCRIPT = """
local key = KEYS[1]
local tokens = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local current = tonumber(redis.call('GET', key) or 0)
if current + tokens > limit then return 0 end
redis.call('INCRBY', key, tokens)
redis.call('EXPIRE', key, ttl)
return 1
"""


async def _check_sliding_window_rate_limit(
    redis: Redis,
    key: str,
    *,
    limit: int,
    window_seconds: int = 3600,
) -> bool:
    now = time.time()
    cutoff = now - window_seconds

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, cutoff)
    pipe.zcard(key)
    pipe.zadd(key, {str(now): now})
    pipe.expire(key, window_seconds)
    _, count, _, _ = await pipe.execute()

    return int(count) < limit


async def check_installation_review_rate_limit(
    redis: Redis,
    installation_id: int,
    *,
    limit: int,
    window_seconds: int = 3600,
) -> bool:
    return await _check_sliding_window_rate_limit(
        redis,
        f"ratelimit:install:{installation_id}",
        limit=limit,
        window_seconds=window_seconds,
    )


async def check_user_review_rate_limit(
    redis: Redis,
    github_id: int,
    *,
    limit: int,
    window_seconds: int = 3600,
) -> bool:
    return await _check_sliding_window_rate_limit(
        redis,
        f"ratelimit:user:{github_id}",
        limit=limit,
        window_seconds=window_seconds,
    )


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
    result = await redis.eval(_BUDGET_INCR_SCRIPT, 1, key, str(tokens), str(daily_limit), "86400")  # type: ignore[misc]
    return bool(result)


async def current_daily_token_usage(redis: Redis, installation_id: int) -> int:
    key = token_budget_key(installation_id)
    return int(await redis.get(key) or 0)
