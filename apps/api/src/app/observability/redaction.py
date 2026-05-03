"""Payload safety and redaction helpers for observability sinks."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Literal

ObservabilityPayloadMode = Literal[
    "metadata_only", "hashed_payloads", "redacted_payloads", "raw_debug_local_only"
]


def hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def sanitize_payload(
    payload: dict[str, Any],
    *,
    mode: ObservabilityPayloadMode,
    max_metadata_bytes: int,
) -> dict[str, Any]:
    """Return a sink-safe payload according to configured observability mode."""
    if mode == "raw_debug_local_only":
        return _truncate_payload(payload, max_metadata_bytes=max_metadata_bytes)

    if mode == "metadata_only":
        return _metadata_only(payload, max_metadata_bytes=max_metadata_bytes)

    if mode == "hashed_payloads":
        hashed = _hash_sensitive_strings(payload)
        return _truncate_payload(hashed, max_metadata_bytes=max_metadata_bytes)

    redacted = _redact_sensitive_strings(payload)
    return _truncate_payload(redacted, max_metadata_bytes=max_metadata_bytes)


def _metadata_only(payload: dict[str, Any], *, max_metadata_bytes: int) -> dict[str, Any]:
    blocked_keys = {
        "prompt",
        "prompt_text",
        "response",
        "response_text",
        "tool_input",
        "tool_output",
        "raw_response",
        "messages",
        "diff_text",
    }
    output: dict[str, Any] = {}
    for key, value in payload.items():
        if key in blocked_keys:
            if isinstance(value, str) and value:
                output[f"{key}_hash"] = hash_text(value)
                output[f"{key}_length"] = len(value)
            continue
        output[key] = value
    return _truncate_payload(output, max_metadata_bytes=max_metadata_bytes)


def _hash_sensitive_strings(payload: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str) and len(value) > 64:
            output[key] = {"hash": hash_text(value), "length": len(value)}
            continue
        if isinstance(value, dict):
            output[key] = _hash_sensitive_strings(value)
            continue
        output[key] = value
    return output


def _redact_sensitive_strings(payload: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str) and len(value) > 128:
            output[key] = f"{value[:96]}... [redacted]"
            continue
        if isinstance(value, dict):
            output[key] = _redact_sensitive_strings(value)
            continue
        output[key] = value
    return output


def _truncate_payload(payload: dict[str, Any], *, max_metadata_bytes: int) -> dict[str, Any]:
    encoded = str(payload).encode("utf-8", errors="ignore")
    if len(encoded) <= max_metadata_bytes:
        return payload
    return {
        "truncated": True,
        "original_size_bytes": len(encoded),
        "max_metadata_bytes": max_metadata_bytes,
    }
