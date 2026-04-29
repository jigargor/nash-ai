from collections import Counter

from sqlalchemy import desc, select

from app.db.models import Review
from app.db.session import AsyncSessionLocal


async def _recent_debug_artifact_rows(
    *,
    limit: int,
    installation_id: int | None = None,
    repo_full_name: str | None = None,
) -> list[tuple[int, object]]:
    async with AsyncSessionLocal() as session:
        query = select(Review.id, Review.debug_artifacts).order_by(desc(Review.id)).limit(limit)
        if installation_id is not None:
            query = query.where(Review.installation_id == installation_id)
        if repo_full_name is not None:
            query = query.where(Review.repo_full_name == repo_full_name)
        return (await session.execute(query)).all()


async def summarize_target_line_mismatch_telemetry(
    *,
    limit: int = 200,
    installation_id: int | None = None,
    repo_full_name: str | None = None,
) -> dict[str, object]:
    """Summarize recent persisted mismatch telemetry for rollout checks."""
    rows = await _recent_debug_artifact_rows(
        limit=limit,
        installation_id=installation_id,
        repo_full_name=repo_full_name,
    )

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


async def summarize_verified_fact_cap_telemetry(
    *,
    limit: int = 200,
    installation_id: int | None = None,
    repo_full_name: str | None = None,
) -> dict[str, object]:
    """Summarize verified_fact cap events persisted in debug artifacts."""
    rows = await _recent_debug_artifact_rows(
        limit=limit,
        installation_id=installation_id,
        repo_full_name=repo_full_name,
    )

    reviews_with_debug_artifacts = 0
    reviews_with_caps = 0
    total_cap_events = 0
    severity_caps = 0
    confidence_caps = 0
    fact_counts: Counter[str] = Counter()
    for _, debug_artifacts in rows:
        if not isinstance(debug_artifacts, dict):
            continue
        reviews_with_debug_artifacts += 1
        raw_caps = debug_artifacts.get("verified_fact_caps")
        if not isinstance(raw_caps, list):
            continue
        reviews_with_caps += 1
        for item in raw_caps:
            if not isinstance(item, dict):
                continue
            total_cap_events += 1
            fact_id = item.get("fact_id")
            if isinstance(fact_id, str) and fact_id.strip():
                fact_counts[fact_id.strip()] += 1
            if "severity_from" in item and "severity_to" in item:
                severity_caps += 1
            if "confidence_from" in item and "confidence_to" in item:
                confidence_caps += 1

    return {
        "review_count": len(rows),
        "reviews_with_debug_artifacts": reviews_with_debug_artifacts,
        "reviews_with_verified_fact_caps": reviews_with_caps,
        "total_verified_fact_cap_events": total_cap_events,
        "severity_caps": severity_caps,
        "confidence_caps": confidence_caps,
        "fact_counts": dict(fact_counts),
    }


async def summarize_verified_fact_retrieval_telemetry(
    *,
    limit: int = 200,
    installation_id: int | None = None,
    repo_full_name: str | None = None,
) -> dict[str, object]:
    """Summarize verified fact retrieval stats captured during prompt assembly."""
    rows = await _recent_debug_artifact_rows(
        limit=limit,
        installation_id=installation_id,
        repo_full_name=repo_full_name,
    )

    reviews_with_debug_artifacts = 0
    reviews_with_retrieval = 0
    total_direct_matches = 0
    total_expanded_matches = 0
    total_selected = 0
    selected_fact_counts: Counter[str] = Counter()
    for _, debug_artifacts in rows:
        if not isinstance(debug_artifacts, dict):
            continue
        reviews_with_debug_artifacts += 1
        retrieval = debug_artifacts.get("verified_fact_retrieval")
        if not isinstance(retrieval, dict):
            continue
        reviews_with_retrieval += 1
        total_direct_matches += int(retrieval.get("direct_match_count", 0) or 0)
        total_expanded_matches += int(retrieval.get("expanded_match_count", 0) or 0)
        total_selected += int(retrieval.get("selected_count", 0) or 0)
        selected_ids = retrieval.get("selected_fact_ids")
        if isinstance(selected_ids, list):
            for fact_id in selected_ids:
                if isinstance(fact_id, str) and fact_id.strip():
                    selected_fact_counts[fact_id.strip()] += 1

    return {
        "review_count": len(rows),
        "reviews_with_debug_artifacts": reviews_with_debug_artifacts,
        "reviews_with_verified_fact_retrieval": reviews_with_retrieval,
        "total_direct_matches": total_direct_matches,
        "total_expanded_matches": total_expanded_matches,
        "total_selected_facts": total_selected,
        "selected_fact_counts": dict(selected_fact_counts),
    }
