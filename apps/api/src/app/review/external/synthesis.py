"""Filter, dedupe and rank findings before they leave the engine.

The synthesis stage preserves only findings that are:

* critical or high severity,
* in an allowed category,
* supported by a meaningful excerpt (>= 20 chars) and confidence (>=
  0.8),
* anchored to a concrete file + non-zero starting line.

Duplicates on ``(category, title, file_path, line_start, line_end)``
are collapsed to a single representative finding.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.review.external.models import Finding

_CRITICAL_SEVERITIES: frozenset[str] = frozenset({"critical", "high"})
_ALLOWED_CATEGORIES: frozenset[str] = frozenset(
    {"security", "best-practice", "performance", "correctness"}
)
_MIN_EXCERPT_LEN = 20
_MIN_CONFIDENCE = 0.8


def is_critical(finding: Finding) -> bool:
    """Return ``True`` iff the finding meets the synthesis bar."""

    if finding.severity not in _CRITICAL_SEVERITIES:
        return False
    if finding.category not in _ALLOWED_CATEGORIES:
        return False
    if not finding.file_path.strip():
        return False
    if finding.line_end is not None and finding.line_end < finding.line_start:
        return False
    excerpt = str(finding.evidence.get("excerpt") or "").strip()
    confidence_raw = finding.evidence.get("confidence")
    if isinstance(confidence_raw, bool):
        return False
    confidence = _coerce_confidence(confidence_raw)
    if confidence is None:
        return False
    return len(excerpt) >= _MIN_EXCERPT_LEN and confidence >= _MIN_CONFIDENCE


def _coerce_confidence(value: object) -> float | None:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def dedupe(findings: Iterable[Finding]) -> list[Finding]:
    seen: set[tuple[str, str, str, int, int | None]] = set()
    out: list[Finding] = []
    for finding in findings:
        key = (
            finding.category,
            finding.title.strip().lower(),
            finding.file_path,
            finding.line_start,
            finding.line_end,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


_SEVERITY_RANK: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


def rank(findings: Iterable[Finding]) -> list[Finding]:
    """Sort findings severity-first, then by confidence desc, then path."""

    def sort_key(finding: Finding) -> tuple[int, float, str, int]:
        rank_value = _SEVERITY_RANK.get(finding.severity, 99)
        confidence = _coerce_confidence(finding.evidence.get("confidence")) or 0.0
        return (
            rank_value,
            -confidence,
            finding.file_path,
            finding.line_start,
        )

    return sorted(findings, key=sort_key)


def synthesize(findings: Iterable[Finding]) -> list[Finding]:
    """One-shot helper: filter -> dedupe -> rank."""

    kept = (finding for finding in findings if is_critical(finding))
    return rank(dedupe(kept))
