"""Policy filters extracted from the runner (confidence, vendor, evidence)."""

from __future__ import annotations

from collections import Counter

from app.agent.schema import Finding, ReviewResult
from app.agent.vendor_detect import auto_tag_vendor_claims


INFERENCE_CONFIDENCE_CAP = 75
"""Schema cap: ``evidence='inference'`` findings can never exceed this confidence."""

INFERENCE_CONFIDENCE_FLOOR = 50
"""Separate floor for inference findings, which can never reach the default 85 threshold."""

_INFERENCE_ELIGIBLE_SEVERITIES = frozenset({"low", "medium"})


def effective_confidence_threshold(finding: Finding, threshold: int) -> int:
    """Evidence-aware threshold.

    Inference findings are capped at confidence 75 by the schema, so a global threshold above 75
    would silently delete the whole tier. Medium/low inference findings use a separate floor;
    every other evidence tier uses ``threshold`` unchanged.
    """
    if (
        finding.evidence == "inference"
        and finding.severity in _INFERENCE_ELIGIBLE_SEVERITIES
        and finding.confidence <= INFERENCE_CONFIDENCE_CAP
    ):
        return min(threshold, INFERENCE_CONFIDENCE_FLOOR)
    return threshold


def apply_confidence_threshold(
    result: ReviewResult, threshold: int
) -> tuple[ReviewResult, list[dict[str, object]]]:
    kept_findings: list[Finding] = []
    dropped: list[dict[str, object]] = []
    for finding in result.findings:
        effective_threshold = effective_confidence_threshold(finding, threshold)
        if finding.confidence >= effective_threshold:
            kept_findings.append(finding)
            continue
        dropped.append(
            {
                "file_path": finding.file_path,
                "line_start": finding.line_start,
                "line_end": finding.line_end or finding.line_start,
                "confidence": finding.confidence,
                "threshold": effective_threshold,
                "evidence": finding.evidence,
                "message_excerpt": finding.message[:120],
            }
        )
    result.findings = kept_findings
    return result, dropped


def cross_check_tool_evidence(
    findings: list[Finding],
    tool_call_history: list[dict[str, object]],
) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    actual_tool_names = {
        str(call.get("name")) for call in tool_call_history if isinstance(call.get("name"), str)
    }
    actual_tool_signatures = {
        f"{call.get('name')}:{_stable_tool_input_repr(call.get('input'))}"
        for call in tool_call_history
        if isinstance(call.get("name"), str)
    }

    accepted: list[Finding] = []
    rejected: list[tuple[Finding, str]] = []
    for finding in findings:
        if finding.evidence != "tool_verified":
            accepted.append(finding)
            continue
        claimed_calls = set(finding.evidence_tool_calls or [])
        if not claimed_calls:
            rejected.append((finding, "missing claimed tool calls"))
            continue
        missing = {
            claim
            for claim in claimed_calls
            if claim not in actual_tool_names and claim not in actual_tool_signatures
        }
        if missing:
            rejected.append((finding, f"claimed tool calls not in history: {sorted(missing)}"))
            continue
        accepted.append(finding)
    return accepted, rejected


def cross_check_fact_ids(
    findings: list[Finding],
    known_fact_ids: set[str],
) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    accepted: list[Finding] = []
    rejected: list[tuple[Finding, str]] = []
    for finding in findings:
        if finding.evidence == "verified_fact" and finding.evidence_fact_id not in known_fact_ids:
            rejected.append((finding, f"unknown fact id: {finding.evidence_fact_id}"))
            continue
        accepted.append(finding)
    return accepted, rejected


def apply_policy_filters(
    result: ReviewResult,
    *,
    threshold: int,
    tool_call_history: list[dict[str, object]],
    known_fact_ids: set[str],
) -> tuple[ReviewResult, list[dict[str, object]], list[tuple[Finding, str]], Counter[str]]:
    result, confidence_dropped = apply_confidence_threshold(result, threshold)
    result.findings, auto_tag_vendor_rejected = auto_tag_vendor_claims(result.findings)
    result.findings, evidence_tool_rejected = cross_check_tool_evidence(
        result.findings, tool_call_history
    )
    result.findings, evidence_fact_rejected = cross_check_fact_ids(result.findings, known_fact_ids)
    evidence_rejections = [
        *auto_tag_vendor_rejected,
        *evidence_tool_rejected,
        *evidence_fact_rejected,
    ]
    evidence_rejection_reasons = Counter(reason for _, reason in evidence_rejections)
    return result, confidence_dropped, evidence_rejections, evidence_rejection_reasons


def _stable_tool_input_repr(raw_input: object) -> str:
    if not isinstance(raw_input, dict):
        return "{}"
    parts = [f"{key}={raw_input[key]}" for key in sorted(raw_input.keys())]
    return ",".join(parts)
