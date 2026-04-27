from __future__ import annotations

from typing import Any

from app.agent.provider_clients import get_provider_api_key
from app.llm.providers.base import (
    BaseProviderAdapter,
    CacheRequestOptions,
    StructuredOutputRequest,
    StructuredOutputResult,
    record_usage,
)
from app.llm.types import LLMUsage
from app.observability import create_async_anthropic_client


class AnthropicAdapter(BaseProviderAdapter):
    provider = "anthropic"

    def render_anthropic_system(self, system_prompt: str, options: CacheRequestOptions | None = None) -> list[dict[str, Any]]:
        cache_control: dict[str, str] = {"type": "ephemeral"}
        if options and options.ttl in {"5m", "1h"}:
            cache_control["ttl"] = options.ttl
        return [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": cache_control,
            }
        ]

    def parse_usage(self, usage: object) -> LLMUsage:
        parsed = super().parse_usage(usage)
        parsed.cached_input_tokens = int(getattr(usage, "cache_read_input_tokens", parsed.cached_input_tokens) or 0)
        parsed.cache_creation_input_tokens = int(
            getattr(usage, "cache_creation_input_tokens", parsed.cache_creation_input_tokens) or 0
        )
        return parsed

    async def structured_output(
        self,
        *,
        request: StructuredOutputRequest,
    ) -> StructuredOutputResult:
        client = create_async_anthropic_client(get_provider_api_key(self.provider))
        response = await client.messages.create(  # type: ignore[call-overload]
            model=request.model_name,
            max_tokens=request.max_tokens,
            system=self.render_anthropic_system(
                request.system_prompt,
                CacheRequestOptions(
                    cache_key=_optional_str(request.context.get("llm_prompt_cache_key")),
                    ttl=_optional_str(request.context.get("anthropic_cache_ttl")),
                    retention=_optional_str(request.context.get("openai_prompt_cache_retention")),
                    cached_content_name=_optional_str(request.context.get("gemini_cached_content_name")),
                ),
            ),
            tools=[
                {
                    "name": request.tool_name,
                    "description": request.tool_description,
                    "input_schema": request.input_schema,
                }
            ],
            tool_choice={"type": "tool", "name": request.tool_name},
            messages=request.messages,
        )
        usage = self.parse_usage(response.usage)
        record_usage(request.context, self.provider, request.model_name, usage)
        for block in response.content:
            if block.type != "tool_use" or block.name != request.tool_name:
                continue
            payload = block.input
            if isinstance(payload, dict):
                return StructuredOutputResult(payload=payload, raw_response=response, usage=usage)
            raise RuntimeError(f"{request.tool_name} tool payload was not a JSON object")
        raise RuntimeError(f"Model did not return {request.tool_name} tool output")


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
