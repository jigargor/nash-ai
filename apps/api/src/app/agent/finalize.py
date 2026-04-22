from anthropic import AsyncAnthropic
import logging

from pydantic import ValidationError

from app.agent.review_config import DEFAULT_MODEL_NAME
from app.agent.schema import ReviewResult
from app.agent.text_sanitizer import sanitize_markdown_text, truncate_markdown_text
from app.config import settings

client = AsyncAnthropic(api_key=settings.anthropic_api_key)
logger = logging.getLogger(__name__)

FINAL_TOOL = {
    "name": "submit_review",
    "description": "Submit the final code review with all findings.",
    "input_schema": ReviewResult.model_json_schema(),
}


async def finalize_review(
    system_prompt: str,
    messages: list[dict],
    context: dict,
    *,
    model_name: str = DEFAULT_MODEL_NAME,
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
    response = await client.messages.create(
        model=model_name,
        max_tokens=8192,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[FINAL_TOOL],
        tool_choice={"type": "tool", "name": "submit_review"},
        messages=messages + [{"role": "user", "content": final_prompt}],
    )

    usage = response.usage
    context["input_tokens"] = context.get("input_tokens", 0) + usage.input_tokens
    context["output_tokens"] = context.get("output_tokens", 0) + usage.output_tokens
    context["tokens_used"] = context.get("tokens_used", 0) + usage.input_tokens + usage.output_tokens

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
                        validation_feedback=retry_feedback,
                        allow_retry=False,
                    )
                raise RuntimeError("Final review schema validation failed after retry") from exc
    raise RuntimeError("Model did not return submit_review tool output")


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
            normalized_finding = dict(finding)
            message = normalized_finding.get("message")
            if isinstance(message, str):
                normalized_finding["message"] = sanitize_markdown_text(message)
            normalized_findings.append(normalized_finding)
        repaired["findings"] = normalized_findings
    return repaired


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
