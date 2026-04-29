"""Validation helpers for evidence-backed review findings."""

from __future__ import annotations

import re

from app.review.external.models import Finding


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def validate_findings_against_samples(
    findings: list[Finding], sample_by_path: dict[str, str]
) -> tuple[list[Finding], int]:
    """Drop findings that cannot be reproduced from sampled file content."""

    validated: list[Finding] = []
    dropped_count = 0
    for finding in findings:
        sample = sample_by_path.get(finding.file_path)
        if not sample:
            dropped_count += 1
            continue
        lines = sample.splitlines() or [sample]
        end_line = finding.line_end or finding.line_start
        if finding.line_start > len(lines) or end_line > len(lines):
            dropped_count += 1
            continue
        excerpt = finding.evidence.get("excerpt")
        if isinstance(excerpt, str) and len(excerpt) >= 6:
            if _normalize_spaces(excerpt) not in _normalize_spaces(sample):
                dropped_count += 1
                continue
        validated.append(finding)
    return validated, dropped_count
