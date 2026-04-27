from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol

from app.llm.types import LLMUsage, ModelProvider, ProviderHealthCheck


@dataclass(frozen=True)
class CacheRequestOptions:
    cache_key: str | None = None
    ttl: str | None = None
    retention: str | None = None
    cached_content_name: str | None = None


@dataclass(frozen=True)
class StructuredOutputRequest:
    model_name: str
    system_prompt: str
    messages: list[dict[str, Any]]
    tool_name: str
    tool_description: str
    input_schema: dict[str, Any]
    context: dict[str, Any]
    max_tokens: int
    temperature: float | None = None


@dataclass(frozen=True)
class StructuredOutputResult:
    payload: dict[str, Any]
    raw_response: Any
    usage: LLMUsage


class ProviderAdapter(Protocol):
    provider: ModelProvider

    async def complete(
        self, *, model_name: str, messages: list[dict[str, Any]], system_prompt: str | None = None
    ) -> Any: ...

    async def tool_loop(
        self,
        *,
        model_name: str,
        system_prompt: str,
        initial_user_message: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]: ...

    async def structured_output(
        self,
        *,
        request: StructuredOutputRequest,
    ) -> StructuredOutputResult: ...

    def render_anthropic_system(
        self, system_prompt: str, options: CacheRequestOptions | None = None
    ) -> list[dict[str, Any]]: ...

    def chat_completion_extra_kwargs(
        self,
        *,
        system_prompt: str,
        model_name: str,
        options: CacheRequestOptions | None = None,
    ) -> dict[str, Any]: ...

    def parse_usage(self, usage: object) -> LLMUsage: ...

    async def health_check(self, model_name: str) -> ProviderHealthCheck: ...


class BaseProviderAdapter:
    provider: ModelProvider = "unknown"

    async def complete(
        self, *, model_name: str, messages: list[dict[str, Any]], system_prompt: str | None = None
    ) -> Any:
        raise NotImplementedError(
            "Provider adapters expose complete through concrete runtime modules"
        )

    async def tool_loop(
        self,
        *,
        model_name: str,
        system_prompt: str,
        initial_user_message: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("Provider adapters expose tool_loop through app.agent.loop")

    async def structured_output(
        self,
        *,
        request: StructuredOutputRequest,
    ) -> StructuredOutputResult:
        raise NotImplementedError(
            "Provider adapters expose structured_output through app.agent.finalize"
        )

    def render_anthropic_system(
        self, system_prompt: str, options: CacheRequestOptions | None = None
    ) -> list[dict[str, Any]]:
        return [{"type": "text", "text": system_prompt}]

    def chat_completion_extra_kwargs(
        self,
        *,
        system_prompt: str,
        model_name: str,
        options: CacheRequestOptions | None = None,
    ) -> dict[str, Any]:
        return {}

    def parse_usage(self, usage: object) -> LLMUsage:
        input_tokens = _read_int(usage, "input_tokens", "prompt_tokens", "prompt_token_count")
        output_tokens = _read_int(
            usage, "output_tokens", "completion_tokens", "candidates_token_count"
        )
        total_tokens = _read_int(usage, "total_tokens", "total_token_count")
        cached_tokens = _read_nested_int(usage, ("prompt_tokens_details", "cached_tokens"))
        if cached_tokens == 0:
            cached_tokens = _read_int(
                usage, "cached_content_token_count", "cache_read_input_tokens"
            )
        cache_creation_tokens = _read_int(usage, "cache_creation_input_tokens")
        return LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_tokens,
            cache_creation_input_tokens=cache_creation_tokens,
            provider_usage=_usage_to_dict(usage),
        )

    async def health_check(self, model_name: str) -> ProviderHealthCheck:
        started = monotonic()
        return ProviderHealthCheck(
            provider=self.provider,
            model=model_name,
            ok=True,
            latency_ms=int((monotonic() - started) * 1000),
            details={"mode": "static"},
        )


def _read_int(obj: object, *names: str) -> int:
    for name in names:
        value = _read_attr_or_key(obj, name)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return 0


def _read_nested_int(obj: object, path: tuple[str, ...]) -> int:
    current = obj
    for name in path:
        current = _read_attr_or_key(current, name)
        if current is None:
            return 0
    if isinstance(current, bool):
        return 0
    if isinstance(current, int):
        return current
    if isinstance(current, float):
        return int(current)
    return 0


def _read_attr_or_key(obj: object, name: str) -> object | None:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _usage_to_dict(usage: object) -> dict[str, Any]:
    if isinstance(usage, dict):
        return {str(key): _jsonable(value) for key, value in usage.items()}
    model_dump = getattr(usage, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return (
            {str(key): _jsonable(value) for key, value in dumped.items()}
            if isinstance(dumped, dict)
            else {}
        )
    out: dict[str, Any] = {}
    for name in (
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "cached_content_token_count",
        "prompt_tokens_details",
    ):
        value = getattr(usage, name, None)
        if value is not None:
            out[name] = _jsonable(value)
    return out


def _jsonable(value: object) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return _jsonable(dumped)
    if hasattr(value, "__dict__"):
        return {str(key): _jsonable(item) for key, item in vars(value).items()}
    return str(value)


def record_usage(context: dict[str, Any], provider: str, model_name: str, usage: LLMUsage) -> None:
    context["input_tokens"] = int(context.get("input_tokens", 0)) + usage.input_tokens
    context["output_tokens"] = int(context.get("output_tokens", 0)) + usage.output_tokens
    context["tokens_used"] = int(context.get("tokens_used", 0)) + usage.total_tokens

    entries = context.setdefault("llm_usage", [])
    if isinstance(entries, list):
        entries.append(
            {
                "provider": provider,
                "model": model_name,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
                "cached_input_tokens": usage.cached_input_tokens,
                "cache_creation_input_tokens": usage.cache_creation_input_tokens,
            }
        )
