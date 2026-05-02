"""Confidence calibration scorecard computation.

Computes per-bucket and per-dimension calibration scorecards from
FindingOutcome + Review data, referencing the targets defined in
docs/quality-model.md.

Calibration targets (from quality-model.md §5):
    95-100  → expected TP/useful rate ≥ 0.90
    80-94   → expected TP/useful rate ≥ 0.75
    60-79   → expected TP/useful rate ≥ 0.55
    40-59   → expected TP/useful rate ≥ 0.40  (critical-only submissions)
    0-39    → below posting threshold; no target (findings should not be posted)

Builds on summarize_finding_outcomes() for data access; does NOT
duplicate its DB query logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db.models import FindingOutcome, Review
from app.db.session import AsyncSessionLocal, set_installation_context
from app.telemetry.finding_outcomes import Outcome, _coerce_int, _confidence_bucket
from sqlalchemy import select

# ── Quality-model calibration targets ─────────────────────────────────────────

BUCKET_EXPECTED_USEFUL_RATE: dict[str, float] = {
    "95-100": 0.90,
    "80-94": 0.75,
    "60-79": 0.55,
    "40-59": 0.40,
    "0-39": 0.00,  # should never be posted
}

BUCKET_ORDER = ["95-100", "80-94", "60-79", "40-59", "0-39"]

USEFUL_OUTCOMES = frozenset(
    {Outcome.APPLIED_DIRECTLY.value, Outcome.APPLIED_MODIFIED.value, Outcome.ACKNOWLEDGED.value}
)
DISMISSED_OUTCOMES = frozenset({Outcome.DISMISSED.value})
IGNORED_OUTCOMES = frozenset({Outcome.IGNORED.value})


# ── Public dataclasses ─────────────────────────────────────────────────────────


@dataclass
class CalibrationBucket:
    """Calibration metrics for a single confidence bucket."""

    bucket_range: str  # "95-100", "80-94", "60-79", "40-59", "0-39"
    total_findings: int
    useful_count: int  # applied_directly + applied_modified + acknowledged
    dismissed_count: int
    ignored_count: int
    useful_rate: float
    expected_rate: float  # target from quality-model.md
    calibration_gap: float  # actual useful_rate − expected_rate (negative = under-performing)


@dataclass
class CalibrationScorecard:
    """Full calibration scorecard for a filtered slice of finding outcomes."""

    dimensions: dict[str, str]  # active filter dimensions, e.g. {"category": "security"}
    buckets: list[CalibrationBucket]
    total_findings: int
    overall_useful_rate: float
    cost_per_useful_usd: float | None  # None when cost data is unavailable


# ── Internal accumulator ───────────────────────────────────────────────────────


@dataclass
class _BucketAccum:
    total: int = 0
    useful: int = 0
    dismissed: int = 0
    ignored: int = 0


# ── DB query helpers ───────────────────────────────────────────────────────────


async def _load_rows(
    *,
    installation_id: int | None,
    repo_full_name: str | None,
) -> list[tuple[FindingOutcome, Review]]:
    """Load (FindingOutcome, Review) pairs, scoped to installation when provided."""
    rows: list[tuple[FindingOutcome, Review]] = []

    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
            stmt = (
                select(FindingOutcome, Review)
                .join(Review, Review.id == FindingOutcome.review_id)
                .where(Review.installation_id == installation_id)
            )
            if repo_full_name:
                stmt = stmt.where(Review.repo_full_name == repo_full_name)
            rows = list((await session.execute(stmt)).tuples().all())
        else:
            installation_rows = await session.scalars(select(Review.installation_id).distinct())
            installation_ids = [int(item) for item in installation_rows]
            for iid in installation_ids:
                await set_installation_context(session, iid)
                stmt = (
                    select(FindingOutcome, Review)
                    .join(Review, Review.id == FindingOutcome.review_id)
                    .where(Review.installation_id == iid)
                )
                if repo_full_name:
                    stmt = stmt.where(Review.repo_full_name == repo_full_name)
                rows.extend((await session.execute(stmt)).tuples().all())

    return rows


def _extract_finding(review: Review, finding_index: int) -> dict[str, object]:
    findings_payload = review.findings if isinstance(review.findings, dict) else {}
    findings = findings_payload.get("findings")
    if not isinstance(findings, list) or finding_index < 0 or finding_index >= len(findings):
        return {}
    finding = findings[finding_index]
    if not isinstance(finding, dict):
        return {}
    return finding


# ── Scorecard computation ──────────────────────────────────────────────────────


def _matches_filters(
    finding: dict[str, object],
    review: Review,
    *,
    provider: str | None,
    model: str | None,
    category: str | None,
    severity: str | None,
    prompt_version: str | None,
) -> bool:
    if provider and str(review.model_provider) != provider:
        return False
    if model and review.model != model:
        return False
    if category and str(finding.get("category", "")) != category:
        return False
    if severity and str(finding.get("severity", "")) != severity:
        return False
    if prompt_version:
        pv = str((review.debug_artifacts or {}).get("prompt_version", ""))
        if pv != prompt_version:
            return False
    return True


async def compute_calibration_scorecard(
    *,
    installation_id: int | None = None,
    repo_full_name: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    prompt_version: str | None = None,
) -> CalibrationScorecard:
    """Compute a calibration scorecard with multi-dimensional filtering.

    The scorecard shows, for each confidence bucket, how the observed
    useful rate compares to the target defined in quality-model.md.

    Cost per useful finding is derived from Review.cost_usd when available.
    Findings with outcome=PENDING are excluded (not yet classifiable).
    """
    rows = await _load_rows(
        installation_id=installation_id,
        repo_full_name=repo_full_name,
    )

    accums: dict[str, _BucketAccum] = {b: _BucketAccum() for b in BUCKET_ORDER}
    total_cost_usd: float = 0.0
    seen_review_ids: set[int] = set()

    for outcome_row, review in rows:
        if outcome_row.outcome == Outcome.PENDING.value:
            continue

        finding = _extract_finding(review, int(outcome_row.finding_index))
        if not _matches_filters(
            finding,
            review,
            provider=provider,
            model=model,
            category=category,
            severity=severity,
            prompt_version=prompt_version,
        ):
            continue

        confidence = _coerce_int(finding.get("confidence"), 0)
        bucket = _confidence_bucket(confidence)
        acc = accums[bucket]
        acc.total += 1

        outcome = outcome_row.outcome
        if outcome in USEFUL_OUTCOMES:
            acc.useful += 1
        elif outcome in DISMISSED_OUTCOMES:
            acc.dismissed += 1
        elif outcome in IGNORED_OUTCOMES:
            acc.ignored += 1

        # Accumulate review cost once per review (not per finding)
        rid = int(review.id)
        if rid not in seen_review_ids and review.cost_usd is not None:
            total_cost_usd += float(review.cost_usd)
            seen_review_ids.add(rid)

    # Build bucket list
    buckets: list[CalibrationBucket] = []
    grand_total = 0
    grand_useful = 0

    for bucket_range in BUCKET_ORDER:
        acc = accums[bucket_range]
        useful_rate = acc.useful / acc.total if acc.total else 0.0
        expected_rate = BUCKET_EXPECTED_USEFUL_RATE[bucket_range]
        buckets.append(
            CalibrationBucket(
                bucket_range=bucket_range,
                total_findings=acc.total,
                useful_count=acc.useful,
                dismissed_count=acc.dismissed,
                ignored_count=acc.ignored,
                useful_rate=useful_rate,
                expected_rate=expected_rate,
                calibration_gap=useful_rate - expected_rate,
            )
        )
        grand_total += acc.total
        grand_useful += acc.useful

    overall_useful_rate = grand_useful / grand_total if grand_total else 0.0
    cost_per_useful = total_cost_usd / grand_useful if grand_useful > 0 else None

    dimensions: dict[str, str] = {}
    if installation_id is not None:
        dimensions["installation_id"] = str(installation_id)
    if repo_full_name:
        dimensions["repo"] = repo_full_name
    if provider:
        dimensions["provider"] = provider
    if model:
        dimensions["model"] = model
    if category:
        dimensions["category"] = category
    if severity:
        dimensions["severity"] = severity
    if prompt_version:
        dimensions["prompt_version"] = prompt_version

    return CalibrationScorecard(
        dimensions=dimensions,
        buckets=buckets,
        total_findings=grand_total,
        overall_useful_rate=overall_useful_rate,
        cost_per_useful_usd=cost_per_useful,
    )
