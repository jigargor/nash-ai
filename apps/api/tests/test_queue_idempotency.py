import pytest

from app.queue.idempotency import (
    REVIEW_SUBMISSION_LOCK_TTL_SECONDS,
    acquire_review_submission_lock,
    review_submission_lock_key,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.calls: list[tuple[str, str, int | None, bool]] = []

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


def test_review_submission_lock_key_format() -> None:
    key = review_submission_lock_key(installation_id=42, pr_number=7, head_sha="abc123")
    assert key == "review-submit:42:7:abc123"


@pytest.mark.anyio
async def test_acquire_review_submission_lock_allows_first_then_blocks_duplicate() -> None:
    redis = _FakeRedis()

    first = await acquire_review_submission_lock(
        redis,
        installation_id=42,
        pr_number=7,
        head_sha="a" * 40,
    )
    second = await acquire_review_submission_lock(
        redis,
        installation_id=42,
        pr_number=7,
        head_sha="a" * 40,
    )

    assert first is True
    assert second is False
    assert redis.calls[0][2] == REVIEW_SUBMISSION_LOCK_TTL_SECONDS
    assert redis.calls[0][3] is True
