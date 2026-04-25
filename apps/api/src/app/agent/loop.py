from time import monotonic
from typing import Any

from app.agent.constants import MAX_ITERATIONS
from app.agent.review_config import DEFAULT_MODEL_NAME
from app.agent.tools import TOOLS, execute_tool
from app.config import settings
from app.observability import create_async_anthropic_client

client = create_async_anthropic_client(settings.anthropic_api_key)


async def run_agent(
    system_prompt: str,
    initial_user_message: str,
    context: dict[str, Any],
    *,
    model_name: str = DEFAULT_MODEL_NAME,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "user", "content": initial_user_message}]
    turns = 0
    fetch_file_content_calls = 0
    started_at = monotonic()

    for _ in range(MAX_ITERATIONS):
        if _contains_empty_user_message(messages):
            break
        response = await client.messages.create(
            model=model_name,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
        )
        turns += 1
        if turns == 1:
            context["first_model_call_latency_ms"] = int((monotonic() - started_at) * 1000)

        usage = response.usage
        context["input_tokens"] = context.get("input_tokens", 0) + usage.input_tokens
        context["output_tokens"] = context.get("output_tokens", 0) + usage.output_tokens
        context["tokens_used"] = context.get("tokens_used", 0) + usage.input_tokens + usage.output_tokens

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            tool_results: list[dict[str, str]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if block.name == "fetch_file_content":
                    fetch_file_content_calls += 1
                result = await execute_tool(block.name, block.input, context)
                normalized = result if str(result).strip() else "Tool returned empty output."
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": normalized,
                    }
                )
            if not tool_results:
                tool_results.append(
                    {
                        "type": "text",
                        "text": "No tool results were produced for this turn. Continue with available context.",
                    }
                )
            messages.append({"role": "user", "content": tool_results})
            continue

        break

    context["agent_metrics"] = {
        "turn_count": turns,
        "fetch_file_content_calls": fetch_file_content_calls,
        "first_model_call_latency_ms": context.get("first_model_call_latency_ms", 0),
    }
    return messages


def _contains_empty_user_message(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and not content.strip():
            return True
        if isinstance(content, list) and not content:
            return True
    return False
