from __future__ import annotations

import pytest

from app.queue import worker


def test_tune_fast_path_thresholds_refreshes_judge_windows_first(
    monkeypatch,
) -> None:
    calls: list[str] = []

    async def _fake_refresh(_config):
        calls.append("refresh")
        return {"enabled": True, "updated": 1, "installation_ids": [1]}

    async def _fake_tune(_config):
        calls.append("tune")
        return []

    monkeypatch.setattr(worker, "refresh_judge_gate_windows", _fake_refresh)
    monkeypatch.setattr(worker, "tune_all_installations", _fake_tune)

    ctx: dict[str, object] = {}
    import asyncio

    asyncio.run(worker.tune_fast_path_thresholds(ctx))
    assert calls == ["refresh", "tune"]
    assert "judge_gate_window_refresh" in ctx
    assert "threshold_tuning_results" in ctx

def test_worker_settings_allow_one_retry_after_worker_interruption() -> None:
    assert worker.WorkerSettings.max_tries == 2


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

    monkeypatch.setattr(worker, "run_review", _fake_run_review)

    redis_client = object()
    await worker.review_pr(
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


@pytest.mark.anyio
async def test_review_pr_routes_through_pipeline_adapter_when_flag_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _legacy(*_args: object, **_kwargs: object) -> None:
        calls.append("legacy")

    async def _pipeline(*_args: object, **_kwargs: object) -> None:
        calls.append("pipeline")

    monkeypatch.setattr(worker, "run_review", _legacy)
    monkeypatch.setattr(worker, "run_review_via_pipeline", _pipeline)

    monkeypatch.setattr(worker.settings, "use_review_pipeline_worker", False)
    await worker.review_pr({}, 1, 2, "acme", "nash-ai", 3, "a" * 40)
    monkeypatch.setattr(worker.settings, "use_review_pipeline_worker", True)
    await worker.review_pr({}, 1, 2, "acme", "nash-ai", 3, "a" * 40)

    assert calls == ["legacy", "pipeline"]
