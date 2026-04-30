from random import randint

import pytest
from sqlalchemy import func, select
from uuid import uuid4

from app.config import settings
from app.crypto import encrypt_secret
from app.db.models import Installation, InstallationUser, Review, User, UserProviderKey
from app.db.session import AsyncSessionLocal, engine, set_installation_context, set_user_context
from app.webhooks.handlers import (
    _primary_provider_for_circuit_breaker,
    queue_pull_request_outcome_classification,
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
        self.kwargs_calls: list[dict[str, object]] = []
        self.locks: set[str] = set()

    async def exists(self, *keys: object) -> int:
        """Redis EXISTS shim: no keys stored in this fake, so circuit is never open."""
        return 0

    async def enqueue_job(self, *args: object, **kwargs: object) -> _FakeJob:
        self.calls.append(args)
        self.kwargs_calls.append(dict(kwargs))
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


@pytest.mark.anyio
async def test_queue_pull_request_outcome_classification_enqueues_expected_job() -> None:
    redis = _FakeRedis()
    payload = _payload(action="closed")

    await queue_pull_request_outcome_classification(redis, payload)

    assert len(redis.calls) == 1
    assert redis.calls[0][0] == "classify_pr_outcomes"
    assert redis.calls[0][1] == payload.installation.id
    assert redis.calls[0][2] == "acme"
    assert redis.calls[0][3] == "repo"
    assert redis.calls[0][4] == payload.pull_request.number


@pytest.mark.anyio
async def test_queue_pull_request_review_skips_when_provider_circuit_is_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CircuitOpenRedis(_FakeRedis):
        async def exists(self, *keys: object) -> int:
            if any(str(key) == "circuit:open:anthropic" for key in keys):
                return 1
            return 0

    class _FakeGitHubClient:
        def __init__(self) -> None:
            self.comments: list[tuple[str, str, int, str]] = []

        async def post_issue_comment(
            self,
            owner: str,
            repo: str,
            pr_number: int,
            body: str,
        ) -> None:
            self.comments.append((owner, repo, pr_number, body))

    redis = _CircuitOpenRedis()
    payload = _payload()
    fake_gh = _FakeGitHubClient()

    async def _allow(*_args: object, **_kwargs: object) -> bool:
        return True

    async def _daily_usage(*_args: object, **_kwargs: object) -> int:
        return 0

    async def _for_installation(_installation_id: int) -> _FakeGitHubClient:
        return fake_gh

    monkeypatch.setattr("app.webhooks.handlers.check_installation_review_rate_limit", _allow)
    monkeypatch.setattr("app.webhooks.handlers.current_daily_token_usage", _daily_usage)
    async def _primary_provider(_installation_id: int) -> str:
        return "anthropic"

    monkeypatch.setattr("app.webhooks.handlers._primary_provider_for_circuit_breaker", _primary_provider)
    monkeypatch.setattr("app.github.client.GitHubClient.for_installation", _for_installation)

    await queue_pull_request_review(redis, payload)

    assert redis.calls == []
    assert len(fake_gh.comments) == 1
    owner, repo, pr_number, body = fake_gh.comments[0]
    assert owner == "acme"
    assert repo == "repo"
    assert pr_number == payload.pull_request.number
    assert "Automated review delayed" in body


@pytest.mark.anyio
async def test_queue_pull_request_review_skips_when_reviews_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    payload = _payload()

    monkeypatch.setattr("app.webhooks.handlers.settings.enable_reviews", False)

    await queue_pull_request_review(redis, payload)

    assert redis.calls == []


@pytest.mark.anyio
async def test_queue_pull_request_review_skips_without_llm_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    payload = _payload()

    monkeypatch.setattr("app.webhooks.handlers.settings.enable_reviews", True)
    monkeypatch.setattr("app.webhooks.handlers.settings.openai_api_key", "")
    monkeypatch.setattr("app.webhooks.handlers.settings.anthropic_api_key", "")
    monkeypatch.setattr("app.webhooks.handlers.settings.gemini_api_key", "")
    async def _no_byok_user(_installation_id: int) -> None:
        return None

    monkeypatch.setattr("app.webhooks.handlers._resolve_byok_user_for_installation", _no_byok_user)

    await queue_pull_request_review(redis, payload)

    assert redis.calls == []


@pytest.mark.anyio
async def test_queue_pull_request_review_enqueues_with_linked_byok_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    payload = _payload()

    monkeypatch.setattr("app.webhooks.handlers.settings.enable_reviews", True)
    monkeypatch.setattr("app.webhooks.handlers.settings.openai_api_key", "")
    monkeypatch.setattr("app.webhooks.handlers.settings.anthropic_api_key", "")
    monkeypatch.setattr("app.webhooks.handlers.settings.gemini_api_key", "")

    async def _allow(*_args: object, **_kwargs: object) -> bool:
        return True

    async def _daily_usage(*_args: object, **_kwargs: object) -> int:
        return 0

    monkeypatch.setattr("app.webhooks.handlers.check_installation_review_rate_limit", _allow)
    monkeypatch.setattr("app.webhooks.handlers.current_daily_token_usage", _daily_usage)

    github_id = randint(100_000_000, 999_999_999)
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
            await session.flush()
        await set_user_context(session, github_id)
        user = User(github_id=github_id, login=f"user-{github_id}", token_enc=None)
        session.add(user)
        await session.flush()
        session.add(
            InstallationUser(
                installation_id=payload.installation.id,
                user_id=int(user.id),
                role="member",
            )
        )
        session.add(
            UserProviderKey(
                user_id=int(user.id),
                provider="anthropic",
                key_enc=encrypt_secret("sk-ant-test-key-that-is-at-least-20-chars"),
            )
        )
        await session.commit()

    await queue_pull_request_review(redis, payload)

    assert len(redis.calls) == 1
    assert redis.calls[0][0] == "review_pr"
    assert redis.kwargs_calls[0]["user_github_id"] == github_id


@pytest.mark.anyio
async def test_queue_pull_request_review_skips_when_daily_budget_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    payload = _payload()

    async def _allow(*_args: object, **_kwargs: object) -> bool:
        return True

    async def _daily_usage(*_args: object, **_kwargs: object) -> int:
        return settings.daily_token_budget_per_installation

    monkeypatch.setattr("app.webhooks.handlers.check_installation_review_rate_limit", _allow)
    monkeypatch.setattr("app.webhooks.handlers.current_daily_token_usage", _daily_usage)

    await queue_pull_request_review(redis, payload)

    assert redis.calls == []
