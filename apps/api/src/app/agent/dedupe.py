from app.agent.normalization import normalize_for_match
from app.agent.schema import Finding

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def finding_dedupe_key(finding: Finding) -> tuple[str, int, str, str, str]:
    line_value = finding.line_end or finding.line_start
    side = finding.side
    normalized_title = normalize_for_match(finding.message[:120])
    normalized_excerpt = normalize_for_match(finding.target_line_content[:240])
    return (
        finding.file_path,
        line_value,
        side,
        normalized_title,
        f"{finding.category}:{normalized_excerpt}",
    )


def dedupe_findings(findings: list[Finding]) -> list[Finding]:
    merged: dict[tuple[str, int, str, str, str], Finding] = {}
    for finding in findings:
        key = finding_dedupe_key(finding)
        existing = merged.get(key)
        if existing is None:
            merged[key] = finding
            continue
        if SEVERITY_RANK[finding.severity] > SEVERITY_RANK[existing.severity]:
            merged[key] = finding
            continue
        if finding.confidence > existing.confidence:
            merged[key] = finding
    return sorted(
        merged.values(),
        key=lambda item: (SEVERITY_RANK[item.severity], item.confidence),
        reverse=True,
    )
