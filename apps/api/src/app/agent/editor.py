import json
from pathlib import Path
from typing import Any

from app.agent.acknowledgments import CodeAcknowledgment
from app.agent.provider_clients import anthropic_tools_to_openai_tools, create_openai_compatible_client, get_provider_api_key
from app.agent.review_config import ModelProvider
from app.agent.schema import EditedReview, ReviewResult
from app.observability import create_async_anthropic_client

EDITOR_SYSTEM_PATH = Path(__file__).parent / "prompts" / "editor_system.md"


async def run_editor(
    *,
    draft: ReviewResult,
    pr_context: dict[str, Any],
    prior_reviews: list[dict[str, Any]],
    code_acknowledgments: list[CodeAcknowledgment],
    model_name: str = "claude-sonnet-4-5",
    provider: ModelProvider = "anthropic",
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

    if provider in {"openai", "gemini"}:
        return await _run_editor_openai_compatible(
            provider=provider,
            model_name=model_name,
            user_input=user_input,
        )
    return await _run_editor_anthropic(model_name=model_name, user_input=user_input)


async def _run_editor_anthropic(*, model_name: str, user_input: dict[str, Any]) -> EditedReview:
    client = create_async_anthropic_client(get_provider_api_key("anthropic"))
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


async def _run_editor_openai_compatible(
    *,
    provider: ModelProvider,
    model_name: str,
    user_input: dict[str, Any],
) -> EditedReview:
    client = create_openai_compatible_client(provider)
    openai_messages_any: Any = [
        {"role": "system", "content": EDITOR_SYSTEM_PATH.read_text(encoding="utf-8")},
        {
            "role": "user",
            "content": (
                "Edit the following code review. Apply drop and modify rules strictly.\n\n"
                f"```json\n{json.dumps(user_input, indent=2)}\n```"
            ),
        },
    ]
    openai_tools_any: Any = anthropic_tools_to_openai_tools(
        [
            {
                "name": "submit_edited_review",
                "description": "Submit the edited review with drop/keep/modify decisions.",
                "input_schema": EditedReview.model_json_schema(),
            }
        ]
    )
    openai_tool_choice_any: Any = {"type": "function", "function": {"name": "submit_edited_review"}}
    response = await client.chat.completions.create(
        model=model_name,
        temperature=0,
        messages=openai_messages_any,
        tools=openai_tools_any,
        tool_choice=openai_tool_choice_any,
    )
    if not response.choices:
        raise RuntimeError("Model did not return submit_edited_review output")
    message = response.choices[0].message
    for call in list(message.tool_calls or []):
        function_obj = getattr(call, "function", None)
        function_name = getattr(function_obj, "name", None)
        function_arguments = getattr(function_obj, "arguments", "{}")
        if function_name == "submit_edited_review":
            parsed = json.loads(function_arguments if isinstance(function_arguments, str) else "{}")
            if isinstance(parsed, dict):
                return EditedReview.model_validate(parsed)
    raise RuntimeError("Model did not return submit_edited_review tool output")
