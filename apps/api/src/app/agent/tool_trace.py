"""Extract tool-use history from provider-neutral message transcripts."""

from __future__ import annotations

from collections.abc import Iterator

from app.agent.provider_clients import parse_openai_tool_arguments


def _block_parts(block: object) -> tuple[str, str | None, dict[str, object] | None]:
    if isinstance(block, dict):
        block_type = str(block.get("type", ""))
        raw_name = block.get("name")
        block_name = str(raw_name) if raw_name is not None else None
        maybe_input = block.get("input")
    else:
        block_type = str(getattr(block, "type", ""))
        raw_name = getattr(block, "name", None)
        block_name = str(raw_name) if isinstance(raw_name, str) else None
        maybe_input = getattr(block, "input", None)
    tool_input = maybe_input if isinstance(maybe_input, dict) else None
    return block_type, block_name, tool_input


def _openai_tool_call_parts(call: object) -> tuple[str | None, dict[str, object] | None]:
    """Parse one OpenAI-format tool call: ``{"function": {"name", "arguments"}}``."""
    function_obj = call.get("function") if isinstance(call, dict) else getattr(call, "function", None)
    if isinstance(function_obj, dict):
        raw_name = function_obj.get("name")
        raw_arguments = function_obj.get("arguments")
    else:
        raw_name = getattr(function_obj, "name", None)
        raw_arguments = getattr(function_obj, "arguments", None)
    if not isinstance(raw_name, str) or not raw_name:
        return None, None
    if isinstance(raw_arguments, dict):
        return raw_name, dict(raw_arguments)
    arguments = parse_openai_tool_arguments(raw_arguments if isinstance(raw_arguments, str) else "{}")
    return raw_name, dict(arguments)


def _iter_tool_calls(messages: list[dict[str, object]]) -> Iterator[tuple[str, dict[str, object]]]:
    """Yield ``(tool_name, tool_input)`` for Anthropic ``tool_use`` blocks and OpenAI ``tool_calls``."""
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                block_type, block_name, tool_input = _block_parts(block)
                if block_type != "tool_use" or not block_name or tool_input is None:
                    continue
                yield block_name, tool_input
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for call in tool_calls:
                call_name, call_input = _openai_tool_call_parts(call)
                if call_name is None or call_input is None:
                    continue
                yield call_name, call_input


def extract_tool_usage_by_file(messages: list[dict[str, object]]) -> set[str]:
    touched_paths: set[str] = set()
    for _, tool_input in _iter_tool_calls(messages):
        candidate = tool_input.get("path") or tool_input.get("file_path")
        if isinstance(candidate, str) and candidate.strip():
            touched_paths.add(candidate.strip())
    return touched_paths


def extract_tool_call_history(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{"name": name, "input": tool_input} for name, tool_input in _iter_tool_calls(messages)]


def extract_tool_usage_with_context(
    messages: list[dict[str, object]],
    context: dict[str, object] | None = None,
) -> tuple[set[str], list[dict[str, object]]]:
    """Return ``(touched_paths, call_history)`` from messages, enriched by ``context["tool_trace"]``.

    ``context["tool_trace"]`` entries (written by the agent loop) only carry hashed inputs, so they
    can contribute tool *names* when the transcript is unavailable or lossy, but never paths.
    Message-derived history is authoritative and is never replaced, only supplemented.
    """
    touched_paths = extract_tool_usage_by_file(messages)
    history = extract_tool_call_history(messages)
    if context is None:
        return touched_paths, history
    trace = context.get("tool_trace")
    if isinstance(trace, list):
        seen_names = {str(call["name"]) for call in history}
        for entry in trace:
            if not isinstance(entry, dict) or entry.get("success") is False:
                continue
            name = entry.get("tool_name")
            if isinstance(name, str) and name and name not in seen_names:
                history.append({"name": name, "input": {}})
                seen_names.add(name)
    return touched_paths, history
