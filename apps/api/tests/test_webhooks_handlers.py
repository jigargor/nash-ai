from random import randint

import pytest
from sqlalchemy import func, select
from uuid import uuid4

from app.db.models import Installation, Review
from app.db.session import AsyncSessionLocal, engine, set_installation_context
from app.webhooks.handlers import (
    _primary_provider_for_circuit_breaker,
    queue_pull_request_review,
    sync_installation_from_webhook,
)
from app.webhooks.schemas import GitHubInstallationWebhookPayload, GitHubPullRequestWebhookPayload


class _FakeJob:
    def __init__(self, job_id: str):
        self.job_id = job_id


class _FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.locks: set[str] = set()

    async def exists(self, *keys: object) -> int:
        """Redis EXISTS shim: no keys stored in this fake, so circuit is never open."""
        return 0

    async def enqueue_job(self, *args: object) -> _FakeJob:
        self.calls.append(args)
        return _FakeJob(job_id=f"job-{len(self.calls)}")

    async def set(
        self,
        key: str,
        _value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        _ = ex
        if nx and key in self.locks:
            return False
        self.locks.add(key)
        return True


def _payload(
    action: str = "opened",
    *,
    title: str | None = None,
    body: str | None = None,
) -> GitHubPullRequestWebhookPayload:
    head_sha = (uuid4().hex + uuid4().hex)[:40]
    pull_request: dict[str, object] = {"number": 99, "head": {"sha": head_sha}}
    if title is not None:
        pull_request["title"] = title
    if body is not None:
        pull_request["body"] = body
    return GitHubPullRequestWebhookPayload.model_validate(
        {
            "action": action,
            "installation": {"id": 555},
            "repository": {
                "full_name": "acme/repo",
                "owner": {"login": "acme", "type": "Organization"},
            },
            "pull_request": pull_request,
        }
    )


def _installation_payload(installation_id: int, action: str) -> GitHubInstallationWebhookPayload:
    return GitHubInstallationWebhookPayload.model_validate(
        {
            "action": action,
            "installation": {
                "id": installation_id,
                "account": {"login": f"acme-{installation_id}", "type": "Organization"},
            },
        }
    )


@pytest.fixture(autouse=True)
async def _dispose_global_engine_after_test() -> None:
    """Each AnyIO test can use a fresh asyncio loop; dispose the pool so later tests do not reuse dead connections."""
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def _enable_review_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.webhooks.handlers.settings.enable_reviews", True)
    monkeypatch.setattr("app.webhooks.handlers.settings.openai_api_key", "test-key")


@pytest.mark.anyio
async def test_sync_installation_from_webhook_tracks_uninstall_and_reinstall() -> None:
    installation_id = randint(100_000_000, 999_999_999)

    try:
        await sync_installation_from_webhook(_installation_payload(installation_id, "created"))
        async with AsyncSessionLocal() as session:
            await set_installation_context(session, installation_id)
            installation = await session.scalar(
                select(Installation).where(Installation.installation_id == installation_id)
            )
            assert installation is not None
            assert installation.suspended_at is None

        await sync_installation_from_webhook(_installation_payload(installation_id, "deleted"))
        async with AsyncSessionLocal() as session:
            await set_installation_context(session, installation_id)
            installation = await session.scalar(
                select(Installation).where(Installation.installation_id == installation_id)
            )
            assert installation is not None
            assert installation.suspended_at is not None

        await sync_installation_from_webhook(_installation_payload(installation_id, "created"))
        async with AsyncSessionLocal() as session:
            await set_installation_context(session, installation_id)
            installation = await session.scalar(
                select(Installation).where(Installation.installation_id == installation_id)
            )
            assert installation is not None
            assert installation.suspended_at is None
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_queue_pull_request_review_skips_duplicate_active_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    payload = _payload()

    async def _allow(*_args, **_kwargs) -> bool:
        return True

    async def _daily_usage(*_args, **_kwargs) -> int:
        return 0

    monkeypatch.setattr("app.webhooks.handlers.check_installation_review_rate_limit", _allow)
    monkeypatch.setattr("app.webhooks.handlers.current_daily_token_usage", _daily_usage)

    await queue_pull_request_review(redis, payload)
    await queue_pull_request_review(redis, payload)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, payload.installation.id)
        total_reviews = await session.scalar(
            select(func.count(Review.id))
            .where(Review.installation_id == payload.installation.id)
            .where(Review.pr_number == payload.pull_request.number)
            .where(Review.pr_head_sha == payload.pull_request.head.sha)
        )

    assert total_reviews == 1
    assert len(redis.calls) == 1
    assert redis.calls[0][0] == "review_pr"


