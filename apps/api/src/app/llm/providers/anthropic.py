from __future__ import annotations

from typing import Any

from app.llm.providers.base import BaseProviderAdapter, CacheRequestOptions
from app.llm.types import LLMUsage


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
