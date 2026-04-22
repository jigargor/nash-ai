import json
from pathlib import Path

from anthropic import AsyncAnthropic

from app.agent.acknowledgments import CodeAcknowledgment
from app.agent.schema import EditedReview, ReviewResult
from app.config import settings

EDITOR_SYSTEM_PATH = Path(__file__).parent / "prompts" / "editor_system.md"
client = AsyncAnthropic(api_key=settings.anthropic_api_key)


async def run_editor(
    *,
    draft: ReviewResult,
    pr_context: dict[str, object],
    prior_reviews: list[dict],
    code_acknowledgments: list[CodeAcknowledgment],
    model_name: str = "claude-sonnet-4-5",
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

    response = await client.messages.create(
        model=model_name,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": EDITOR_SYSTEM_PATH.read_text(encoding="utf-8"),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[
            {
                "name": "submit_edited_review",
                "description": "Submit the edited review with drop/keep/modify decisions.",
                "input_schema": EditedReview.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": "submit_edited_review"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Edit the following code review. Apply drop and modify rules strictly.\n\n"
                    f"```json\n{json.dumps(user_input, indent=2)}\n```"
                ),
            }
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_edited_review":
            return EditedReview.model_validate(block.input)
    raise RuntimeError("Model did not return submit_edited_review tool output")
