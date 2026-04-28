from __future__ import annotations

import pytest

from app.queue import worker as worker_module


def test_worker_settings_disable_retries_for_review_jobs() -> None:
    assert worker_module.WorkerSettings.max_tries == 1


@pytest.mark.anyio
async def test_review_pr_forwards_redis_context_and_user(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_run_review(
        review_id: int,
        installation_id: int,
        owner: str,
        repo: str,
        pr_number: int,
        head_sha: str,
        *,
        user_github_id: int | None = None,
        redis: object | None = None,
    ) -> None:
        captured["review_id"] = review_id
        captured["installation_id"] = installation_id
        captured["owner"] = owner
        captured["repo"] = repo
        captured["pr_number"] = pr_number
        captured["head_sha"] = head_sha
        captured["user_github_id"] = user_github_id
        captured["redis"] = redis

    monkeypatch.setattr(worker_module, "run_review", _fake_run_review)

    redis_client = object()
    await worker_module.review_pr(
        {"redis": redis_client},
        123,
        456,
        "acme",
        "nash-ai",
        99,
        "a" * 40,
        user_github_id=777,
    )

    assert captured == {
        "review_id": 123,
        "installation_id": 456,
        "owner": "acme",
        "repo": "nash-ai",
        "pr_number": 99,
        "head_sha": "a" * 40,
        "user_github_id": 777,
        "redis": redis_client,
    }
