from __future__ import annotations

import json

import pytest
import redis.exceptions as redis_exc

from app.agent.profiler import RepoProfile
from app.agent import profiler_cache


class _FakeRedis:
    def __init__(
        self,
        *,
        get_value: str | None = None,
        raise_on_get: bool = False,
        raise_on_set: bool = False,
    ) -> None:
        self.get_value = get_value
        self.raise_on_get = raise_on_get
        self.raise_on_set = raise_on_set
        self.closed = False
        self.set_calls: list[tuple[str, int, str]] = []

    async def get(self, _key: str) -> str | None:
        if self.raise_on_get:
            raise redis_exc.ConnectionError("cache unavailable")
        return self.get_value

    async def setex(self, key: str, ttl: int, payload: str) -> None:
        if self.raise_on_set:
            raise redis_exc.ConnectionError("cache unavailable")
        self.set_calls.append((key, ttl, payload))

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
async def _reset_profiler_cache_singleton() -> None:
    await profiler_cache._reset_redis_client_for_tests()
    yield
    await profiler_cache._reset_redis_client_for_tests()


@pytest.mark.anyio
async def test_get_cached_repo_profile_returns_deserialized_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps({"frameworks": ["nextjs"], "conventions": {"lint": "ruff"}})
    fake_redis = _FakeRedis(get_value=payload)
    from_url_calls = 0

    def _fake_from_url(*_args: object, **_kwargs: object) -> _FakeRedis:
        nonlocal from_url_calls
        from_url_calls += 1
        return fake_redis

    monkeypatch.setattr(profiler_cache.Redis, "from_url", _fake_from_url)

    profile = await profiler_cache.get_cached_repo_profile("acme", "repo", "main")
    assert profile == RepoProfile(frameworks=["nextjs"], conventions={"lint": "ruff"})
    profile_second = await profiler_cache.get_cached_repo_profile("acme", "repo", "main")
    assert profile_second == RepoProfile(frameworks=["nextjs"], conventions={"lint": "ruff"})
    assert from_url_calls == 1


@pytest.mark.anyio
async def test_get_cached_repo_profile_returns_none_on_invalid_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis(get_value="{invalid-json")
    monkeypatch.setattr(profiler_cache.Redis, "from_url", lambda *args, **kwargs: fake_redis)

    profile = await profiler_cache.get_cached_repo_profile("acme", "repo", "main")
    assert profile is None


@pytest.mark.anyio
async def test_set_cached_repo_profile_writes_payload_and_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(profiler_cache.Redis, "from_url", lambda *args, **kwargs: fake_redis)

    profile = RepoProfile(frameworks=["fastapi"], conventions={"style": "strict"})
    await profiler_cache.set_cached_repo_profile("acme", "repo", "main", profile)

    assert len(fake_redis.set_calls) == 1
    key, ttl, payload = fake_redis.set_calls[0]
    assert key == "repo_profile:acme:repo:main"
    assert ttl == profiler_cache.PROFILE_CACHE_TTL_SECONDS
    assert json.loads(payload)["frameworks"] == ["fastapi"]


@pytest.mark.anyio
async def test_set_cached_repo_profile_swallow_redis_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis(raise_on_set=True)
    monkeypatch.setattr(profiler_cache.Redis, "from_url", lambda *args, **kwargs: fake_redis)

    profile = RepoProfile(frameworks=["fastapi"], conventions={})
    await profiler_cache.set_cached_repo_profile("acme", "repo", "main", profile)
