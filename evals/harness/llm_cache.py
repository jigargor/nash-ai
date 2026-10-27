"""LLM response cache for evals — keyed by request fingerprint (cached reruns cost $0)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = REPO_ROOT / "evals" / "cache" / "llm"


def request_fingerprint(
    *,
    provider: str,
    model: str,
    effort: str | None,
    system: str,
    messages: list[dict[str, Any]] | str,
    tools: Any = None,
    schema: Any = None,
) -> str:
    payload = {
        "provider": provider,
        "model": model,
        "effort": effort or "",
        "system": system,
        "messages": _jsonable(messages),
        "tools": _jsonable(tools),
        "schema": _jsonable(schema),
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _jsonable(dump())
    if hasattr(value, "__dict__"):
        return {str(k): _jsonable(v) for k, v in vars(value).items() if not str(k).startswith("_")}
    return str(value)


class LLMResponseCache:
    def __init__(self, cache_dir: Path | None = None, *, enabled: bool = True) -> None:
        self.cache_dir = cache_dir or CACHE_ROOT
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.enabled = enabled
        self.hits = 0
        self.misses = 0

    def get(self, fingerprint: str) -> dict[str, Any] | None:
        if not self.enabled:
            self.misses += 1
            return None
        path = self.cache_dir / f"{fingerprint}.json"
        if not path.exists():
            self.misses += 1
            return None
        self.hits += 1
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None

    def put(self, fingerprint: str, response: dict[str, Any]) -> None:
        if not self.enabled:
            return
        path = self.cache_dir / f"{fingerprint}.json"
        path.write_text(json.dumps(response, indent=2, default=str), encoding="utf-8")


AgentRunnerFn = Callable[..., Awaitable[list[dict[str, Any]]]]
FinalizerFn = Callable[..., Awaitable[Any]]


def cached_agent_runner(inner: AgentRunnerFn, cache: LLMResponseCache) -> AgentRunnerFn:
    """Cache whole ReAct transcripts keyed by (provider, model, effort, system, user prompt)."""

    async def _run(
        system_prompt: str,
        initial_user_message: str,
        context: dict[str, Any],
        *,
        model_name: str,
        provider: str,
    ) -> list[dict[str, Any]]:
        key = request_fingerprint(
            provider=provider,
            model=model_name,
            effort=str(context.get("llm_effort") or ""),
            system=system_prompt,
            messages=initial_user_message,
            tools="react-loop",
        )
        hit = cache.get(key)
        if hit is not None:
            context["llm_mode"] = "cache"
            context["agent_metrics"] = hit.get("agent_metrics") or {}
            context["tool_trace"] = list(hit.get("tool_trace") or [])
            fetched = hit.get("fetched_files")
            if isinstance(fetched, dict):
                existing = context.setdefault("fetched_files", {})
                if isinstance(existing, dict):
                    existing.update(fetched)
            return list(hit.get("messages") or [])
        messages = await inner(
            system_prompt, initial_user_message, context, model_name=model_name, provider=provider
        )
        context["llm_mode"] = "live"
        serialisable = _jsonable(messages)
        cache.put(
            key,
            {
                "messages": serialisable,
                "agent_metrics": _jsonable(context.get("agent_metrics") or {}),
                "tool_trace": _jsonable(context.get("tool_trace") or []),
                "fetched_files": _jsonable(context.get("fetched_files") or {}),
                "usage": _jsonable(context.get("llm_usage") or []),
            },
        )
        return list(serialisable) if isinstance(serialisable, list) else messages

    return _run


def cached_finalizer(inner: FinalizerFn, cache: LLMResponseCache) -> FinalizerFn:
    from app.agent.schema import ReviewResult

    async def _run(
        system_prompt: str,
        messages: list[dict[str, Any]],
        context: dict[str, Any],
        *,
        model_name: str,
        provider: str,
        **kwargs: Any,
    ) -> ReviewResult:
        key = request_fingerprint(
            provider=provider,
            model=model_name,
            effort=str(context.get("llm_effort") or ""),
            system=system_prompt,
            messages=messages,
            schema="submit_review",
        )
        hit = cache.get(key)
        if hit is not None and isinstance(hit.get("result"), dict):
            context["llm_mode"] = "cache" if context.get("llm_mode") != "live" else "live+cache"
            return ReviewResult.model_validate(hit["result"])
        result = await inner(
            system_prompt, messages, context, model_name=model_name, provider=provider, **kwargs
        )
        cache.put(key, {"result": result.model_dump(mode="json")})
        return result

    return _run
