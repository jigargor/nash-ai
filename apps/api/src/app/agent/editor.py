import json
from pathlib import Path
from typing import Any

from app.agent.acknowledgments import CodeAcknowledgment
from app.agent.provider_clients import anthropic_tools_to_openai_tools, create_openai_compatible_client, get_provider_api_key
from app.agent.review_config import ModelProvider
from app.agent.schema import EditedReview, ReviewResult
from app.llm.providers import CacheRequestOptions, get_provider_adapter, record_usage
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

    if provider in {"openai", "gemini"}:
        return await _run_editor_openai_compatible(
            provider=provider,
            model_name=model_name,
            user_input=user_input,
            context=context,
        )
    return await _run_editor_anthropic(model_name=model_name, user_input=user_input, context=context)


async def _run_editor_anthropic(*, model_name: str, user_input: dict[str, Any], context: dict[str, Any] | None) -> EditedReview:
    client = create_async_anthropic_client(get_provider_api_key("anthropic"))
    adapter = get_provider_adapter("anthropic")
    anthropic_system: Any = adapter.render_anthropic_system(
        EDITOR_SYSTEM_PATH.read_text(encoding="utf-8"),
        _cache_options(context),
    )
    anthropic_tools: Any = [
        {
            "name": "submit_edited_review",
            "description": "Submit the edited review with drop/keep/modify decisions.",
            "input_schema": EditedReview.model_json_schema(),
        }
    ]
    anthropic_tool_choice: Any = {"type": "tool", "name": "submit_edited_review"}
    anthropic_messages: Any = [
        {
            "role": "user",
            "content": (
                "Edit the following code review. Apply drop and modify rules strictly.\n\n"
                f"```json\n{json.dumps(user_input, indent=2)}\n```"
            ),
        }
    ]
    response = await client.messages.create(
        model=model_name,
        max_tokens=4096,
        system=anthropic_system,
        tools=anthropic_tools,
        tool_choice=anthropic_tool_choice,
        messages=anthropic_messages,
    )
    if context is not None:
        record_usage(context, "anthropic", model_name, adapter.parse_usage(response.usage))

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_edited_review":
            return EditedReview.model_validate(block.input)
    raise RuntimeError("Model did not return submit_edited_review tool output")


async def _run_editor_openai_compatible(
    *,
    provider: ModelProvider,
    model_name: str,
    user_input: dict[str, Any],
    context: dict[str, Any] | None,
) -> EditedReview:
    client = create_openai_compatible_client(provider)
    adapter = get_provider_adapter(provider)
    system_prompt = EDITOR_SYSTEM_PATH.read_text(encoding="utf-8")
    openai_messages_any: Any = [
        {"role": "system", "content": system_prompt},
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
        **adapter.chat_completion_extra_kwargs(
            system_prompt=system_prompt,
            model_name=model_name,
            options=_cache_options(context),
        ),
    )
    if context is not None and response.usage is not None:
        record_usage(context, provider, model_name, adapter.parse_usage(response.usage))
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


def _cache_options(context: dict[str, Any] | None) -> CacheRequestOptions:
    context = context or {}
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
