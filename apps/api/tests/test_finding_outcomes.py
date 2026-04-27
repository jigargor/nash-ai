from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

import app.telemetry.finding_outcomes as finding_outcomes_module
from app.db.models import FindingOutcome, Installation, Review
from app.db.session import AsyncSessionLocal, engine, set_installation_context
from app.telemetry.finding_outcomes import (
    Outcome,
    _coerce_int,
    _has_bot_coauthor,
    _looks_like_modified_apply,
    _safe_commit_list,
    _safe_reaction_list,
    _safe_reply_list,
    classify_pending_outcomes_nightly,
    classify_finding_outcome,
    classify_review_outcomes,
    commits_scoped_narrowly,
    detect_suggestion_apply,
    list_review_finding_outcomes,
    seed_pending_finding_outcomes,
    summarize_finding_outcomes,
)


def _random_installation_id() -> int:
    return int(str(uuid4().int)[:9])


async def _seed_installation(installation_id: int) -> None:
    await engine.dispose()
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


async def _seed_review(
    installation_id: int,
    *,
    repo_full_name: str = "acme/repo",
    findings: list[dict[str, object]] | None = None,
) -> int:
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = Review(
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=9,
            pr_head_sha="b" * 40,
            status="done",
            model_provider="anthropic",
            model="claude-sonnet-4-5",
            findings={"findings": findings or []},
            debug_artifacts={"prompt_version": "v-test"},
            tokens_used=100,
            cost_usd=0.1,
        )
        session.add(review)
        await session.flush()
        review_id = int(review.id)
        await session.commit()
    return review_id


class _FakeGitHubClient:
    async def get_pull_review_comment_reactions(
        self, _owner: str, _repo: str, _comment_id: int | None
    ) -> list[dict[str, object]]:
        return []

    async def get_pull_review_comment_replies(
        self, _owner: str, _repo: str, _comment_id: int | None
    ) -> list[dict[str, object]]:
        return []

    async def is_pull_review_thread_resolved(
        self, _owner: str, _repo: str, _pr_number: int, _comment_id: int | None
    ) -> bool:
        return False

    async def get_commits_touching_file(
        self,
        *,
        owner: str,
        repo: str,
        path: str,
        since: datetime | None,
    ) -> list[dict[str, object]]:
        _ = (owner, repo, path, since)
        return []

    async def line_exists_in_pull_request_final_state(
        self,
        *,
        owner: str,
        repo: str,
        pr_state: dict[str, object],
        file_path: str,
        line_text: str,
    ) -> bool:
        _ = (owner, repo, pr_state, file_path, line_text)
        return True

    async def get_commit_files(self, _owner: str, _repo: str, _sha: str) -> list[dict[str, object]]:
        return []


@pytest.mark.anyio
async def test_summarize_finding_outcomes_excludes_pending_and_computes_useful_rate() -> None:
    installation_id = _random_installation_id()
    await _seed_installation(installation_id)
    review_id = await _seed_review(
        installation_id,
        findings=[
            {
                "severity": "high",
                "category": "security",
                "evidence": "tool_verified",
                "confidence": 95,
            },
            {
                "severity": "low",
                "category": "performance",
                "evidence": "inference",
                "confidence": 55,
            },
        ],
    )

    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add_all(
            [
                FindingOutcome(
                    review_id=review_id,
                    finding_index=0,
                    github_comment_id=101,
                    outcome=Outcome.APPLIED_DIRECTLY.value,
                    outcome_confidence="high",
                    signals={},
                ),
                FindingOutcome(
                    review_id=review_id,
                    finding_index=1,
                    github_comment_id=102,
                    outcome=Outcome.PENDING.value,
                    outcome_confidence="high",
                    signals={},
                ),
            ]
        )
        await session.commit()

    summary = await summarize_finding_outcomes(
        installation_id=installation_id, repo_full_name="acme/repo"
    )
    assert summary["total_classified"] == 1
    assert summary["global_metrics"]["useful_rate"] == pytest.approx(1.0)
    assert summary["outcomes"][Outcome.APPLIED_DIRECTLY.value] == 1
    assert "anthropic" in summary["breakdowns"]["provider"]


