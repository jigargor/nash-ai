"""Confidence threshold recommendations from calibration data.

Consumes CalibrationScorecard data to recommend per-(category, severity)
confidence thresholds.  The recommender identifies the lowest bucket where
the observed useful_rate meets the quality-model target, and recommends the
bottom of that bucket as the minimum posting threshold.

Design decisions:
- Operates purely on calibration data; no direct DB access (delegates to
  compute_calibration_scorecard).
- Computes one recommendation per (category, severity) pair for which
  sufficient sample data exists.
- `min_samples` guards against noise from low-volume slices.
- The default threshold (60) matches the quality-model minimum posting
  confidence for non-critical findings.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.categories import CanonicalCategory
from app.telemetry.calibration import (
    CalibrationBucket,
    compute_calibration_scorecard,
)

# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_THRESHOLD = 60  # quality-model: ≥60 confidence to post (non-critical)
CRITICAL_DEFAULT_THRESHOLD = 40  # quality-model: critical may post at ≥40

# Bottom-of-bucket values: the minimum confidence a finding must have to
# belong to that bucket.
BUCKET_FLOOR: dict[str, int] = {
    "95-100": 95,
    "80-94": 80,
    "60-79": 60,
    "40-59": 40,
    "0-39": 0,
}

SEVERITY_LEVELS = ("critical", "high", "medium", "low")
CANONICAL_CATEGORIES: tuple[CanonicalCategory, ...] = (
    "security",
    "performance",
    "correctness",
    "style",
    "maintainability",
    "best-practice",
)


# ── Public dataclass ───────────────────────────────────────────────────────────


@dataclass
class ThresholdRecommendation:
    """Recommended confidence threshold for a (category, severity) pair."""

    category: str
    severity: str
    current_threshold: int  # current policy minimum from quality-model.md
    recommended_threshold: int  # recommended minimum based on calibration data
    basis: str  # human-readable explanation of why this threshold was chosen
    sample_size: int  # total classified findings in this slice


# ── Helper ─────────────────────────────────────────────────────────────────────


def _current_threshold(severity: str) -> int:
    """Return the policy-specified minimum confidence for a severity level."""
    return CRITICAL_DEFAULT_THRESHOLD if severity == "critical" else DEFAULT_THRESHOLD


def _recommend_from_buckets(
    buckets: list[CalibrationBucket],
    severity: str,
    sample_size: int,
) -> ThresholdRecommendation | None:
    """Derive a threshold recommendation from a list of calibration buckets.

    Strategy: walk buckets from highest to lowest confidence.  The recommended
    threshold is the floor of the lowest bucket where the observed useful_rate
    meets (or exceeds) its expected target.  If no bucket meets the target,
    recommend raising the threshold to the highest-confidence bucket floor.
    """
    current = _current_threshold(severity)

    # Buckets ordered high→low; find lowest bucket that passes calibration
    passing_floor: int | None = None
    failing_buckets: list[str] = []

    for bucket in buckets:
        if bucket.total_findings == 0:
            continue
        if bucket.useful_rate >= bucket.expected_rate:
            passing_floor = BUCKET_FLOOR[bucket.bucket_range]
        else:
            failing_buckets.append(bucket.bucket_range)

    if passing_floor is None:
        # No bucket passes — recommend the highest bucket floor to tighten
        recommended = BUCKET_FLOOR["95-100"]
        basis = (
            f"No confidence bucket meets its useful-rate target "
            f"(failing: {', '.join(failing_buckets)}). "
            f"Recommend raising threshold to {recommended} to reduce noise."
        )
    elif failing_buckets:
        # Some buckets pass, some fail — recommend floor of the lowest passing bucket
        recommended = passing_floor
        basis = (
            f"Buckets {', '.join(failing_buckets)} under-perform their useful-rate targets. "
            f"Setting threshold to {recommended} keeps only calibrated findings."
        )
    else:
        # All buckets pass — threshold can remain at current or lower
        recommended = current
        basis = (
            f"All confidence buckets meet their useful-rate targets. "
            f"Current threshold ({current}) is sufficient."
        )

    return ThresholdRecommendation(
        category="",  # filled by caller
        severity=severity,
        current_threshold=current,
        recommended_threshold=recommended,
        basis=basis,
        sample_size=sample_size,
    )


# ── Public API ─────────────────────────────────────────────────────────────────


async def generate_threshold_recommendations(
    *,
    installation_id: int | None = None,
    min_samples: int = 50,
) -> list[ThresholdRecommendation]:
    """Generate per-(category, severity) confidence threshold recommendations.

    For each (category, severity) combination with at least `min_samples`
    classified findings, computes a calibration scorecard and derives a
    recommended minimum posting threshold.

    Args:
        installation_id: Scope to a specific installation.  None = global.
        min_samples: Minimum number of classified findings required before a
            recommendation is emitted for a slice.  Slices with fewer findings
            are skipped to avoid noise from low-volume data.

    Returns:
        List of ThresholdRecommendation, one per (category, severity) slice
        that has sufficient data.  Empty list when no slice meets min_samples.
    """
    recommendations: list[ThresholdRecommendation] = []

    for category in CANONICAL_CATEGORIES:
        for severity in SEVERITY_LEVELS:
            scorecard = await compute_calibration_scorecard(
                installation_id=installation_id,
                category=category,
                severity=severity,
            )

            if scorecard.total_findings < min_samples:
                continue

            rec = _recommend_from_buckets(
                buckets=scorecard.buckets,
                severity=severity,
                sample_size=scorecard.total_findings,
            )
            if rec is None:
                continue

            rec.category = category
            recommendations.append(rec)

    return recommendations
