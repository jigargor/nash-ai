"""Phase 5: tenant isolation + feedback loop (unit-level checks, no live GitHub)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.webhooks.handlers import queue_review_comment_feedback
from app.webhooks.schemas import GitHubPullRequestReviewCommentWebhookPayload

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "x4y5z6a7b8c9_enable_rls_missed_issues.py"
)


def _payload(
    *, action: str = "created", in_reply_to_id: int | None = 10, user_type: str = "User"
) -> GitHubPullRequestReviewCommentWebhookPayload:
    return GitHubPullRequestReviewCommentWebhookPayload.model_validate(
        {
            "action": action,
            "installation": {"id": 99},
            "repository": {"full_name": "acme/repo", "owner": {"login": "acme", "type": "Org"}},
            "pull_request": {"number": 7},
            "comment": {
                "id": 11,
                "in_reply_to_id": in_reply_to_id,
                "body": "won't fix",
                "user": {"login": "dev", "type": user_type},
            },
        }
    )


class _FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[object, ...]]] = []

    async def enqueue_job(self, name: str, *args: object) -> SimpleNamespace:
        self.jobs.append((name, args))
        return SimpleNamespace(job_id="job-1")


@pytest.mark.anyio
async def test_review_comment_reply_is_enqueued() -> None:
    redis = _FakeRedis()
    queued = await queue_review_comment_feedback(redis, _payload())  # type: ignore[arg-type]
    assert queued is True
    assert redis.jobs[0][0] == "record_review_comment_feedback"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"action": "edited"},
        {"action": "deleted"},
        {"in_reply_to_id": None},
        {"user_type": "Bot"},
    ],
)
async def test_review_comment_non_feedback_events_are_not_enqueued(
    kwargs: dict[str, object],
) -> None:
    redis = _FakeRedis()
    queued = await queue_review_comment_feedback(redis, _payload(**kwargs))  # type: ignore[arg-type]
    assert queued is False
    assert redis.jobs == []


def test_missed_issues_rls_migration_is_forced_and_reversible() -> None:
    spec = importlib.util.spec_from_file_location("missed_issues_rls", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "w3x4y5z6a7b8"
    source = _MIGRATION.read_text(encoding="utf-8")
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "NO FORCE ROW LEVEL SECURITY" in source
    for command in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert f"FOR {command}" in source
    assert "nullif(current_setting('app.current_installation_id', true), '')::bigint" in source
