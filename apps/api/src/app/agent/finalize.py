import logging
from typing import Any, Final, cast

from pydantic import ValidationError

from app.agent.review_config import DEFAULT_MODEL_NAME, ModelProvider
from app.agent.schema import Finding, ReviewResult
from app.agent.text_sanitizer import sanitize_markdown_text, truncate_markdown_text
from app.llm.providers import StructuredOutputRequest, get_provider_adapter

logger = logging.getLogger(__name__)

_ALLOWED_FINDING_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"security", "performance", "correctness", "style", "maintainability"}
)
_CATEGORY_ALIASES: Final[dict[str, str]] = {
    "completeness": "maintainability",
    "documentation": "maintainability",
    "docs": "maintainability",
    "reliability": "correctness",
    "testing": "correctness",
}

FINAL_TOOL = {
    "name": "submit_review",
    "description": "Submit the final code review with all findings.",
    "input_schema": ReviewResult.model_json_schema(),
}


async def finalize_review(
    system_prompt: str,
    messages: list[dict[str, Any]],
    context: dict[str, Any],
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    provider: ModelProvider = "anthropic",
    validation_feedback: str | None = None,
    allow_retry: bool = True,
) -> ReviewResult:
    final_prompt = "Now submit your final review using the submit_review tool."
    if validation_feedback:
        final_prompt = (
            "Regenerate the final review. Previous findings failed validation checks.\n"
            f"{validation_feedback}\n\n"
            "Now submit your corrected review using the submit_review tool."
        )
    adapter = get_provider_adapter(provider)
    try:
        structured = await adapter.structured_output(
            request=StructuredOutputRequest(
                model_name=model_name,
                system_prompt=system_prompt,
                messages=messages + [{"role": "user", "content": final_prompt}],
                tool_name=str(FINAL_TOOL["name"]),
                tool_description=str(FINAL_TOOL["description"]),
                input_schema=cast(dict[str, Any], FINAL_TOOL["input_schema"]),
                context=context,
                max_tokens=8192,
                temperature=0,
            )
        )
    except RuntimeError as exc:
        logger.warning("submit_review tool missing or malformed; returning safe empty result: %s", exc)
        return _safe_partial_review_result(
            {"findings": [], "summary": "Review output was incomplete; returned a safe empty result."},
            reason="submit_review_tool_missing",
        )

    repaired_input = _repair_review_input(structured.payload)
    try:
        return ReviewResult.model_validate(repaired_input)
    except ValidationError as exc:
        logger.warning("Final review validation failed: %s", exc)
        if allow_retry:
            retry_feedback = _build_schema_feedback(exc)
            if validation_feedback:
                retry_feedback = f"{validation_feedback}\n\n{retry_feedback}"
            return await finalize_review(
                system_prompt=system_prompt,
                messages=messages,
                context=context,
                model_name=model_name,
                provider=provider,
                validation_feedback=retry_feedback,
                allow_retry=False,
            )
        return _safe_partial_review_result(
            repaired_input,
            reason="schema_validation_failed_after_retry",
            validation_error=exc,
        )


def _repair_review_input(raw_input: object) -> object:
    if not isinstance(raw_input, dict):
        return raw_input

    repaired = dict(raw_input)
    summary = repaired.get("summary")
    if isinstance(summary, str):
        repaired["summary"] = truncate_markdown_text(summary, 800)

    findings = repaired.get("findings")
    if isinstance(findings, list):
        normalized_findings = []
        for finding in findings:
            if not isinstance(finding, dict):
                normalized_findings.append(finding)
                continue
            normalized_finding = _coerce_finding_payload(dict(finding))
            message = normalized_finding.get("message")
            if isinstance(message, str):
                normalized_finding["message"] = sanitize_markdown_text(message)
            normalized_findings.append(normalized_finding)
        repaired["findings"] = normalized_findings
    return repaired


def _parse_confidence(raw: object) -> int:
    if isinstance(raw, bool):
        return 50
    if isinstance(raw, int):
        return max(0, min(100, raw))
    if isinstance(raw, float):
        return max(0, min(100, int(round(raw))))
    if isinstance(raw, str):
        try:
            return max(0, min(100, int(round(float(raw.strip())))))
        except ValueError:
            return 50
    return 50


