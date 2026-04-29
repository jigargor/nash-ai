import json
from pathlib import Path
from typing import Any

from app.agent.acknowledgments import CodeAcknowledgment
from app.agent.review_config import ModelProvider
from app.agent.finalize import parse_edited_review
from app.agent.schema import EditedReview, ReviewResult
from app.llm.providers import StructuredOutputRequest, get_provider_adapter

EDITOR_SYSTEM_PATH = Path(__file__).parent / "prompts" / "editor_system.md"


async def run_editor(
    *,
    draft: ReviewResult,
    pr_context: dict[str, Any],
    prior_reviews: list[dict[str, Any]],
    code_acknowledgments: list[CodeAcknowledgment],
    model_name: str = "claude-sonnet-4-5",
    provider: ModelProvider = "anthropic",
    context: dict[str, Any] | None = None,
) -> EditedReview:
    user_input = {
        "pr_context": pr_context,
        "prior_reviews": [
            {
                "file_path": review.get("path"),
                "line_start": review.get("line") or review.get("original_line"),
                "line_end": review.get("line") or review.get("original_line"),
                "category": "unknown",
                "message_preview": str(review.get("body", ""))[:200],
            }
            for review in prior_reviews
            if isinstance(review, dict)
        ],
        "code_acknowledgments": [
            {"file_path": ack.file_path, "line_number": ack.line_number, "text": ack.text}
            for ack in code_acknowledgments
        ],
        "findings": draft.model_dump(mode="json").get("findings", []),
        "summary": draft.summary,
    }

    system_prompt = EDITOR_SYSTEM_PATH.read_text(encoding="utf-8")
    prompt = (
        "Edit the following code review. Apply drop and modify rules strictly.\n\n"
        f"```json\n{json.dumps(user_input, indent=2)}\n```"
    )
    adapter = get_provider_adapter(provider)
    result = await adapter.structured_output(
        request=StructuredOutputRequest(
            model_name=model_name,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            tool_name="submit_edited_review",
            tool_description="Submit the edited review with drop/keep/modify decisions.",
            input_schema=EditedReview.model_json_schema(),
            context=context or {},
            max_tokens=4096,
            temperature=0,
        )
    )
    return parse_edited_review(result.payload)
