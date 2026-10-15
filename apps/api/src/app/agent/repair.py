"""Anchor repair — re-locate findings whose target line drifted within a window."""

from __future__ import annotations

from app.agent.normalization import normalize_for_match
from app.agent.schema import Finding


def repair_findings_from_files(
    findings: list[Finding],
    fetched_files: dict[str, str],
    *,
    commentable_lines: set[tuple[str, int]] | None,
    window: int,
) -> list[Finding]:
    return [
        repair_finding(
            finding,
            fetched_files,
            commentable_lines=commentable_lines,
            window=window,
        )
        for finding in findings
    ]


def repair_finding(
    finding: Finding,
    fetched_files: dict[str, str],
    *,
    commentable_lines: set[tuple[str, int]] | None,
    window: int,
) -> Finding:
    file_content = fetched_files.get(finding.file_path)
    if file_content is None:
        return finding

    lines = file_content.split("\n")
    start_line = finding.line_start
    end_line = finding.line_end or finding.line_start
    if not (1 <= start_line <= len(lines)):
        return finding

    actual = lines[start_line - 1]
    if normalize_for_match(actual) == normalize_for_match(finding.target_line_content):
        finding.target_line_content = actual
        return finding

    line_span = max(0, end_line - start_line)
    search_start = max(1, start_line - window)
    search_end = min(len(lines), end_line + window)
    matched_line = _find_normalized_line(
        lines, finding.target_line_content, search_start, search_end
    )
    if matched_line is None:
        return finding

    new_end_line = min(len(lines), matched_line + line_span)
    if commentable_lines is not None and not _is_commentable_range(
        finding.file_path, matched_line, new_end_line, commentable_lines
    ):
        return finding

    finding.line_start = matched_line
    finding.line_end = new_end_line
    finding.target_line_content = lines[matched_line - 1]
    return finding


def _find_normalized_line(
    lines: list[str], target_line_content: str, start_line: int, end_line: int
) -> int | None:
    normalized_target = normalize_for_match(target_line_content)
    for line_no in range(start_line, end_line + 1):
        if normalize_for_match(lines[line_no - 1]) == normalized_target:
            return line_no
    return None


def _is_commentable_range(
    path: str,
    start_line: int,
    end_line: int,
    commentable_lines: set[tuple[str, int]],
) -> bool:
    return all((path, line_no) in commentable_lines for line_no in range(start_line, end_line + 1))
