import logging
from datetime import datetime, timedelta, timezone

from app.db.models import Review
from app.db.session import AsyncSessionLocal, set_installation_context
from sqlalchemy import and_, or_, select

logger = logging.getLogger(__name__)
STALE_RUNNING_REVIEW_MAX_AGE_MINUTES = 10
STALE_QUEUED_REVIEW_MAX_AGE_MINUTES = 30

_RUNNING_RECOVERY_SUMMARY = "Review recovered as failed after worker crash/timeout."
_QUEUED_RECOVERY_SUMMARY = "Review recovered as failed after stale queue timeout."


async def recover_stale_running_reviews(
    max_age_minutes: int = STALE_RUNNING_REVIEW_MAX_AGE_MINUTES,
) -> int:
    stats = await recover_stale_reviews(
        running_max_age_minutes=max_age_minutes,
        recover_queued=False,
    )
    return stats["running_recovered"]


async def recover_stale_reviews(
    *,
    running_max_age_minutes: int = STALE_RUNNING_REVIEW_MAX_AGE_MINUTES,
    recover_queued: bool = False,
    queued_max_age_minutes: int = STALE_QUEUED_REVIEW_MAX_AGE_MINUTES,
) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    running_cutoff = now - timedelta(minutes=running_max_age_minutes)
    queued_cutoff = now - timedelta(minutes=queued_max_age_minutes)
    running_recovered = 0
    queued_recovered = 0

    running_clause = and_(
        Review.status == "running",
        or_(
            and_(Review.started_at.is_not(None), Review.started_at < running_cutoff),
            and_(Review.started_at.is_(None), Review.created_at < running_cutoff),
        ),
    )
    queued_clause = and_(
        Review.status == "queued",
        Review.started_at.is_(None),
        Review.created_at < queued_cutoff,
    )
    selection_clause = or_(running_clause, queued_clause) if recover_queued else running_clause

    async with AsyncSessionLocal() as session:
        installation_ids = list(
            await session.scalars(select(Review.installation_id).where(selection_clause).distinct())
        )
        for installation_id in installation_ids:
            await set_installation_context(session, int(installation_id))
            rows = list(
                await session.scalars(
                    select(Review)
                    .where(Review.installation_id == int(installation_id))
                    .where(selection_clause)
                )
            )
            for review in rows:
                reason = "stale_running"
                summary = _RUNNING_RECOVERY_SUMMARY
                if review.status == "queued":
                    reason = "stale_queued"
                    summary = _QUEUED_RECOVERY_SUMMARY
                    queued_recovered += 1
                else:
                    running_recovered += 1
                review.status = "failed"
                review.completed_at = now
                review.findings = {"findings": [], "summary": summary}
                existing_artifacts = dict(review.debug_artifacts or {})
                existing_artifacts["recovery"] = {
                    "reason": reason,
                    "recovered_at": now.isoformat(),
                    "running_max_age_minutes": running_max_age_minutes,
                    "queued_max_age_minutes": queued_max_age_minutes if recover_queued else None,
                }
                review.debug_artifacts = existing_artifacts
        await session.commit()

    recovered = running_recovered + queued_recovered
    if recovered:
        logger.warning(
            "Recovered stale reviews recovered=%s running=%s queued=%s running_max_age_minutes=%s queued_max_age_minutes=%s recover_queued=%s",
            recovered,
            running_recovered,
            queued_recovered,
            running_max_age_minutes,
            queued_max_age_minutes,
            recover_queued,
        )
    return {
        "running_recovered": running_recovered,
        "queued_recovered": queued_recovered,
        "total_recovered": recovered,
    }
