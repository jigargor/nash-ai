from __future__ import annotations

from typing import Any

from app.agent.prompts.system import DYNAMIC_PROMPT_MARKER, split_system_prompt
from app.agent.provider_clients import get_provider_api_key
from app.llm.catalog.loader import load_baseline_catalog
from app.llm.errors import coerce_quota_error
from app.llm.providers.base import (
    BaseProviderAdapter,
    CacheRequestOptions,
    StructuredOutputRequest,
    StructuredOutputResult,
    record_usage,
)
from app.llm.types import LLMUsage, ModelCapabilities
from app.observability import create_async_anthropic_client


class AnthropicAdapter(BaseProviderAdapter):
    provider = "anthropic"

    def render_anthropic_system(
        self,
        system_prompt: str,
        options: CacheRequestOptions | None = None,
        *,
        dynamic_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Render system blocks; only the static prefix carries ``cache_control``.

        When ``dynamic_prompt`` is not given, the prompt is split on the dynamic-section
        marker emitted by ``build_system_prompt``. The dynamic block follows uncached so
        per-review facts/repo instructions never invalidate the static prefix.
        """
        static_text = system_prompt
        dynamic_text = dynamic_prompt or ""
        if dynamic_prompt is None:
            static_text, dynamic_text = split_system_prompt(system_prompt)
        blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": static_text,
                "cache_control": anthropic_cache_control(options),
            }
        ]
        if dynamic_text.strip():
            blocks.append({"type": "text", "text": _dynamic_block_text(dynamic_text)})
        return blocks

    def parse_usage(self, usage: object) -> LLMUsage:
        parsed = super().parse_usage(usage)
        parsed.cached_input_tokens = int(
            getattr(usage, "cache_read_input_tokens", parsed.cached_input_tokens) or 0
        )
        parsed.cache_creation_input_tokens = int(
            getattr(usage, "cache_creation_input_tokens", parsed.cache_creation_input_tokens) or 0
        )
        return parsed

    async def structured_output(
        self,
        *,
        request: StructuredOutputRequest,
    ) -> StructuredOutputResult:
        user_key_override: str | None = request.context.get("user_provider_keys", {}).get(
            self.provider
        )
        api_key = user_key_override or get_provider_api_key(self.provider)
        client = create_async_anthropic_client(api_key)
        temp = 0.0 if request.temperature is None else float(request.temperature)
        capabilities = _model_capabilities(request.model_name)
        request_kwargs: dict[str, object] = {
            "model": request.model_name,
            "max_tokens": request.max_tokens,
            "system": self.render_anthropic_system(
                request.system_prompt,
                CacheRequestOptions(
                    cache_key=_optional_str(request.context.get("llm_prompt_cache_key")),
                    ttl=_optional_str(request.context.get("anthropic_cache_ttl")),
                    retention=_optional_str(request.context.get("openai_prompt_cache_retention")),
                    cached_content_name=_optional_str(
                        request.context.get("gemini_cached_content_name")
                    ),
                ),
            ),
            "tools": [
                {
                    "name": request.tool_name,
                    "description": request.tool_description,
                    "input_schema": request.input_schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": request.tool_name},
            "messages": request.messages,
            "timeout": 120.0,
        }
        request_kwargs.update(
            anthropic_create_kwargs(
                request.model_name,
                temperature=temp,
                effort=request.effort or _optional_effort(request.context.get("llm_effort")),
                model_role=_optional_str(request.context.get("model_role")),
                capabilities=capabilities,
            )
        )
        try:
            response = await client.messages.create(**request_kwargs)  # type: ignore[call-overload]
        except Exception as exc:
            quota_error = coerce_quota_error(exc, provider=self.provider, model=request.model_name)
            if quota_error is not None:
                raise quota_error from exc
            raise
        usage = self.parse_usage(response.usage)
        record_usage(request.context, self.provider, request.model_name, usage)
        if getattr(response, "stop_reason", None) == "refusal":
            raise RuntimeError("Anthropic model refused the structured-output request")
        for block in response.content:
            if block.type != "tool_use" or block.name != request.tool_name:
                continue
            payload = block.input
            if isinstance(payload, dict):
                return StructuredOutputResult(payload=payload, raw_response=response, usage=usage)
            raise RuntimeError(f"{request.tool_name} tool payload was not a JSON object")
        raise RuntimeError(f"Model did not return {request.tool_name} tool output")


def anthropic_cache_control(options: CacheRequestOptions | None = None) -> dict[str, str]:
    """Ephemeral ``cache_control`` payload, honoring the optional 5m/1h TTL."""
    cache_control: dict[str, str] = {"type": "ephemeral"}
    if options and options.ttl in {"5m", "1h"}:
        cache_control["ttl"] = options.ttl
    return cache_control


def _dynamic_block_text(dynamic_text: str) -> str:
    stripped = dynamic_text.strip()
    if stripped.startswith(DYNAMIC_PROMPT_MARKER):
        return stripped
    return f"{DYNAMIC_PROMPT_MARKER}\n\n{stripped}"


_COUNT_TOKENS_CACHE: dict[str, int] = {}


async def count_tokens_anthropic(
    *,
    model_name: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    api_key: str | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> int | None:
    """Exact Anthropic token count (cached by request hash); ``None`` when unavailable.

    Sonnet 5's tokenizer is ~30% denser than tiktoken cl100k, so budgets computed
    with the local estimator over-count; callers prefer this value when a key exists.
    """
    from hashlib import sha256
    import json

    key_material = json.dumps(
        {"model": model_name, "system": system_prompt, "messages": messages, "tools": tools},
        sort_keys=True,
        default=str,
    )
    cache_key = sha256(key_material.encode("utf-8")).hexdigest()
    cached = _COUNT_TOKENS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        resolved_key = api_key or get_provider_api_key("anthropic")
    except RuntimeError:
        return None
    client = create_async_anthropic_client(resolved_key)
    try:
        request_kwargs: dict[str, Any] = {
            "model": model_name,
            "system": system_prompt,
            "messages": messages,
        }
        if tools:
            request_kwargs["tools"] = tools
        response = await client.messages.count_tokens(**request_kwargs)
    except Exception:
        return None
    total = int(getattr(response, "input_tokens", 0) or 0)
    if len(_COUNT_TOKENS_CACHE) > 512:
        _COUNT_TOKENS_CACHE.clear()
    _COUNT_TOKENS_CACHE[cache_key] = total
    return total


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_effort(value: object) -> str | None:
    if isinstance(value, str) and value.strip().lower() in {"low", "medium", "high", "max"}:
        return value.strip().lower()
    return None


_ECONOMY_MODEL_ROLES = frozenset({"fast_path", "editor", "config_generator"})


def anthropic_create_kwargs(
    model_name: str,
    *,
    temperature: float | None = 0.0,
    effort: str | None = None,
    model_role: str | None = None,
    capabilities: ModelCapabilities | None = None,
) -> dict[str, Any]:
    """Build sampling/effort kwargs safe for Claude 5.x (no temperature when rejected)."""
    caps = capabilities if capabilities is not None else _model_capabilities(model_name)
    extras: dict[str, Any] = {}
    if not caps.rejects_sampling_params and temperature is not None:
        extras["temperature"] = temperature
    if not caps.supports_effort:
        return extras
    resolved_effort = effort
    if resolved_effort is None and model_role in _ECONOMY_MODEL_ROLES:
        resolved_effort = "low"
    elif resolved_effort is None and model_role in {None, "primary_review"}:
        resolved_effort = "medium"
    if resolved_effort is not None:
        extras["output_config"] = {"effort": resolved_effort}
    return extras


def _model_capabilities(model_name: str) -> ModelCapabilities:
    record = load_baseline_catalog().find_model("anthropic", model_name)
    if record is not None:
        return record.capabilities
    return ModelCapabilities(
        rejects_sampling_params=_is_claude_5_model(model_name),
        supports_effort=_is_claude_5_model(model_name),
    )


def _is_claude_5_model(model_name: str) -> bool:
    normalized = model_name.lower()
    return any(
        family in normalized
        for family in ("haiku-5", "sonnet-5", "opus-5", "fable-5", "mythos-5")
    )
