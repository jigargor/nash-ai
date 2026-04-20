import pytest
from sqlalchemy import func, select
from uuid import uuid4

from app.db.models import Review
from app.db.session import AsyncSessionLocal, set_installation_context
from app.webhooks.handlers import queue_pull_request_review
from app.webhooks.schemas import GitHubPullRequestWebhookPayload


class _FakeJob:
    def __init__(self, job_id: str):
        self.job_id = job_id


class _FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def enqueue_job(self, *args: object) -> _FakeJob:
        self.calls.append(args)
        return _FakeJob(job_id=f"job-{len(self.calls)}")


def _payload(action: str = "opened") -> GitHubPullRequestWebhookPayload:
    head_sha = (uuid4().hex + uuid4().hex)[:40]
    return GitHubPullRequestWebhookPayload.model_validate(
        {
            "action": action,
            "installation": {"id": 555},
            "repository": {"full_name": "acme/repo", "owner": {"login": "acme", "type": "Organization"}},
            "pull_request": {"number": 99, "head": {"sha": head_sha}},
        }
    )


@pytest.mark.anyio
async def test_queue_pull_request_review_skips_duplicate_active_review() -> None:
    redis = _FakeRedis()
    payload = _payload()

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