@pytest.mark.anyio
async def test_summarize_finding_outcomes_without_installation_sets_scoped_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation_id = _random_installation_id()
    repo_full_name = f"acme/repo-{installation_id}"
    await _seed_installation(installation_id)
    review_id = await _seed_review(
        installation_id,
        repo_full_name=repo_full_name,
        findings=[{"severity": "high", "category": "security", "evidence": "diff_visible"}],
    )
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            FindingOutcome(
                review_id=review_id,
                finding_index=0,
                github_comment_id=103,
                outcome=Outcome.APPLIED_DIRECTLY.value,
                outcome_confidence="high",
                signals={},
            )
        )
        await session.commit()

    seen_installation_contexts: list[int] = []
    original_set_installation_context = finding_outcomes_module.set_installation_context

    async def spy_set_installation_context(session: object, scoped_installation_id: int) -> None:
        seen_installation_contexts.append(scoped_installation_id)
        await original_set_installation_context(session, scoped_installation_id)

    monkeypatch.setattr(
        finding_outcomes_module, "set_installation_context", spy_set_installation_context
    )
    summary = await summarize_finding_outcomes(repo_full_name=repo_full_name)
    assert summary["total_classified"] == 1
    assert installation_id in seen_installation_contexts


@pytest.mark.anyio
async def test_list_review_finding_outcomes_returns_sorted_rows() -> None:
    installation_id = _random_installation_id()
    await _seed_installation(installation_id)
    review_id = await _seed_review(installation_id, findings=[{}, {}])

    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add_all(
            [
                FindingOutcome(
                    review_id=review_id,
                    finding_index=1,
                    github_comment_id=201,
                    outcome=Outcome.IGNORED.value,
                    outcome_confidence="low",
                    signals={},
                ),
                FindingOutcome(
                    review_id=review_id,
                    finding_index=0,
                    github_comment_id=200,
                    outcome=Outcome.ACKNOWLEDGED.value,
                    outcome_confidence="medium",
                    signals={},
                ),
            ]
        )
        await session.commit()

    rows = await list_review_finding_outcomes(review_id, installation_id)
    assert [item["finding_index"] for item in rows] == [0, 1]
    assert rows[0]["outcome"] == Outcome.ACKNOWLEDGED.value
    assert rows[1]["outcome"] == Outcome.IGNORED.value


@pytest.mark.anyio
async def test_classify_review_outcomes_writes_pending_for_open_pr_recent_review() -> None:
    installation_id = _random_installation_id()
    await _seed_installation(installation_id)
    review_id = await _seed_review(
        installation_id,
        findings=[
            {
                "file_path": "src/main.py",
                "line_start": 8,
                "line_end": 8,
                "target_line_content": "print('hi')",
                "suggestion": None,
            }
        ],
    )

    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = await session.scalar(select(Review).where(Review.id == review_id))
        assert review is not None

    gh = _FakeGitHubClient()
    await classify_review_outcomes(
        gh=gh,
        review=review,
        owner="acme",
        repo="repo",
        pr_number=9,
        pr_state={"state": "open", "merged": False},
    )

    rows = await list_review_finding_outcomes(review_id, installation_id)
    assert len(rows) == 1
    assert rows[0]["outcome"] == Outcome.PENDING.value


@pytest.mark.anyio
async def test_classify_pending_outcomes_nightly_sets_scoped_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation_id = _random_installation_id()
    repo_full_name = f"acme/repo-{installation_id}"
    await _seed_installation(installation_id)
    review_id = await _seed_review(
        installation_id,
        repo_full_name=repo_full_name,
        findings=[
            {
                "file_path": "src/main.py",
                "line_start": 8,
                "line_end": 8,
                "target_line_content": "print('hi')",
                "suggestion": None,
            }
        ],
    )

    await engine.dispose()
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = await session.scalar(select(Review).where(Review.id == review_id))
        assert review is not None
        review.created_at = datetime.now(timezone.utc) - timedelta(days=20)
        session.add(
            FindingOutcome(
                review_id=review_id,
                finding_index=0,
                github_comment_id=5001,
                outcome=Outcome.PENDING.value,
                outcome_confidence="high",
                signals={},
            )
        )
        await session.commit()

    seen_installation_contexts: list[int] = []
    original_set_installation_context = finding_outcomes_module.set_installation_context
    classify_calls: list[int] = []

    class _NightlyGitHubClient:
        async def get_pull_request(
            self, _owner: str, _repo: str, _pr_number: int
        ) -> dict[str, object]:
            return {"state": "closed", "merged": True}

    async def spy_set_installation_context(session: object, scoped_installation_id: int) -> None:
        seen_installation_contexts.append(scoped_installation_id)
        await original_set_installation_context(session, scoped_installation_id)

    async def fake_classify_review_outcomes(**kwargs: object) -> None:
        review = kwargs.get("review")
        review_id_value = getattr(review, "id", None)
        if isinstance(review_id_value, int):
            classify_calls.append(review_id_value)

    async def fake_for_installation(_installation_id: int) -> _NightlyGitHubClient:
        return _NightlyGitHubClient()

    monkeypatch.setattr(
        finding_outcomes_module, "set_installation_context", spy_set_installation_context
    )
    monkeypatch.setattr(
        finding_outcomes_module, "classify_review_outcomes", fake_classify_review_outcomes
    )
    monkeypatch.setattr(
        finding_outcomes_module.GitHubClient, "for_installation", fake_for_installation
    )

    await classify_pending_outcomes_nightly(max_open_days=14)
    assert installation_id in seen_installation_contexts
    assert review_id in classify_calls


