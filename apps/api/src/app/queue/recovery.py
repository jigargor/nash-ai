from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import select, update

from app.db.models import Review
from app.db.session import AsyncSessionLocal, set_installation_context

logger = logging.getLogger(__name__)
STALE_RUNNING_REVIEW_MAX_AGE_MINUTES = 10


async def recover_stale_running_reviews(max_age_minutes: int = STALE_RUNNING_REVIEW_MAX_AGE_MINUTES) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    recovered = 0

    async with AsyncSessionLocal() as session:
        installation_ids = await session.scalars(
            select(Review.installation_id)
            .where(Review.status == "running")
            .where(Review.started_at.is_not(None))
            .where(Review.started_at < cutoff)
            .distinct()
        )
        for installation_id in installation_ids:
            await set_installation_context(session, int(installation_id))
            result = await session.execute(
                update(Review)
                .where(Review.installation_id == installation_id)
                .where(Review.status == "running")
                .where(Review.started_at.is_not(None))
                .where(Review.started_at < cutoff)
                .values(
                    status="failed",
                    completed_at=datetime.now(timezone.utc),
                    findings={
                        "findings": [],
                        "summary": "Review recovered as failed after worker crash/timeout.",
                    },
                )
            )
            recovered += int(result.rowcount or 0)
        await session.commit()

    if recovered:
        logger.warning("Recovered stale running reviews count=%s max_age_minutes=%s", recovered, max_age_minutes)
    return recovered
