"""Extract tool-use history from provider-neutral message transcripts."""

from __future__ import annotations


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


def extract_tool_usage_by_file(messages: list[dict[str, object]]) -> set[str]:
    touched_paths: set[str] = set()
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            block_type, _, tool_input = _block_parts(block)
            if block_type != "tool_use" or tool_input is None:
                continue
            candidate = tool_input.get("path") or tool_input.get("file_path")
            if isinstance(candidate, str) and candidate.strip():
                touched_paths.add(candidate.strip())
    return touched_paths


def extract_tool_call_history(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    history: list[dict[str, object]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            block_type, block_name, tool_input = _block_parts(block)
            if block_type != "tool_use" or not block_name or tool_input is None:
                continue
            history.append({"name": block_name, "input": tool_input})
    return history
