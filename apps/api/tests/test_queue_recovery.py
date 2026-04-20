from datetime import datetime, timedelta, timezone
from random import randint

import pytest

from app.db.models import Installation, Review
from app.db.session import AsyncSessionLocal, set_installation_context
from app.queue.recovery import recover_stale_running_reviews


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
