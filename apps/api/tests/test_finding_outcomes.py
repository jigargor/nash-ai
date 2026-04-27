from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models import FindingOutcome, Installation, Review
from app.db.session import AsyncSessionLocal, engine, set_installation_context
from app.telemetry.finding_outcomes import (
    Outcome,
    classify_finding_outcome,
    classify_review_outcomes,
    list_review_finding_outcomes,
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
    async def get_pull_review_comment_reactions(self, _owner: str, _repo: str, _comment_id: int | None) -> list[dict[str, object]]:
        return []

    async def get_pull_review_comment_replies(self, _owner: str, _repo: str, _comment_id: int | None) -> list[dict[str, object]]:
        return []

    async def is_pull_review_thread_resolved(self, _owner: str, _repo: str, _pr_number: int, _comment_id: int | None) -> bool:
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
            {"severity": "high", "category": "security", "evidence": "tool_verified", "confidence": 95},
            {"severity": "low", "category": "performance", "evidence": "inference", "confidence": 55},
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

    summary = await summarize_finding_outcomes(installation_id=installation_id, repo_full_name="acme/repo")
    assert summary["total_classified"] == 1
    assert summary["global_metrics"]["useful_rate"] == pytest.approx(1.0)
    assert summary["outcomes"][Outcome.APPLIED_DIRECTLY.value] == 1
    assert "anthropic" in summary["breakdowns"]["provider"]


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
