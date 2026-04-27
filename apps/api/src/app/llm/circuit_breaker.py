"""Redis-backed circuit breaker for LLM provider failures.

After FAILURE_THRESHOLD consecutive failures the circuit opens for
OPEN_DURATION_SECONDS.  While open, new review jobs are not enqueued;
instead a delay comment is posted on the PR.  The circuit resets on the
first successful review completion.

Keys used in Redis:
  circuit:failures:{provider}  — INCR counter, expires with the circuit window
  circuit:open:{provider}      — sentinel key, present while circuit is open
"""

from __future__ import annotations

import logging

from arq.connections import ArqRedis

logger = logging.getLogger(__name__)

FAILURE_THRESHOLD = 5
OPEN_DURATION_SECONDS = 900  # 15 minutes


async def record_provider_failure(redis: ArqRedis, provider: str) -> bool:
    """Increment the failure counter.  Returns True if the circuit just opened."""
    failures_key = f"circuit:failures:{provider}"
    open_key = f"circuit:open:{provider}"

    count = await redis.incr(failures_key)
    await redis.expire(failures_key, OPEN_DURATION_SECONDS)

    if count >= FAILURE_THRESHOLD:
        was_already_open = await redis.exists(open_key)
        await redis.set(open_key, "1", ex=OPEN_DURATION_SECONDS)
        if not was_already_open:
            logger.warning(
                "Circuit breaker OPENED for provider=%s after %s consecutive failures",
                provider,
                count,
            )
        return True
    return False


async def record_provider_success(redis: ArqRedis, provider: str) -> None:
    """Reset the failure counter and close the circuit."""
    was_open = await redis.exists(f"circuit:open:{provider}")
    await redis.delete(f"circuit:failures:{provider}", f"circuit:open:{provider}")
    if was_open:
        logger.info("Circuit breaker CLOSED for provider=%s — service recovered", provider)


async def is_circuit_open(redis: ArqRedis, provider: str) -> bool:
    """Return True if the circuit is currently open (provider is failing)."""
    return bool(await redis.exists(f"circuit:open:{provider}"))
