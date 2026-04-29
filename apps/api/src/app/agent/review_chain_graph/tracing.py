from __future__ import annotations

from typing import Any

from app.config import settings

try:  # pragma: no cover - optional dependency
    from langsmith import Client
except Exception:  # pragma: no cover
    Client = None


def emit_langsmith_stage_trace(
    *,
    run_id: str,
    stage: str,
    metadata: dict[str, Any],
) -> None:
    if not settings.langsmith_tracing_enabled:
        return
    if Client is None:
        return
    if not settings.langsmith_api_key:
        return
    try:
        client = Client(api_key=settings.langsmith_api_key)
        client.create_run(
            name=stage,
            run_type="chain",
            id=run_id,
            project_name=settings.langsmith_project or "review-chain-poc",
            inputs={},
            outputs={"stage": stage},
            extra={"metadata": _sanitize_metadata(metadata)},
        )
    except Exception:
        return


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    blocked_tokens = ("token", "secret", "key", "authorization")
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        lowered = key.lower()
        if any(marker in lowered for marker in blocked_tokens):
            continue
        sanitized[key] = value
    return sanitized
