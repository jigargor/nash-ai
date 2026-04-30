from __future__ import annotations

import pytest

from app.llm import circuit_breaker


class _FakeRedis:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._keys: set[str] = set()
        self.expirations: list[tuple[str, int]] = []

    async def incr(self, key: str) -> int:
        current = self._counts.get(key, 0) + 1
        self._counts[key] = current
        return current

    async def expire(self, key: str, ttl_seconds: int) -> bool:
        self.expirations.append((key, ttl_seconds))
        return True

    async def exists(self, key: str) -> int:
        return 1 if key in self._keys else 0

    async def set(self, key: str, _value: str, *, ex: int | None = None) -> bool:
        if ex is not None:
            self.expirations.append((key, ex))
        self._keys.add(key)
        return True

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self._keys:
                self._keys.remove(key)
                deleted += 1
            self._counts.pop(key, None)
        return deleted


@pytest.mark.anyio
async def test_record_provider_failure_opens_at_threshold() -> None:
    redis = _FakeRedis()
    provider = "anthropic"

    for _ in range(circuit_breaker.FAILURE_THRESHOLD - 1):
        assert await circuit_breaker.record_provider_failure(redis, provider) is False
        assert await circuit_breaker.is_circuit_open(redis, provider) is False

    assert await circuit_breaker.record_provider_failure(redis, provider) is True
    assert await circuit_breaker.is_circuit_open(redis, provider) is True
    assert ("circuit:open:anthropic", circuit_breaker.OPEN_DURATION_SECONDS) in redis.expirations


@pytest.mark.anyio
async def test_record_provider_failure_returns_true_when_already_open() -> None:
    redis = _FakeRedis()
    provider = "anthropic"
    for _ in range(circuit_breaker.FAILURE_THRESHOLD - 1):
        await redis.incr(f"circuit:failures:{provider}")
    await redis.set(f"circuit:open:{provider}", "1", ex=circuit_breaker.OPEN_DURATION_SECONDS)

    opened = await circuit_breaker.record_provider_failure(redis, provider)

    assert opened is True
    assert await circuit_breaker.is_circuit_open(redis, provider) is True


@pytest.mark.anyio
async def test_record_provider_success_clears_open_and_failure_keys() -> None:
    redis = _FakeRedis()
    provider = "anthropic"
    await redis.set(f"circuit:open:{provider}", "1", ex=circuit_breaker.OPEN_DURATION_SECONDS)
    await redis.incr(f"circuit:failures:{provider}")

    await circuit_breaker.record_provider_success(redis, provider)

    assert await circuit_breaker.is_circuit_open(redis, provider) is False
    assert f"circuit:failures:{provider}" not in redis._counts


@pytest.mark.anyio
async def test_is_circuit_open_reflects_redis_state() -> None:
    redis = _FakeRedis()
    provider = "openai"
    assert await circuit_breaker.is_circuit_open(redis, provider) is False

    await redis.set(f"circuit:open:{provider}", "1", ex=circuit_breaker.OPEN_DURATION_SECONDS)
    assert await circuit_breaker.is_circuit_open(redis, provider) is True
