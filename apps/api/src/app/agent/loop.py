from time import monotonic
from typing import Any

from app.agent.constants import MAX_ITERATIONS
from app.agent.provider_clients import (
    anthropic_tools_to_openai_tools,
    create_openai_compatible_client,
    get_provider_api_key,
    parse_openai_tool_arguments,
)
from app.agent.review_config import DEFAULT_MODEL_NAME, ModelProvider
from app.agent.tools import TOOLS, execute_tool
from app.llm.providers import CacheRequestOptions, get_provider_adapter, record_usage
from app.observability import create_async_anthropic_client


async def run_agent(
    system_prompt: str,
    initial_user_message: str,
    context: dict[str, Any],
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    provider: ModelProvider = "anthropic",
) -> list[dict[str, Any]]:
    if provider in {"openai", "gemini"}:
        return await _run_agent_openai_compatible(system_prompt, initial_user_message, context, model_name=model_name, provider=provider)
    return await _run_agent_anthropic(system_prompt, initial_user_message, context, model_name=model_name)


async def _run_agent_anthropic(
    system_prompt: str,
    initial_user_message: str,
    context: dict[str, Any],
    *,
    model_name: str,
) -> list[dict[str, Any]]:
    user_key_override: str | None = context.get("user_provider_keys", {}).get("anthropic")
    client = create_async_anthropic_client(get_provider_api_key("anthropic", user_key_override=user_key_override))
    adapter = get_provider_adapter("anthropic")
    messages: list[dict[str, Any]] = [{"role": "user", "content": initial_user_message}]
    turns = 0
    fetch_file_content_calls = 0
    started_at = monotonic()
    anthropic_system: Any = adapter.render_anthropic_system(system_prompt, _cache_options(context))

    for _ in range(MAX_ITERATIONS):
        if _contains_empty_user_message(messages):
            break
        response = await client.messages.create(
            model=model_name,
            max_tokens=4096,
            system=anthropic_system,
            tools=TOOLS,  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
        )
        turns += 1
        if turns == 1:
            context["first_model_call_latency_ms"] = int((monotonic() - started_at) * 1000)

        record_usage(context, "anthropic", model_name, adapter.parse_usage(response.usage))

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
        "provider": "anthropic",
    }
    return messages


async def _run_agent_openai_compatible(
    system_prompt: str,
    initial_user_message: str,
    context: dict[str, Any],
    *,
    model_name: str,
    provider: ModelProvider,
) -> list[dict[str, Any]]:
    user_key_override = context.get("user_provider_keys", {}).get(provider)
    client = create_openai_compatible_client(provider, user_key_override=user_key_override)
    adapter = get_provider_adapter(provider)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": initial_user_message},
    ]
    turns = 0
    fetch_file_content_calls = 0
    started_at = monotonic()
    openai_tools = anthropic_tools_to_openai_tools(TOOLS)

    for _ in range(MAX_ITERATIONS):
        openai_messages: Any = messages
        openai_tools_any: Any = openai_tools
        completion = await client.chat.completions.create(
            model=model_name,
            temperature=0,
            messages=openai_messages,
            tools=openai_tools_any,
            **adapter.chat_completion_extra_kwargs(
                system_prompt=system_prompt,
                model_name=model_name,
                options=_cache_options(context),
            ),
        )
        turns += 1
        if turns == 1:
            context["first_model_call_latency_ms"] = int((monotonic() - started_at) * 1000)
        usage = completion.usage
        if usage is not None:
            record_usage(context, provider, model_name, adapter.parse_usage(usage))
        if not completion.choices:
            break
        message = completion.choices[0].message
        tool_calls = list(message.tool_calls or [])
        assistant_content = message.content or ""
        if tool_calls:
            serialized_tool_calls: list[dict[str, object]] = []
            for call in tool_calls:
                function_obj = getattr(call, "function", None)
                function_name = getattr(function_obj, "name", None)
                function_arguments = getattr(function_obj, "arguments", "{}")
                if not isinstance(function_name, str):
                    continue
                serialized_tool_calls.append(
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": function_name,
                            "arguments": function_arguments if isinstance(function_arguments, str) else "{}",
                        },
                    }
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": serialized_tool_calls,
                }
            )
            for call in tool_calls:
                function_obj = getattr(call, "function", None)
                function_name = getattr(function_obj, "name", None)
                function_arguments = getattr(function_obj, "arguments", "{}")
                if not isinstance(function_name, str):
                    continue
                if function_name == "fetch_file_content":
                    fetch_file_content_calls += 1
                parsed_input = parse_openai_tool_arguments(function_arguments if isinstance(function_arguments, str) else "{}")
                result = await execute_tool(function_name, parsed_input, context)
                normalized = result if str(result).strip() else "Tool returned empty output."
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": normalized,
                    }
                )
            continue
        messages.append({"role": "assistant", "content": assistant_content})
        break

    context["agent_metrics"] = {
        "turn_count": turns,
        "fetch_file_content_calls": fetch_file_content_calls,
        "first_model_call_latency_ms": context.get("first_model_call_latency_ms", 0),
        "provider": provider,
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
