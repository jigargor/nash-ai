from random import randint

import pytest
from sqlalchemy import func, select
from uuid import uuid4

from app.db.models import Installation, Review
from app.db.session import AsyncSessionLocal, engine, set_installation_context
from app.webhooks.handlers import queue_pull_request_review, sync_installation_from_webhook
from app.webhooks.schemas import GitHubInstallationWebhookPayload, GitHubPullRequestWebhookPayload


class _FakeJob:
    def __init__(self, job_id: str):
        self.job_id = job_id


class _FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def enqueue_job(self, *args: object) -> _FakeJob:
        self.calls.append(args)
        return _FakeJob(job_id=f"job-{len(self.calls)}")


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
async def test_queue_pull_request_review_skips_when_skip_tag_in_title(
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

    assert not redis.calls
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, payload.installation.id)
        count = await session.scalar(
            select(func.count(Review.id))
            .where(Review.installation_id == payload.installation.id)
            .where(Review.pr_number == payload.pull_request.number)
            .where(Review.pr_head_sha == payload.pull_request.head.sha)
        )
    assert count == 0


@pytest.mark.anyio
async def test_queue_pull_request_review_skips_when_skip_tag_in_body(
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
    assert not redis.calls


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
    assert not redis.calls