@pytest.mark.anyio
async def test_classify_finding_outcome_acknowledged_for_merged_pr_with_positive_reaction() -> None:
    class _PositiveReactionClient(_FakeGitHubClient):
        async def get_pull_review_comment_reactions(
            self, _owner: str, _repo: str, _comment_id: int | None
        ) -> list[dict[str, object]]:
            return [{"content": "+1"}]

    now = datetime.now(timezone.utc)
    review = SimpleNamespace(
        id=1234,
        installation_id=9999,
        created_at=now,
        completed_at=now,
    )
    finding = {
        "file_path": "src/main.py",
        "line_start": 10,
        "line_end": 10,
        "target_line_content": "value = 1",
        "suggestion": None,
    }

    decision = await classify_finding_outcome(
        gh=_PositiveReactionClient(),
        owner="acme",
        repo="repo",
        pr_number=12,
        review=review,
        finding=finding,
        comment_id=999,
        pr_state={"state": "closed", "merged": True},
    )
    assert decision.outcome == Outcome.ACKNOWLEDGED


# ---------------------------------------------------------------------------
# _coerce_int
# ---------------------------------------------------------------------------


def test_coerce_int_from_int() -> None:
    assert _coerce_int(42) == 42


def test_coerce_int_from_float() -> None:
    assert _coerce_int(3.7) == 3


def test_coerce_int_from_numeric_string() -> None:
    assert _coerce_int("95") == 95


def test_coerce_int_from_bool_returns_default() -> None:
    assert _coerce_int(True, 0) == 0
    assert _coerce_int(False, 99) == 99


def test_coerce_int_from_invalid_string_returns_default() -> None:
    assert _coerce_int("not-a-number", 7) == 7


def test_coerce_int_from_none_returns_default() -> None:
    assert _coerce_int(None, 5) == 5


def test_coerce_int_empty_string_returns_default() -> None:
    assert _coerce_int("", 3) == 3


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_safe_commit_list_filters_non_dicts() -> None:
    raw = [{"sha": "a"}, "not-a-dict", None, {"sha": "b"}]
    result = _safe_commit_list(raw)
    assert len(result) == 2


def test_safe_commit_list_non_list_returns_empty() -> None:
    assert _safe_commit_list("string") == []
    assert _safe_commit_list(None) == []


def test_safe_reaction_list_filters_non_dicts() -> None:
    assert _safe_reaction_list([{"+1": True}, "bad"]) == [{"+1": True}]


def test_safe_reply_list_non_list_returns_empty() -> None:
    assert _safe_reply_list(42) == []


def test_has_bot_coauthor_true() -> None:
    from app.telemetry.finding_outcomes import BOT_COAUTHOR
    commit = {"co_authored_by": BOT_COAUTHOR}
    assert _has_bot_coauthor(commit) is True


def test_has_bot_coauthor_false() -> None:
    assert _has_bot_coauthor({"co_authored_by": "someone-else"}) is False


def test_has_bot_coauthor_missing_field() -> None:
    assert _has_bot_coauthor({}) is False


def test_looks_like_modified_apply_true() -> None:
    added = ["value = encrypt(secret_key)", "return value"]
    suggestion = ["value = encrypt(key)", "return value"]
    assert _looks_like_modified_apply(added, suggestion) is True


