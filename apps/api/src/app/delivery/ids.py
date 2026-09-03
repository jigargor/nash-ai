"""Stable finding ids used by delivery markers and outcome tracking."""

from __future__ import annotations

from hashlib import sha1

from app.agent.schema import Finding


def stable_finding_id(finding: Finding, index: int) -> str:
    seed = f"{finding.file_path}:{finding.line_start}:{finding.category}:{finding.message[:80]}"
    digest = sha1(seed.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    return f"f{index}-{digest}"


def assign_finding_ids(findings: list[Finding], *, prefix: str = "f") -> list[Finding]:
    _ = prefix
    updated: list[Finding] = []
    for index, finding in enumerate(findings):
        if finding.finding_id:
            updated.append(finding)
            continue
        updated.append(finding.model_copy(update={"finding_id": stable_finding_id(finding, index)}))
    return updated