@pytest.mark.anyio
async def test_queue_pull_request_review_requeues_failed_review_for_same_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    payload = _payload()

    async def _allow(*_args, **_kwargs) -> bool:
        return True

    async def _daily_usage(*_args, **_kwargs) -> int:
        return 0

    monkeypatch.setattr("app.webhooks.handlers.check_installation_review_rate_limit", _allow)
    monkeypatch.setattr("app.webhooks.handlers.current_daily_token_usage", _daily_usage)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, payload.installation.id)
        installation = await session.scalar(
            select(Installation).where(Installation.installation_id == payload.installation.id)
        )
        if installation is None:
            session.add(
                Installation(
                    installation_id=payload.installation.id,
                    account_login="acme",
                    account_type="Organization",
                )
            )
        existing_review = Review(
            installation_id=payload.installation.id,
            repo_full_name=payload.repository.full_name,
            pr_number=payload.pull_request.number,
            pr_head_sha=payload.pull_request.head.sha,
            status="failed",
            model_provider="anthropic",
            model="claude-sonnet-4-5",
        )
        session.add(existing_review)
        await session.flush()
        existing_review_id = int(existing_review.id)
        await session.commit()

    await queue_pull_request_review(redis, payload)

    assert len(redis.calls) == 1
    assert redis.calls[0][0] == "review_pr"
    assert int(redis.calls[0][1]) == existing_review_id

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, payload.installation.id)
        persisted_review = await session.get(Review, existing_review_id)
        assert persisted_review is not None
        assert persisted_review.status == "queued"


@pytest.mark.anyio
async def test_queue_pull_request_review_skips_when_submission_lock_already_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    payload = _payload()

    async def _allow(*_args, **_kwargs) -> bool:
        return True

    async def _daily_usage(*_args, **_kwargs) -> int:
        return 0

    monkeypatch.setattr("app.webhooks.handlers.check_installation_review_rate_limit", _allow)
    monkeypatch.setattr("app.webhooks.handlers.current_daily_token_usage", _daily_usage)

    await queue_pull_request_review(redis, payload)
    await queue_pull_request_review(redis, payload)
    assert len(redis.calls) == 1


@pytest.mark.anyio
async def test_queue_pull_request_review_skips_when_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    payload = _payload()

    async def _deny(*_args, **_kwargs) -> bool:
        return False

    async def _daily_usage(*_args, **_kwargs) -> int:
        return 0

    monkeypatch.setattr("app.webhooks.handlers.check_installation_review_rate_limit", _deny)
    monkeypatch.setattr("app.webhooks.handlers.current_daily_token_usage", _daily_usage)

    await queue_pull_request_review(redis, payload)
    assert not redis.calls


@pytest.mark.anyio
async def test_queue_pull_request_review_enqueues_when_skip_tag_in_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    payload = _payload(title="chore: deps [skip-nash-review]")

    async def _allow(*_args: object, **_kwargs: object) -> bool:
        return True

    async def _daily_usage(*_args: object, **_kwargs: object) -> int:
        return 0

    monkeypatch.setattr("app.webhooks.handlers.check_installation_review_rate_limit", _allow)
    monkeypatch.setattr("app.webhooks.handlers.current_daily_token_usage", _daily_usage)

    await queue_pull_request_review(redis, payload)

    assert len(redis.calls) == 1
    assert redis.calls[0][0] == "review_pr"
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, payload.installation.id)
        count = await session.scalar(
            select(func.count(Review.id))
            .where(Review.installation_id == payload.installation.id)
            .where(Review.pr_number == payload.pull_request.number)
            .where(Review.pr_head_sha == payload.pull_request.head.sha)
        )
    assert count == 1


