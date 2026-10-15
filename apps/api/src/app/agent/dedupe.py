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


def near_dedupe_key(finding: Finding) -> tuple[str, str, str]:
    normalized_title = normalize_for_match(finding.message[:80])
    return (finding.file_path, finding.category, normalized_title)


def near_dedupe_findings(findings: list[Finding], *, line_window: int = 2) -> list[Finding]:
    """Collapse findings on the same file+category+message within a small line window."""
    kept: list[Finding] = []
    for finding in findings:
        duplicate = False
        for index, existing in enumerate(kept):
            if near_dedupe_key(existing) != near_dedupe_key(finding):
                continue
            existing_line = existing.line_end or existing.line_start
            finding_line = finding.line_end or finding.line_start
            if abs(existing_line - finding_line) <= line_window:
                duplicate = True
                if SEVERITY_RANK[finding.severity] > SEVERITY_RANK[existing.severity]:
                    kept[index] = finding
                elif (
                    finding.severity == existing.severity
                    and finding.confidence > existing.confidence
                ):
                    kept[index] = finding
                break
        if not duplicate:
            kept.append(finding)
    return kept


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
    exact = list(merged.values())
    near = near_dedupe_findings(exact)
    return sorted(
        near,
        key=lambda item: (SEVERITY_RANK[item.severity], item.confidence),
        reverse=True,
    )