def _coerce_finding_payload(finding: dict[str, Any]) -> dict[str, Any]:
    """Normalize model output so Finding validators pass without weakening safety-critical tool_verified rules."""
    d: dict[str, Any] = dict(finding)

    cat = d.get("category")
    if isinstance(cat, str):
        key = cat.strip().lower()
        if key in _CATEGORY_ALIASES:
            d["category"] = _CATEGORY_ALIASES[key]
        elif key not in _ALLOWED_FINDING_CATEGORIES:
            d["category"] = "maintainability"

    d["confidence"] = _parse_confidence(d.get("confidence"))

    sev = d.get("severity")
    if not isinstance(sev, str) or sev not in {"critical", "high", "medium", "low"}:
        d["severity"] = "medium"
        sev = "medium"
    ev = d.get("evidence")
    if not isinstance(ev, str) or ev not in {"tool_verified", "diff_visible", "verified_fact", "inference"}:
        d["evidence"] = "diff_visible"
        ev = "diff_visible"

    if ev == "verified_fact" and not (
        isinstance(d.get("evidence_fact_id"), str) and str(d["evidence_fact_id"]).strip()
    ):
        d["evidence"] = "diff_visible"
        d.pop("evidence_fact_id", None)
        ev = "diff_visible"

    vendor = bool(d.get("is_vendor_claim"))

    # Inference: only low/medium; confidence ≤ 75 (schema Finding.check_evidence_consistency)
    if ev == "inference":
        d["confidence"] = min(d["confidence"], 75)
        if sev in ("high", "critical"):
            d["severity"] = "medium"
            sev = "medium"

    # Vendor critical without tool verification → medium (before generic critical→high step)
    if vendor and sev == "critical" and ev != "tool_verified":
        d["severity"] = "medium"
        sev = "medium"

    # Critical requires tool_verified (schema); downgrade so non-tool paths can still validate
    if sev == "critical" and ev != "tool_verified":
        d["severity"] = "high"
        sev = "high"

    # Vendor high without strong evidence → medium
    if vendor and sev == "high" and ev not in ("tool_verified", "verified_fact"):
        d["severity"] = "medium"
        sev = "medium"

    if vendor and ev != "tool_verified":
        d["confidence"] = min(d["confidence"], 85)

    return d


def _safe_partial_review_result(
    raw_input: object,
    *,
    reason: str,
    validation_error: ValidationError | None = None,
) -> ReviewResult:
    findings_raw: list[object] = []
    summary_raw: object = None
    if isinstance(raw_input, dict):
        findings_obj = raw_input.get("findings")
        if isinstance(findings_obj, list):
            findings_raw = findings_obj
        summary_raw = raw_input.get("summary")

    valid_findings: list[Finding] = []
    dropped_count = 0
    for item in findings_raw:
        if not isinstance(item, dict):
            dropped_count += 1
            continue
        try:
            valid_findings.append(Finding.model_validate(item))
        except ValidationError:
            dropped_count += 1

    if isinstance(summary_raw, str) and summary_raw.strip():
        base_summary = truncate_markdown_text(summary_raw, 560)
    else:
        base_summary = "Review completed with partial output."

    if dropped_count:
        summary = (
            f"{base_summary} "
            f"Recovered {len(valid_findings)} valid finding(s) and dropped {dropped_count} invalid finding(s)."
        )
    else:
        summary = f"{base_summary} Returned a safe fallback result ({reason})."
    summary = truncate_markdown_text(summary, 800)

    if validation_error is not None:
        logger.warning(
            "Returning recoverable partial ReviewResult after validation failure reason=%s kept=%s dropped=%s",
            reason,
            len(valid_findings),
            dropped_count,
        )
    return ReviewResult(findings=valid_findings, summary=summary)


def _build_schema_feedback(exc: ValidationError) -> str:
    lines = [
        "Your previous submit_review payload failed schema validation.",
        "Regenerate and strictly satisfy the schema constraints.",
        "Validation errors:",
    ]
    for issue in exc.errors(include_url=False):
        location = ".".join(str(part) for part in issue.get("loc", []))
        message = issue.get("msg", "Validation error")
        lines.append(f"- {location}: {message}")
    return "\n".join(lines)