def test_looks_like_modified_apply_false_empty_inputs() -> None:
    assert _looks_like_modified_apply([], ["x"]) is False
    assert _looks_like_modified_apply(["x"], []) is False


def test_looks_like_modified_apply_no_overlap() -> None:
    added = ["aaaa bbb cccc"]
    suggestion = ["xxxx yyy zzzz"]
    assert _looks_like_modified_apply(added, suggestion) is False


# ---------------------------------------------------------------------------
# commits_scoped_narrowly
# ---------------------------------------------------------------------------


def test_commits_scoped_narrowly_true() -> None:
    commits = [
        {"files": [{"filename": "src/main.py"}]},
    ]
    assert commits_scoped_narrowly(commits, {"file_path": "src/main.py"}) is True


def test_commits_scoped_narrowly_false_touches_other_files() -> None:
    commits = [
        {"files": [{"filename": "src/main.py"}, {"filename": "src/other.py"}]},
    ]
    assert commits_scoped_narrowly(commits, {"file_path": "src/main.py"}) is False


def test_commits_scoped_narrowly_false_empty_commits() -> None:
    assert commits_scoped_narrowly([], {"file_path": "src/main.py"}) is False


def test_commits_scoped_narrowly_ignores_non_list_files() -> None:
    commits = [{"files": "not-a-list"}]
    assert commits_scoped_narrowly(commits, {"file_path": "src/main.py"}) is False


# ---------------------------------------------------------------------------
# seed_pending_finding_outcomes
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_seed_pending_finding_outcomes_creates_rows() -> None:
    installation_id = _random_installation_id()
    await _seed_installation(installation_id)
    review_id = await _seed_review(installation_id, findings=[{}, {}])

    await seed_pending_finding_outcomes(
        review_id=review_id,
        installation_id=installation_id,
        finding_count=2,
        github_comment_ids=[101, 102],
    )

    rows = await list_review_finding_outcomes(review_id, installation_id)
    assert len(rows) == 2
    assert rows[0]["outcome"] == Outcome.PENDING.value
    assert rows[0]["github_comment_id"] == 101
    assert rows[1]["github_comment_id"] == 102


@pytest.mark.anyio
async def test_seed_pending_finding_outcomes_idempotent() -> None:
    installation_id = _random_installation_id()
    await _seed_installation(installation_id)
    review_id = await _seed_review(installation_id, findings=[{}])

    await seed_pending_finding_outcomes(review_id, installation_id, 1, [None])
    await seed_pending_finding_outcomes(review_id, installation_id, 1, [999])

    rows = await list_review_finding_outcomes(review_id, installation_id)
    assert len(rows) == 1
    # Second call should update the comment_id since it was None before
    assert rows[0]["github_comment_id"] == 999


# ---------------------------------------------------------------------------
# classify_finding_outcome — more paths
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_classify_finding_outcome_abandoned_for_closed_unmerged_pr() -> None:
    now = datetime.now(timezone.utc)
    review = SimpleNamespace(id=1, installation_id=1, created_at=now, completed_at=now)
    finding = {
        "file_path": "src/main.py",
        "line_start": 5,
        "line_end": 5,
        "target_line_content": "x = 1",
        "suggestion": None,
    }
    decision = await classify_finding_outcome(
        gh=_FakeGitHubClient(),
        owner="acme",
        repo="repo",
        pr_number=1,
        review=review,
        finding=finding,
        comment_id=None,
        pr_state={"state": "closed", "merged": False},
    )
    assert decision.outcome == Outcome.ABANDONED


@pytest.mark.anyio
async def test_classify_finding_outcome_ignored_merged_no_reactions() -> None:
    now = datetime.now(timezone.utc)
    review = SimpleNamespace(id=2, installation_id=1, created_at=now, completed_at=now)
    finding = {
        "file_path": "src/main.py",
        "line_start": 5,
        "line_end": 5,
        "target_line_content": "print('hi')",
        "suggestion": None,
    }
    decision = await classify_finding_outcome(
        gh=_FakeGitHubClient(),
        owner="acme",
        repo="repo",
        pr_number=1,
        review=review,
        finding=finding,
        comment_id=None,
        pr_state={"state": "closed", "merged": True},
    )
    assert decision.outcome == Outcome.IGNORED


