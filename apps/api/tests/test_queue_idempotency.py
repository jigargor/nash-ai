import pytest

from app.queue.idempotency import (
    REVIEW_SUBMISSION_LOCK_TTL_SECONDS,
    acquire_review_submission_lock,
    release_review_submission_lock,
    review_submission_lock_key,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.calls: list[tuple[str, str, int | None, bool]] = []
        self.deleted: list[str] = []

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        self.calls.append((key, value, ex, nx))
        if nx and key in self.keys:
            return False
        self.keys.add(key)
        return True

    async def delete(self, key: str) -> int:
        self.deleted.append(key)
        if key in self.keys:
            self.keys.remove(key)
            return 1
        return 0


def test_review_submission_lock_key_format() -> None:
    key = review_submission_lock_key(
        installation_id=42, repo_full_name="Acme/Repo", pr_number=7, head_sha="abc123"
    )
    assert key == "review-submit:42:acme/repo:7:abc123"


def test_review_submission_lock_key_includes_repo() -> None:
    first = review_submission_lock_key(42, "acme/one", 7, "abc123")
    second = review_submission_lock_key(42, "acme/two", 7, "abc123")
    assert first != second


@pytest.mark.anyio
async def test_acquire_review_submission_lock_allows_first_then_blocks_duplicate() -> None:
    redis = _FakeRedis()

    first = await acquire_review_submission_lock(
        redis,
        installation_id=42,
        repo_full_name="acme/repo",
        pr_number=7,
        head_sha="a" * 40,
    )
    second = await acquire_review_submission_lock(
        redis,
        installation_id=42,
        repo_full_name="acme/repo",
        pr_number=7,
        head_sha="a" * 40,
    )

    assert first is True
    assert second is False
    assert redis.calls[0][2] == REVIEW_SUBMISSION_LOCK_TTL_SECONDS
    assert redis.calls[0][3] is True


@pytest.mark.anyio
async def test_acquire_review_submission_lock_same_pr_number_in_other_repo_is_independent() -> None:
    redis = _FakeRedis()

    first = await acquire_review_submission_lock(
        redis, installation_id=42, repo_full_name="acme/one", pr_number=7, head_sha="a" * 40
    )
    second = await acquire_review_submission_lock(
        redis, installation_id=42, repo_full_name="acme/two", pr_number=7, head_sha="a" * 40
    )

    assert first is True
    assert second is True


@pytest.mark.anyio
async def test_release_review_submission_lock_allows_reacquire() -> None:
    redis = _FakeRedis()
    kwargs = {
        "installation_id": 42,
        "repo_full_name": "acme/repo",
        "pr_number": 7,
        "head_sha": "a" * 40,
    }

    assert await acquire_review_submission_lock(redis, **kwargs) is True
    assert await acquire_review_submission_lock(redis, **kwargs) is False

    await release_review_submission_lock(redis, **kwargs)

    assert redis.deleted == [review_submission_lock_key(42, "acme/repo", 7, "a" * 40)]
    assert await acquire_review_submission_lock(redis, **kwargs) is True


@pytest.mark.anyio
async def test_release_review_submission_lock_is_noop_when_not_held() -> None:
    redis = _FakeRedis()

    await release_review_submission_lock(
        redis, installation_id=1, repo_full_name="acme/repo", pr_number=1, head_sha="b" * 40
    )

    assert redis.keys == set()
