"""Supersession of older queued/running reviews when a PR gets a new head SHA."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.webhooks.handlers import SUPERSEDED_REVIEW_STATUS, supersede_older_reviews

_OLD_SHA = "a" * 40
_NEW_SHA = "b" * 40


class _FakeScalarResult:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def all(self) -> list[SimpleNamespace]:
        return list(self._rows)


class _FakeSession:
    """Returns the rows a real query (older head, queued/running) would match."""

    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows
        self.statements: list[str] = []

    async def scalars(self, statement: object) -> _FakeScalarResult:
        self.statements.append(str(statement))
        return _FakeScalarResult(self._rows)


def _review(review_id: int, status: str, head_sha: str = _OLD_SHA) -> SimpleNamespace:
    return SimpleNamespace(
        id=review_id,
        status=status,
        pr_head_sha=head_sha,
        completed_at=None,
        findings=None,
        debug_artifacts=None,
    )


@pytest.mark.anyio
async def test_supersede_older_reviews_marks_queued_and_running_as_superseded() -> None:
    queued = _review(1, "queued")
    running = _review(2, "running", head_sha="c" * 40)
    session = _FakeSession([queued, running])

    superseded_ids = await supersede_older_reviews(
        session,  # type: ignore[arg-type]
        installation_id=7,
        repo_full_name="acme/repo",
        pr_number=3,
        head_sha=_NEW_SHA,
    )

    assert superseded_ids == [1, 2]
    for review in (queued, running):
        assert review.status == SUPERSEDED_REVIEW_STATUS
        assert review.completed_at is not None
        assert review.findings is not None
        assert review.findings["findings"] == []
        assert _NEW_SHA[:7] in review.findings["summary"]
        assert review.debug_artifacts == {"superseded_by_head_sha": _NEW_SHA}


@pytest.mark.anyio
async def test_supersede_older_reviews_query_scopes_to_pr_older_heads_and_active_status() -> None:
    session = _FakeSession([])

    superseded_ids = await supersede_older_reviews(
        session,  # type: ignore[arg-type]
        installation_id=7,
        repo_full_name="acme/repo",
        pr_number=3,
        head_sha=_NEW_SHA,
    )

    assert superseded_ids == []
    assert len(session.statements) == 1
    sql = session.statements[0].lower()
    for column in ("installation_id", "repo_full_name", "pr_number", "pr_head_sha", "status"):
        assert column in sql
    assert "!=" in sql or "<>" in sql
    assert " in (" in sql


@pytest.mark.anyio
async def test_supersede_older_reviews_preserves_existing_debug_artifacts() -> None:
    queued = _review(5, "queued")
    queued.debug_artifacts = {"check_run_id": 99}
    session = _FakeSession([queued])

    await supersede_older_reviews(
        session,  # type: ignore[arg-type]
        installation_id=7,
        repo_full_name="acme/repo",
        pr_number=3,
        head_sha=_NEW_SHA,
    )

    assert queued.debug_artifacts == {"check_run_id": 99, "superseded_by_head_sha": _NEW_SHA}
