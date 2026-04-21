from collections import Counter

from sqlalchemy import desc, select

from app.db.models import Review
from app.db.session import AsyncSessionLocal


async def summarize_target_line_mismatch_telemetry(limit: int = 200) -> dict[str, object]:
    """Summarize recent persisted mismatch telemetry for rollout checks."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(Review.id, Review.debug_artifacts).order_by(desc(Review.id)).limit(limit)
            )
        ).all()

    subtype_counts: Counter[str] = Counter()
    total_mismatch = 0
    reviews_with_debug_artifacts = 0
    for _, debug_artifacts in rows:
        if not isinstance(debug_artifacts, dict):
            continue
        reviews_with_debug_artifacts += 1
        subtypes = debug_artifacts.get("target_line_mismatch_subtypes")
        if not isinstance(subtypes, dict):
            continue
        for key, value in subtypes.items():
            if isinstance(value, int):
                subtype_counts[key] += value
                total_mismatch += value

    return {
        "review_count": len(rows),
        "reviews_with_debug_artifacts": reviews_with_debug_artifacts,
        "total_target_line_mismatch_drops": total_mismatch,
        "subtypes": dict(subtype_counts),
    }
