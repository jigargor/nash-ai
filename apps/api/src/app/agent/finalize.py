import logging
from typing import Any, Final

from pydantic import ValidationError

from app.agent.provider_clients import (
    anthropic_tools_to_openai_tools,
    create_openai_compatible_client,
    get_provider_api_key,
    parse_openai_tool_arguments,
)
from app.agent.review_config import DEFAULT_MODEL_NAME, ModelProvider
from app.agent.schema import Finding, ReviewResult
from app.agent.text_sanitizer import sanitize_markdown_text, truncate_markdown_text
from app.llm.providers import CacheRequestOptions, get_provider_adapter, record_usage
from app.observability import create_async_anthropic_client

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
    if provider in {"openai", "gemini"}:
        return await _finalize_openai_compatible(
            system_prompt=system_prompt,
            messages=messages,
            context=context,
            model_name=model_name,
            provider=provider,
            validation_feedback=validation_feedback,
            allow_retry=allow_retry,
        )
    return await _finalize_anthropic(
        system_prompt=system_prompt,
        messages=messages,
        context=context,
        model_name=model_name,
        validation_feedback=validation_feedback,
        allow_retry=allow_retry,
    )


async def _finalize_anthropic(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    context: dict[str, Any],
    model_name: str,
    validation_feedback: str | None,
    allow_retry: bool,
) -> ReviewResult:
    client = create_async_anthropic_client(get_provider_api_key("anthropic"))
    adapter = get_provider_adapter("anthropic")
    final_prompt = "Now submit your final review using the submit_review tool."
    if validation_feedback:
        final_prompt = (
            "Regenerate the final review. Previous findings failed validation checks.\n"
            f"{validation_feedback}\n\n"
            "Now submit your corrected review using the submit_review tool."
        )
    response = await client.messages.create(  # type: ignore[call-overload]
        model=model_name,
        max_tokens=8192,
        system=adapter.render_anthropic_system(system_prompt, _cache_options(context)),
        tools=[FINAL_TOOL],
        tool_choice={"type": "tool", "name": "submit_review"},
        messages=messages + [{"role": "user", "content": final_prompt}],
    )

    record_usage(context, "anthropic", model_name, adapter.parse_usage(response.usage))

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_review":
            repaired_input = _repair_review_input(block.input)
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
                        provider="anthropic",
                        validation_feedback=retry_feedback,
                        allow_retry=False,
                    )
                return _safe_partial_review_result(
                    repaired_input,
                    reason="schema_validation_failed_after_retry",
                    validation_error=exc,
                )
    logger.warning("submit_review tool missing from anthropic response; returning safe empty result")
    return _safe_partial_review_result(
        {"findings": [], "summary": "Review output was incomplete; returned a safe empty result."},
        reason="submit_review_tool_missing",
    )


async def _finalize_openai_compatible(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    context: dict[str, Any],
    model_name: str,
    provider: ModelProvider,
    validation_feedback: str | None,
    allow_retry: bool,
) -> ReviewResult:
    client = create_openai_compatible_client(provider)
    adapter = get_provider_adapter(provider)
    final_prompt = "Now submit your final review using the submit_review tool."
    if validation_feedback:
        final_prompt = (
            "Regenerate the final review. Previous findings failed validation checks.\n"
            f"{validation_feedback}\n\n"
            "Now submit your corrected review using the submit_review tool."
        )
    openai_messages = list(messages)
    has_system = bool(openai_messages and openai_messages[0].get("role") == "system")
    if not has_system:
        openai_messages.insert(0, {"role": "system", "content": system_prompt})
    openai_messages.append({"role": "user", "content": final_prompt})

    openai_messages_any: Any = openai_messages
    openai_tools_any: Any = anthropic_tools_to_openai_tools([FINAL_TOOL])
    openai_tool_choice_any: Any = {"type": "function", "function": {"name": "submit_review"}}
    response = await client.chat.completions.create(
        model=model_name,
        temperature=0,
        messages=openai_messages_any,
        tools=openai_tools_any,
        tool_choice=openai_tool_choice_any,
        **adapter.chat_completion_extra_kwargs(
            system_prompt=system_prompt,
            model_name=model_name,
            options=_cache_options(context),
        ),
    )
    usage = response.usage
    if usage is not None:
        record_usage(context, provider, model_name, adapter.parse_usage(usage))
    if not response.choices:
        raise RuntimeError("Model did not return submit_review output")
    message = response.choices[0].message
    for call in list(message.tool_calls or []):
        function_obj = getattr(call, "function", None)
        function_name = getattr(function_obj, "name", None)
        function_arguments = getattr(function_obj, "arguments", "{}")
        if function_name != "submit_review":
            continue
        repaired_input = _repair_review_input(
            parse_openai_tool_arguments(function_arguments if isinstance(function_arguments, str) else "{}")
        )
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
    if message.content:
        logger.warning("submit_review tool missing; raw content excerpt=%s", str(message.content)[:200])
    return _safe_partial_review_result(
        {"findings": [], "summary": "Review output was incomplete; returned a safe empty result."},
        reason="submit_review_tool_missing",
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


def _cache_options(context: dict[str, Any]) -> CacheRequestOptions:
    return CacheRequestOptions(
        cache_key=_optional_str(context.get("llm_prompt_cache_key")),
        ttl=_optional_str(context.get("anthropic_cache_ttl")),
        retention=_optional_str(context.get("openai_prompt_cache_retention")),
        cached_content_name=_optional_str(context.get("gemini_cached_content_name")),
    )


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