@pytest.mark.anyio
async def test_classify_finding_outcome_dismissed_negative_reaction() -> None:
    class _NegativeClient(_FakeGitHubClient):
        async def get_pull_review_comment_reactions(self, *_a: object, **_k: object) -> list:
            return [{"content": "-1"}]

    now = datetime.now(timezone.utc)
    review = SimpleNamespace(id=3, installation_id=1, created_at=now, completed_at=now)
    finding = {
        "file_path": "src/main.py",
        "line_start": 10,
        "line_end": 10,
        "target_line_content": "value = x",
        "suggestion": None,
    }
    decision = await classify_finding_outcome(
        gh=_NegativeClient(),
        owner="acme",
        repo="repo",
        pr_number=1,
        review=review,
        finding=finding,
        comment_id=555,
        pr_state={"state": "closed", "merged": True},
    )
    assert decision.outcome == Outcome.DISMISSED


@pytest.mark.anyio
async def test_classify_finding_outcome_pending_for_recent_open_pr() -> None:
    now = datetime.now(timezone.utc)
    review = SimpleNamespace(id=4, installation_id=1, created_at=now, completed_at=now)
    finding = {
        "file_path": "src/main.py",
        "line_start": 5,
        "line_end": 5,
        "target_line_content": "api_key = 'secret'",
        "suggestion": None,
    }
    decision = await classify_finding_outcome(
        gh=_FakeGitHubClient(),
        owner="acme",
        repo="repo",
        pr_number=1,
        review=review,
        finding=finding,
        comment_id=None,
        pr_state={"state": "open", "merged": False},
    )
    assert decision.outcome == Outcome.PENDING


@pytest.mark.anyio
async def test_classify_finding_outcome_dismissed_resolved_negative_reply() -> None:
    class _ResolvedNegativeClient(_FakeGitHubClient):
        async def is_pull_review_thread_resolved(self, *_a: object, **_k: object) -> bool:
            return True

        async def get_pull_review_comment_replies(self, *_a: object, **_k: object) -> list:
            return [{"body": "won't fix this"}]

    now = datetime.now(timezone.utc)
    review = SimpleNamespace(id=5, installation_id=1, created_at=now, completed_at=now)
    finding = {
        "file_path": "src/main.py",
        "line_start": 15,
        "line_end": 15,
        "target_line_content": "x = dangerous_call()",
        "suggestion": None,
    }
    decision = await classify_finding_outcome(
        gh=_ResolvedNegativeClient(),
        owner="acme",
        repo="repo",
        pr_number=1,
        review=review,
        finding=finding,
        comment_id=777,
        pr_state={"state": "closed", "merged": True},
    )
    assert decision.outcome == Outcome.DISMISSED


# ---------------------------------------------------------------------------
# detect_suggestion_apply
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_detect_suggestion_apply_empty_suggestion_returns_none() -> None:
    result = await detect_suggestion_apply(
        gh=_FakeGitHubClient(),
        owner="acme",
        repo="repo",
        commits=[],
        suggestion="",
        file_path="src/main.py",
        line_start=1,
        line_end=1,
    )
    assert result == "none"


@pytest.mark.anyio
async def test_detect_suggestion_apply_no_commits_returns_none() -> None:
    result = await detect_suggestion_apply(
        gh=_FakeGitHubClient(),
        owner="acme",
        repo="repo",
        commits=[],
        suggestion="x = encrypt(secret)",
        file_path="src/main.py",
        line_start=1,
        line_end=1,
    )
    assert result == "none"


@pytest.mark.anyio
async def test_detect_suggestion_apply_near_match_returns_near() -> None:

    class _CommitFilesClient(_FakeGitHubClient):
        async def get_commit_files(self, _o: str, _r: str, _sha: str) -> list:
            return [
                {
                    "filename": "src/auth.py",
                    "patch": "+x = encrypt(secret)\n+return x",
                }
            ]

    commits = [{"sha": "abc123", "co_authored_by": None}]
    result = await detect_suggestion_apply(
        gh=_CommitFilesClient(),
        owner="acme",
        repo="repo",
        commits=commits,
        suggestion="x = encrypt(secret)",
        file_path="src/auth.py",
        line_start=1,
        line_end=1,
    )
    assert result == "near"
