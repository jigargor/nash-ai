"""Stable finding ids used by delivery markers and outcome tracking."""

from __future__ import annotations

from hashlib import sha1

from app.agent.schema import Finding


def normalize_target_line(content: str) -> str:
    """Collapse whitespace so reindenting a line does not change the finding id."""
    return " ".join(content.split())


def stable_finding_id(finding: Finding) -> str:
    """Content-based id: stable across pushes, list ordering, and line-number shifts.

    Derived from file path + category + normalized target line content only.
    """
    seed = "\x1f".join(
        (
            finding.file_path,
            str(finding.category),
            normalize_target_line(finding.target_line_content or ""),
        )
    )
    return sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()


def assign_finding_ids(findings: list[Finding], *, prefix: str = "f") -> list[Finding]:
    _ = prefix
    updated: list[Finding] = []
    for finding in findings:
        if finding.finding_id:
            updated.append(finding)
            continue
        updated.append(finding.model_copy(update={"finding_id": stable_finding_id(finding)}))
    return updated
