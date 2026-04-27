import pytest

from app.ratelimit import (
    check_and_consume_daily_token_budget,
    check_installation_review_rate_limit,
    token_budget_key,
)


class _FakePipeline:
    def __init__(self, redis: "_FakeRedis") -> None:
        self.redis = redis

    def zremrangebyscore(self, key: str, _start: float, cutoff: float) -> "_FakePipeline":
        self.redis.sorted_values[key] = [
            value for value in self.redis.sorted_values.get(key, []) if value > cutoff
        ]
        return self

    def zcard(self, key: str) -> "_FakePipeline":
        self.redis.last_count = len(self.redis.sorted_values.get(key, []))
        return self

    def zadd(self, key: str, mapping: dict[str, float]) -> "_FakePipeline":
        self.redis.sorted_values.setdefault(key, []).extend(mapping.values())
        return self

    def expire(self, _key: str, _ttl: int) -> "_FakePipeline":
        return self

    async def execute(self) -> tuple[int, int, int, int]:
        return 0, self.redis.last_count, 0, 0


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.sorted_values: dict[str, list[float]] = {}
        self.last_count = 0

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)

    async def get(self, key: str) -> int:
        return self.values.get(key, 0)

    async def incrby(self, key: str, value: int) -> None:
        self.values[key] = int(self.values.get(key, 0)) + value

    async def expire(self, _key: str, _ttl: int) -> None:
        return None

    async def eval(
        self, _script: str, _numkeys: int, key: str, tokens: str, limit: str, _ttl: str
    ) -> int:
        """Simulate the budget Lua script: atomic check-and-increment."""
        current = int(self.values.get(key, 0))
        if current + int(tokens) > int(limit):
            return 0
        self.values[key] = current + int(tokens)
        return 1


def test_token_budget_key_uses_utc_date() -> None:
    key = token_budget_key(42)
    assert key.startswith("tokens:install:42:")


@pytest.mark.anyio
async def test_check_and_consume_daily_token_budget() -> None:
    redis = _FakeRedis()
    ok = await check_and_consume_daily_token_budget(redis, 1, tokens=100, daily_limit=500)
    assert ok is True
    blocked = await check_and_consume_daily_token_budget(redis, 1, tokens=500, daily_limit=500)
    assert blocked is False


@pytest.mark.anyio
async def test_check_installation_review_rate_limit() -> None:
    redis = _FakeRedis()
    assert await check_installation_review_rate_limit(redis, 10, limit=2) is True
    assert await check_installation_review_rate_limit(redis, 10, limit=2) is True
    assert await check_installation_review_rate_limit(redis, 10, limit=2) is False
