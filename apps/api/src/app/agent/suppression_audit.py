from __future__ import annotations

from hashlib import sha256

from app.agent.consistency_probe_schema import (
    DeterministicSuppression,
    ProbeCandidate,
    ProbeReasonCode,
    SuppressionAudit,
)
from app.agent.schema import EditedReview, Finding, ReviewResult

_HIGH_RISK = {"high", "critical"}


def candidate_summary_hash(finding: Finding) -> str:
    """Stable, compact fingerprint for finding identity across stages."""
    raw = (
        f"{finding.file_path}:{finding.line_start}:{finding.severity}:"
        f"{finding.message.lower().strip()}"
    )
    return sha256(raw.encode("utf-8")).hexdigest()[:16]


def to_probe_candidate(finding: Finding) -> ProbeCandidate:
    return ProbeCandidate(
        candidate_id=candidate_summary_hash(finding),
        title=finding.message,
        severity=finding.severity,
        category=finding.category,
        path=finding.file_path,
        line_start=finding.line_start,
        line_end=finding.line_end,
        evidence=finding.evidence,
        evidence_fact_id=finding.evidence_fact_id,
        summary_hash=candidate_summary_hash(finding),
    )


def run_suppression_audit(
    draft_result: ReviewResult,
    edited_result: EditedReview,
    *,
    high_critical_only: bool,
) -> SuppressionAudit:
    final_by_hash = {candidate_summary_hash(f): f for f in edited_result.findings}
    final_by_path_line: dict[tuple[str, int], list[Finding]] = {}
    for finding in edited_result.findings:
        final_by_path_line.setdefault((finding.file_path, finding.line_start), []).append(finding)

    suppressed: list[DeterministicSuppression] = []
    unresolved_high_risk: list[DeterministicSuppression] = []
    for index, draft in enumerate(draft_result.findings):
        if high_critical_only and draft.severity not in _HIGH_RISK:
            continue
        candidate = to_probe_candidate(draft)
        reason_code, reason_text = _classify_suppression(
            draft=draft,
            index=index,
            edited_result=edited_result,
            final_by_hash=final_by_hash,
            final_by_path_line=final_by_path_line,
        )
        if reason_code is None:
            continue
        unresolved = bool(
            draft.severity in _HIGH_RISK
            and reason_code
            in {
                "missing_from_final",
                "severity_downgraded_without_evidence",
                "deduplicated_into_weaker_finding",
            }
        )
        item = DeterministicSuppression(
            candidate=candidate,
            reason_code=reason_code,
            deterministic_reason=reason_text,
            unresolved=unresolved,
        )
        suppressed.append(item)
        if unresolved:
            unresolved_high_risk.append(item)

    return SuppressionAudit(
        draft_count=len(draft_result.findings),
        final_count=len(edited_result.findings),
        suppressed=suppressed,
        unresolved_high_risk=unresolved_high_risk,
    )


def _classify_suppression(
    *,
    draft: Finding,
    index: int,
    edited_result: EditedReview,
    final_by_hash: dict[str, Finding],
    final_by_path_line: dict[tuple[str, int], list[Finding]],
) -> tuple[ProbeReasonCode | None, str]:
    draft_hash = candidate_summary_hash(draft)
    if draft_hash in final_by_hash:
        final = final_by_hash[draft_hash]
        if _severity_rank(final.severity) < _severity_rank(draft.severity):
            return (
                "severity_downgraded_without_evidence",
                "Matched finding kept but downgraded severity.",
            )
        return None, ""

    related = final_by_path_line.get((draft.file_path, draft.line_start), [])
    if related:
        has_weaker = any(
            _severity_rank(item.severity) < _severity_rank(draft.severity) for item in related
        )
        if has_weaker:
            return (
                "severity_downgraded_without_evidence",
                "No exact match in final findings; same anchor reappeared at weaker severity.",
            )
        return (
            "deduplicated_into_weaker_finding",
            "Draft finding disappeared while same anchor remains with altered message.",
        )

    if index < len(edited_result.decisions):
        decision = edited_result.decisions[index]
        if decision.action == "drop":
            reason = (decision.reason or "").lower()
            if "duplicate" in reason or "dedup" in reason:
                return (
                    "deduplicated_into_weaker_finding",
                    f"Editor dropped finding as duplicate: {decision.reason or 'duplicate'}",
                )
            if "anchor" in reason or "line" in reason:
                return (
                    "editor_removed_anchor",
                    f"Editor dropped finding due to anchor mismatch: {decision.reason or 'anchor mismatch'}",
                )
            return (
                "missing_from_final",
                f"Editor dropped finding: {decision.reason or 'no reason provided'}",
            )

    return "missing_from_final", "Draft finding is absent from final output."


def _severity_rank(severity: str) -> int:
    return {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(severity, -1)

