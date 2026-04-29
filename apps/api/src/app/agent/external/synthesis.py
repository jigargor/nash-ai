"""Compatibility shim for the legacy TypedDict-based synthesis API.

Existing callers pass plain ``dict`` objects through ``is_critical_finding``
and ``dedupe_findings``. We keep that surface and route the logic through
:mod:`app.review.external.synthesis` so both the old and new paths share
identical filtering semantics.
"""

from __future__ import annotations

from typing import TypedDict

from app.review.external.models import Finding


class ExternalCriticalFinding(TypedDict):
    category: str
    severity: str
    title: str
    message: str
    file_path: str | None
    line_start: int | None
    line_end: int | None
    evidence: dict[str, object]


_CRITICAL_SEVERITIES: frozenset[str] = frozenset({"critical", "high"})
_ALLOWED_CATEGORIES: frozenset[str] = frozenset(
    {"security", "best-practice", "performance"}
)


def is_critical_finding(candidate: ExternalCriticalFinding) -> bool:
    """Dict-based predicate preserved from the legacy API."""

    severity = candidate["severity"].strip().lower()
    category = candidate["category"].strip().lower()
    if severity not in _CRITICAL_SEVERITIES:
        return False
    if category not in _ALLOWED_CATEGORIES:
        return False
    file_path = (candidate.get("file_path") or "").strip()
    line_start = candidate.get("line_start")
    line_end = candidate.get("line_end")
    if not file_path:
        return False
    if not isinstance(line_start, int) or line_start <= 0:
        return False
    if line_end is not None and (not isinstance(line_end, int) or line_end < line_start):
        return False
    evidence = candidate.get("evidence", {})
    if not isinstance(evidence, dict):
        return False
    excerpt = str(evidence.get("excerpt") or "").strip()
    confidence_raw = evidence.get("confidence")
    if isinstance(confidence_raw, bool):
        return False
    confidence = 0.0
    if isinstance(confidence_raw, (int, float)):
        confidence = float(confidence_raw)
    elif isinstance(confidence_raw, str):
        try:
            confidence = float(confidence_raw.strip())
        except ValueError:
            return False
    elif confidence_raw is not None:
        return False
    return len(excerpt) >= 20 and confidence >= 0.8


def dedupe_findings(
    findings: list[ExternalCriticalFinding],
) -> list[ExternalCriticalFinding]:
    seen: set[tuple[str, str, str, str | None, int | None, int | None]] = set()
    deduped: list[ExternalCriticalFinding] = []
    for finding in findings:
        key = (
            finding["category"].strip().lower(),
            finding["title"].strip().lower(),
            finding["message"].strip().lower(),
            finding.get("file_path"),
            finding.get("line_start"),
            finding.get("line_end"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def to_finding(candidate: ExternalCriticalFinding) -> Finding:
    """Convert a legacy dict to a Pydantic ``Finding`` (best-effort)."""

    return Finding(
        category=candidate["category"],  # type: ignore[arg-type]
        severity=candidate["severity"],  # type: ignore[arg-type]
        title=candidate["title"],
        message=candidate["message"],
        file_path=str(candidate.get("file_path") or ""),
        line_start=int(candidate.get("line_start") or 1),
        line_end=candidate.get("line_end"),
        evidence=dict(candidate.get("evidence") or {}),
    )


__all__ = [
    "ExternalCriticalFinding",
    "dedupe_findings",
    "is_critical_finding",
    "to_finding",
]
