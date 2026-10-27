"""Integration tests for the full review pipeline in runner.py.

These tests exercise the orchestration layer (run_review) with mocked external
dependencies so we can verify the pipeline stages are wired correctly and the
Review object ends up in the expected terminal state.

The DB layer is mocked (same pattern as test_mark_review_done_persists_runtime_model)
to avoid event-loop lifecycle issues with the async connection pool in tests.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.runner import run_review
from app.agent.schema import EditedReview, ReviewResult

_INSTALLATION_ID = 99_001
_OWNER = "acme"
_REPO = "test-repo"
_PR_NUMBER = 7
_HEAD_SHA = "deadbeef" * 5  # 40 chars


def _make_fake_review(review_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=review_id,
        installation_id=_INSTALLATION_ID,
        repo_full_name=f"{_OWNER}/{_REPO}",
        pr_number=_PR_NUMBER,
        pr_head_sha=_HEAD_SHA,
        model="claude-sonnet-4-5",
        status="queued",
        findings=None,
        debug_artifacts=None,
        tokens_used=None,
        cost_usd=None,
        completed_at=None,
        started_at=None,
    )


def _make_fake_session(review: SimpleNamespace) -> object:
    class FakeSession:
        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, _model: object, _review_id: int) -> object:
            return review

        async def commit(self) -> None:
            return None

        def add(self, _obj: object) -> None:
            return None

    return FakeSession()


async def _fake_set_installation_context(_session: object, _installation_id: int) -> None:
    return None


def _make_mock_gh(*, draft: bool = False) -> AsyncMock:
    gh = AsyncMock()
    gh.get_pull_request.return_value = {
        "number": _PR_NUMBER,
        "title": "Test PR",
        "body": "",
        "state": "open",
        "draft": draft,
        "head": {"sha": _HEAD_SHA},
        "merge_commit_sha": None,
    }
    gh.get_pull_request_diff.return_value = (
        "diff --git a/hello.py b/hello.py\n"
        "--- a/hello.py\n"
        "+++ b/hello.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def greet():\n"
        "+    x = eval(input())\n"
        "     return 'hi'\n"
    )
    gh.get_pull_request_files.return_value = [{"filename": "hello.py", "status": "modified"}]
    gh.get_pull_request_commits.return_value = []
    gh.get_file_content.return_value = "def greet():\n    return 'hi'\n"
    gh.get_pr_reviews_by_bot.return_value = []
    gh.post_json.return_value = {"id": 1}
    return gh


@pytest.mark.anyio
async def test_run_review_skips_draft_pr() -> None:
    review = _make_fake_review()
    mock_gh = _make_mock_gh(draft=True)

    with (
        patch("app.agent.runner.AsyncSessionLocal", return_value=_make_fake_session(review)),
        patch(
            "app.agent.runner.set_installation_context",
            new=AsyncMock(side_effect=_fake_set_installation_context),
        ),
        patch("app.agent.runner.GitHubClient.for_installation", return_value=mock_gh),
        patch("app.agent.runner._record_token_budget_usage", new=AsyncMock()),
        patch("app.agent.runner.record_review_trace"),
        patch("app.agent.runner.get_cached_review_config", new=AsyncMock(return_value=None)),
        patch("app.agent.runner.set_cached_review_config", new=AsyncMock()),
        patch("app.agent.profiler_cache.get_cached_repo_profile", new=AsyncMock(return_value=None)),
        patch("app.agent.profiler_cache.set_cached_repo_profile", new=AsyncMock()),
    ):
        await run_review(int(review.id), _INSTALLATION_ID, _OWNER, _REPO, _PR_NUMBER, _HEAD_SHA)

    assert review.status == "skipped"
    assert "draft" in (review.findings or {}).get("summary", "").lower()


@pytest.mark.anyio
async def test_run_review_full_pipeline_marks_done() -> None:
    review = _make_fake_review()
    mock_gh = _make_mock_gh()
    empty_result = ReviewResult(findings=[], summary="No issues found in this minimal diff.")
    edited_pass_through = EditedReview(
        findings=list(empty_result.findings),
        summary=empty_result.summary,
        decisions=[],
    )

    with (
        patch("app.agent.runner.AsyncSessionLocal", return_value=_make_fake_session(review)),
        patch(
            "app.agent.runner.set_installation_context",
            new=AsyncMock(side_effect=_fake_set_installation_context),
        ),
        patch("app.agent.runner.GitHubClient.for_installation", return_value=mock_gh),
        patch("app.agent.runner.run_agent", new=AsyncMock(return_value=[])),
        patch("app.agent.runner.finalize_review", new=AsyncMock(return_value=empty_result)),
        patch("app.agent.runner.run_editor", new=AsyncMock(return_value=edited_pass_through)),
        patch("app.agent.runner._record_token_budget_usage", new=AsyncMock()),
        patch("app.agent.runner.record_review_trace"),
        patch("app.agent.runner.post_review", new=AsyncMock(return_value={})),
        patch("app.agent.runner.seed_pending_finding_outcomes", new=AsyncMock()),
        patch("app.agent.runner.get_cached_review_config", new=AsyncMock(return_value=None)),
        patch("app.agent.runner.set_cached_review_config", new=AsyncMock()),
        patch("app.agent.profiler_cache.get_cached_repo_profile", new=AsyncMock(return_value=None)),
        patch("app.agent.profiler_cache.set_cached_repo_profile", new=AsyncMock()),
    ):
        await run_review(int(review.id), _INSTALLATION_ID, _OWNER, _REPO, _PR_NUMBER, _HEAD_SHA)

    assert review.status == "done"


class _RecordingRedis:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, key: str) -> int:
        self.deleted.append(key)
        return 1


@pytest.mark.anyio
async def test_run_review_supersedes_when_pr_head_moved_and_releases_lock() -> None:
    review = _make_fake_review()
    mock_gh = _make_mock_gh()
    mock_gh.get_pull_request.return_value = {
        **mock_gh.get_pull_request.return_value,
        "head": {"sha": "f" * 40},
    }
    post_review_mock = AsyncMock(return_value={})
    redis = _RecordingRedis()

    with (
        patch("app.agent.runner.AsyncSessionLocal", return_value=_make_fake_session(review)),
        patch(
            "app.agent.runner.set_installation_context",
            new=AsyncMock(side_effect=_fake_set_installation_context),
        ),
        patch("app.agent.runner.GitHubClient.for_installation", return_value=mock_gh),
        patch("app.agent.runner._record_token_budget_usage", new=AsyncMock()),
        patch("app.agent.runner.record_review_trace"),
        patch("app.agent.runner.post_review", new=post_review_mock),
        patch("app.agent.runner.get_cached_review_config", new=AsyncMock(return_value=None)),
        patch("app.agent.runner.set_cached_review_config", new=AsyncMock()),
    ):
        await run_review(
            int(review.id),
            _INSTALLATION_ID,
            _OWNER,
            _REPO,
            _PR_NUMBER,
            _HEAD_SHA,
            redis=redis,
        )

    assert review.status == "superseded"
    assert "superseded" in (review.findings or {}).get("summary", "").lower()
    post_review_mock.assert_not_awaited()
    mock_gh.get_pull_request_diff.assert_not_awaited()
    assert redis.deleted == [f"review-submit:{_INSTALLATION_ID}:{_OWNER}/{_REPO}:{_PR_NUMBER}:{_HEAD_SHA}"]
    mock_gh.aclose.assert_awaited()


@pytest.mark.anyio
async def test_run_review_prefers_compare_diff_pinned_to_job_head() -> None:
    review = _make_fake_review()
    mock_gh = _make_mock_gh(draft=True)
    mock_gh.get_pull_request.return_value = {
        **mock_gh.get_pull_request.return_value,
        "base": {"sha": "b" * 40},
    }
    mock_gh.get_compare_diff.return_value = mock_gh.get_pull_request_diff.return_value

    with (
        patch("app.agent.runner.AsyncSessionLocal", return_value=_make_fake_session(review)),
        patch(
            "app.agent.runner.set_installation_context",
            new=AsyncMock(side_effect=_fake_set_installation_context),
        ),
        patch("app.agent.runner.GitHubClient.for_installation", return_value=mock_gh),
        patch("app.agent.runner._record_token_budget_usage", new=AsyncMock()),
        patch("app.agent.runner.record_review_trace"),
        patch("app.agent.runner.get_cached_review_config", new=AsyncMock(return_value=None)),
        patch("app.agent.runner.set_cached_review_config", new=AsyncMock()),
        patch("app.agent.profiler_cache.get_cached_repo_profile", new=AsyncMock(return_value=None)),
        patch("app.agent.profiler_cache.set_cached_repo_profile", new=AsyncMock()),
    ):
        await run_review(int(review.id), _INSTALLATION_ID, _OWNER, _REPO, _PR_NUMBER, _HEAD_SHA)

    mock_gh.get_compare_diff.assert_awaited_once_with(_OWNER, _REPO, "b" * 40, _HEAD_SHA)
    mock_gh.get_pull_request_diff.assert_not_awaited()
    assert review.status == "skipped"
