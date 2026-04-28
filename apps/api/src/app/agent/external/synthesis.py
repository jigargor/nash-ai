from __future__ import annotations

from typing import TypedDict


class ExternalCriticalFinding(TypedDict):
    category: str
    severity: str
    title: str
    message: str
    file_path: str | None
    line_start: int | None
    line_end: int | None
    evidence: dict[str, object]


_CRITICAL_SEVERITIES = {"critical", "high"}
_ALLOWED_CATEGORIES = {"security", "best-practice", "performance"}


def is_critical_finding(candidate: ExternalCriticalFinding) -> bool:
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
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    # Require meaningful supporting signal.
    return len(excerpt) >= 20 and confidence >= 0.8


def dedupe_findings(findings: list[ExternalCriticalFinding]) -> list[ExternalCriticalFinding]:
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