@pytest.mark.anyio
async def test_queue_pull_request_review_enqueues_when_skip_tag_in_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    payload = _payload(body="## Notes\n\n[skip-nash-review] while iterating\n")

    async def _allow(*_args: object, **_kwargs: object) -> bool:
        return True

    async def _daily_usage(*_args: object, **_kwargs: object) -> int:
        return 0

    monkeypatch.setattr("app.webhooks.handlers.check_installation_review_rate_limit", _allow)
    monkeypatch.setattr("app.webhooks.handlers.current_daily_token_usage", _daily_usage)

    await queue_pull_request_review(redis, payload)
    assert len(redis.calls) == 1
    assert redis.calls[0][0] == "review_pr"


@pytest.mark.anyio
async def test_queue_pull_request_review_force_tag_overrides_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    payload = _payload(title="[skip-nash-review]", body="[force-nash-review]")

    async def _allow(*_args: object, **_kwargs: object) -> bool:
        return True

    async def _daily_usage(*_args: object, **_kwargs: object) -> int:
        return 0

    monkeypatch.setattr("app.webhooks.handlers.check_installation_review_rate_limit", _allow)
    monkeypatch.setattr("app.webhooks.handlers.current_daily_token_usage", _daily_usage)

    await queue_pull_request_review(redis, payload)
    assert len(redis.calls) == 1
    assert redis.calls[0][0] == "review_pr"


@pytest.mark.anyio
async def test_queue_pull_request_review_skip_tag_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    payload = _payload(title="[Skip-Nash-Review]")

    async def _allow(*_args: object, **_kwargs: object) -> bool:
        return True

    async def _daily_usage(*_args: object, **_kwargs: object) -> int:
        return 0

    monkeypatch.setattr("app.webhooks.handlers.check_installation_review_rate_limit", _allow)
    monkeypatch.setattr("app.webhooks.handlers.current_daily_token_usage", _daily_usage)

    await queue_pull_request_review(redis, payload)
    assert len(redis.calls) == 1
    assert redis.calls[0][0] == "review_pr"


@pytest.mark.anyio
async def test_primary_provider_for_circuit_breaker_prefers_default_when_configured(
) -> None:
    installation_id = randint(100_000_000, 999_999_999)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            Installation(
                installation_id=installation_id,
                account_login=f"acme-{installation_id}",
                account_type="Organization",
            )
        )
        await session.commit()
    assert await _primary_provider_for_circuit_breaker(installation_id) == "anthropic"


@pytest.mark.anyio
async def test_primary_provider_for_circuit_breaker_falls_back_to_first_configured(
) -> None:
    installation_id = randint(100_000_000, 999_999_999)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            Installation(
                installation_id=installation_id,
                account_login=f"acme-{installation_id}",
                account_type="Organization",
            )
        )
        session.add_all(
            [
                Review(
                    installation_id=installation_id,
                    repo_full_name="acme/repo",
                    pr_number=1,
                    pr_head_sha=(uuid4().hex + uuid4().hex)[:40],
                    status="done",
                    model_provider="anthropic",
                    model="claude-sonnet-4-5",
                ),
                Review(
                    installation_id=installation_id,
                    repo_full_name="acme/repo",
                    pr_number=2,
                    pr_head_sha=(uuid4().hex + uuid4().hex)[:40],
                    status="done",
                    model_provider="openai",
                    model="gpt-5.5",
                ),
            ]
        )
        await session.commit()
    assert await _primary_provider_for_circuit_breaker(installation_id) == "openai"
