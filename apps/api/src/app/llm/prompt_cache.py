"""Optional Redis prompt-hash cache for identical re-runs (best-effort)."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any


def prompt_cache_key(
    *,
    provider: str,
    model: str,
    effort: str | None,
    system: str,
    messages: Any,
    tools: Any = None,
    schema: Any = None,
) -> str:
    payload = {
        "provider": provider,
        "model": model,
        "effort": effort or "",
        "system": system,
        "messages": messages,
        "tools": tools,
        "schema": schema,
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return sha256(raw).hexdigest()


async def redis_cache_get(redis: Any, key: str) -> dict[str, Any] | None:
    if redis is None:
        return None
    try:
        raw = await redis.get(f"nash:llm:{key}")
    except Exception:
        return None
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def redis_cache_set(redis: Any, key: str, payload: dict[str, Any], ttl_s: int = 3600) -> None:
    if redis is None:
        return
    try:
        await redis.set(f"nash:llm:{key}", json.dumps(payload, default=str), ex=ttl_s)
    except Exception:
        return
