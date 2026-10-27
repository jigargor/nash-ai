"""Shared validation / policy / filter stage.

Single implementation of the post-generation finding gauntlet used by both
``app.agent.runner`` (legacy path, via the low-level helpers) and
``app.agent.pipeline.review_pipeline`` (via :func:`run_validation_stage`):

    repair -> anchors -> FindingValidator -> policy -> dedupe -> config filters

Every helper is pure (no I/O, no observer calls); callers own logging/telemetry.
Drop accounting uses ``DroppedFinding`` so both paths report identical
``stage:reason`` pairs.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Collection
from dataclasses import dataclass, field
from fnmatch import fnmatch

from app.agent.anchors import attach_anchor_metadata
from app.agent.constants import REPAIR_SEARCH_WINDOW
from app.agent.dedupe import SEVERITY_RANK, dedupe_findings
from app.agent.diff_parser import FileInDiff
from app.agent.policy import apply_policy_filters
from app.agent.repair import repair_findings_from_files
from app.agent.review_config import ReviewConfig
from app.agent.schema import DroppedFinding, DropReason, Finding, ReviewResult
from app.agent.validator import FindingValidator

logger = logging.getLogger(__name__)

RejectedFinding = tuple[Finding, DropReason, str]


@dataclass
class ValidationOutcome:
    """Result of :func:`run_validation_stage`."""

    kept: list[Finding]
    drops: list[DroppedFinding] = field(default_factory=list)

    def drop_keys(self) -> list[str]:
        """``stage:reason`` per drop, in order (stable for golden assertions)."""
        return [f"{d.stage}:{d.reason}" for d in self.drops]


def matches_ignore(path: str, patterns: Collection[str]) -> bool:
    return any(fnmatch(path, pattern) for pattern in patterns)


def repair_and_anchor(
    findings: list[Finding],
    file_contents: dict[str, str],
    files_in_diff: list[FileInDiff],
    *,
    commentable_lines: set[tuple[str, int]] | None,
    window: int = REPAIR_SEARCH_WINDOW,
) -> list[Finding]:
    """Re-anchor drifting line numbers against file content, then attach anchor metadata."""
    repaired = repair_findings_from_files(
        findings,
        file_contents,
        commentable_lines=commentable_lines,
        window=window,
    )
    return attach_anchor_metadata(repaired, files_in_diff)


def validate_with(
    validator: FindingValidator, findings: list[Finding]
) -> tuple[list[Finding], list[RejectedFinding]]:
    """Run ``validator`` over ``findings``; return kept + (finding, reason, detail) rejects.

    ``FindingValidator.validate`` is documented as non-raising; the guard keeps one bad finding
    from aborting the whole review and records it as ``validator_error``.
    """
    kept: list[Finding] = []
    rejected: list[RejectedFinding] = []
    for finding in findings:
        try:
            ok, reason, detail = validator.validate(finding)
        except Exception as exc:
            rejected.append((finding, "validator_error", str(exc)))
            continue
        if ok:
            kept.append(finding)
        else:
            rejected.append((finding, reason or "validator_error", detail or "Unknown validation error"))
    return kept, rejected


def validate_findings(
    findings: list[Finding],
    *,
    file_contents: dict[str, str],
    commentable_lines: set[tuple[str, int]] | None,
) -> tuple[list[Finding], list[DroppedFinding]]:
    validator = FindingValidator(file_contents, commentable_lines=commentable_lines)
    kept, rejected = validate_with(validator, findings)
    drops = [
        DroppedFinding.from_finding(finding, reason=reason, detail=detail, stage="validation")
        for finding, reason, detail in rejected
    ]
    return kept, drops


def apply_config_filters(
    findings: list[Finding], config: ReviewConfig, ignore_paths: list[str]
) -> tuple[list[Finding], list[DroppedFinding]]:
    """Severity threshold, enabled categories, ignored paths, then the per-PR cap."""
    kept: list[Finding] = []
    drops: list[DroppedFinding] = []
    min_rank = SEVERITY_RANK.get(config.severity_threshold, 0)
    for finding in findings:
        if SEVERITY_RANK.get(finding.severity, 0) < min_rank:
            drops.append(
                DroppedFinding.from_finding(
                    finding, reason="below_severity_threshold", stage="policy"
                )
            )
            continue
        if config.categories and finding.category not in config.categories:
            drops.append(
                DroppedFinding.from_finding(finding, reason="category_not_enabled", stage="policy")
            )
            continue
        if ignore_paths and matches_ignore(finding.file_path, ignore_paths):
            drops.append(DroppedFinding.from_finding(finding, reason="ignored_path", stage="policy"))
            continue
        kept.append(finding)
    if len(kept) > config.max_findings_per_pr:
        ranked = sorted(
            kept,
            key=lambda item: (SEVERITY_RANK.get(item.severity, 0), item.confidence),
            reverse=True,
        )
        for extra in ranked[config.max_findings_per_pr :]:
            drops.append(
                DroppedFinding.from_finding(extra, reason="max_findings_per_pr", stage="policy")
            )
        kept = ranked[: config.max_findings_per_pr]
    return kept, drops


def run_validation_stage(
    findings: list[Finding],
    *,
    summary: str,
    file_contents: dict[str, str],
    files_in_diff: list[FileInDiff],
    commentable_lines: set[tuple[str, int]] | None,
    config: ReviewConfig,
    ignore_paths: list[str],
    tool_call_history: list[dict[str, object]],
    known_fact_ids: set[str],
    confidence_threshold: int | None = None,
) -> ValidationOutcome:
    """repair -> anchors -> validate -> policy -> dedupe -> config filters, with drop accounting."""
    anchored = repair_and_anchor(
        list(findings), file_contents, files_in_diff, commentable_lines=commentable_lines
    )
    kept, drops = validate_findings(
        anchored, file_contents=file_contents, commentable_lines=commentable_lines
    )
    policy_result, confidence_dropped, evidence_rejections, _ = apply_policy_filters(
        ReviewResult(findings=kept, summary=summary),
        threshold=(
            confidence_threshold if confidence_threshold is not None else config.confidence_threshold
        ),
        tool_call_history=tool_call_history,
        known_fact_ids=known_fact_ids,
    )
    for item in confidence_dropped:
        drops.append(
            DroppedFinding(
                finding=item if isinstance(item, dict) else None,
                reason="below_confidence_threshold",
                detail=json.dumps(item, default=str),
                stage="policy",
            )
        )
    for rejected_finding, reason in evidence_rejections:
        drops.append(
            DroppedFinding.from_finding(
                rejected_finding, reason="evidence_rejected", detail=reason, stage="policy"
            )
        )
    deduped = dedupe_findings(policy_result.findings)
    if len(deduped) < len(policy_result.findings):
        kept_ids = {id(f) for f in deduped}
        for finding in policy_result.findings:
            if id(finding) not in kept_ids:
                drops.append(DroppedFinding.from_finding(finding, reason="duplicate", stage="dedupe"))
    final_kept, config_drops = apply_config_filters(deduped, config, ignore_paths)
    drops.extend(config_drops)
    return ValidationOutcome(kept=final_kept, drops=drops)


__all__ = [
    "RejectedFinding",
    "ValidationOutcome",
    "apply_config_filters",
    "matches_ignore",
    "repair_and_anchor",
    "run_validation_stage",
    "validate_findings",
    "validate_with",
]
