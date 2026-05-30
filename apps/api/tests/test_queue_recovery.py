from datetime import datetime, timedelta, timezone
from random import randint

import pytest

from app.db.models import Installation, Review
from app.db.session import AsyncSessionLocal, set_installation_context
from app.queue.recovery import recover_stale_reviews, recover_stale_running_reviews


@pytest.mark.anyio
async def test_recover_stale_running_reviews_marks_only_stale_rows_failed() -> None:
    installation_id = randint(10_000_000, 99_999_999)
    now = datetime.now(timezone.utc)
    stale_started_at = now - timedelta(minutes=20)
    fresh_started_at = now - timedelta(minutes=3)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            Installation(
                installation_id=installation_id,
                account_login=f"acme-{installation_id}",
                account_type="Organization",
            )
        )
        stale_review = Review(
            installation_id=installation_id,
            repo_full_name="acme/repo",
            pr_number=1,
            pr_head_sha="c" * 40,
            model="claude-sonnet-4-5",
            status="running",
            started_at=stale_started_at,
        )
        fresh_review = Review(
            installation_id=installation_id,
            repo_full_name="acme/repo",
            pr_number=2,
            pr_head_sha="d" * 40,
            model="claude-sonnet-4-5",
            status="running",
            started_at=fresh_started_at,
        )
        session.add_all([stale_review, fresh_review])
        await session.commit()
        stale_review_id = stale_review.id
        fresh_review_id = fresh_review.id

    recovered = await recover_stale_running_reviews(max_age_minutes=10)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        stale_review = await session.get(Review, stale_review_id)
        fresh_review = await session.get(Review, fresh_review_id)

    assert recovered >= 1
    assert stale_review is not None
    assert stale_review.status == "failed"
    assert isinstance(stale_review.findings, dict)
    assert "recovered as failed" in str(stale_review.findings.get("summary"))
    assert stale_review.completed_at is not None

    assert fresh_review is not None
    assert fresh_review.status == "running"


@pytest.mark.anyio
async def test_recover_stale_reviews_can_recover_stale_queued_rows() -> None:
    installation_id = randint(10_000_000, 99_999_999)
    now = datetime.now(timezone.utc)
    stale_created_at = now - timedelta(minutes=45)
    fresh_created_at = now - timedelta(minutes=2)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            Installation(
                installation_id=installation_id,
                account_login=f"queued-{installation_id}",
                account_type="Organization",
            )
        )
        stale_queued_review = Review(
            installation_id=installation_id,
            repo_full_name="acme/repo",
            pr_number=31,
            pr_head_sha="e" * 40,
            model="claude-sonnet-4-5",
            status="queued",
            created_at=stale_created_at,
        )
        fresh_queued_review = Review(
            installation_id=installation_id,
            repo_full_name="acme/repo",
            pr_number=32,
            pr_head_sha="f" * 40,
            model="claude-sonnet-4-5",
            status="queued",
            created_at=fresh_created_at,
        )
        session.add_all([stale_queued_review, fresh_queued_review])
        await session.commit()
        stale_queued_review_id = stale_queued_review.id
        fresh_queued_review_id = fresh_queued_review.id

    stats = await recover_stale_reviews(
        running_max_age_minutes=10,
        recover_queued=True,
        queued_max_age_minutes=30,
    )

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        stale_queued_review = await session.get(Review, stale_queued_review_id)
        fresh_queued_review = await session.get(Review, fresh_queued_review_id)

    assert stats["queued_recovered"] >= 1
    assert stale_queued_review is not None
    assert stale_queued_review.status == "failed"
    assert isinstance(stale_queued_review.findings, dict)
    assert "stale queue timeout" in str(stale_queued_review.findings.get("summary"))
    assert stale_queued_review.completed_at is not None

    assert fresh_queued_review is not None
    assert fresh_queued_review.status == "queued"


@pytest.mark.anyio
async def test_recover_stale_reviews_running_without_started_at_uses_created_at() -> None:
    installation_id = randint(10_000_000, 99_999_999)
    now = datetime.now(timezone.utc)
    stale_created_at = now - timedelta(minutes=25)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        session.add(
            Installation(
                installation_id=installation_id,
                account_login=f"running-{installation_id}",
                account_type="Organization",
            )
        )
        stale_running_review = Review(
            installation_id=installation_id,
            repo_full_name="acme/repo",
            pr_number=41,
            pr_head_sha="g" * 40,
            model="claude-sonnet-4-5",
            status="running",
            started_at=None,
            created_at=stale_created_at,
        )
        session.add(stale_running_review)
        await session.commit()
        stale_running_review_id = stale_running_review.id

    stats = await recover_stale_reviews(running_max_age_minutes=10, recover_queued=False)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        stale_running_review = await session.get(Review, stale_running_review_id)

    assert stats["running_recovered"] >= 1
    assert stale_running_review is not None
    assert stale_running_review.status == "failed"
