from __future__ import annotations

from hashlib import sha1
from typing import Any

from app.llm.providers.base import BaseProviderAdapter, CacheRequestOptions


class OpenAIAdapter(BaseProviderAdapter):
    provider = "openai"

    def chat_completion_extra_kwargs(
        self,
        *,
        system_prompt: str,
        model_name: str,
        options: CacheRequestOptions | None = None,
    ) -> dict[str, Any]:
        cache_key = options.cache_key if options and options.cache_key else _stable_cache_key(self.provider, model_name, system_prompt)
        body: dict[str, Any] = {"prompt_cache_key": cache_key}
        if options and options.retention in {"in_memory", "24h"}:
            body["prompt_cache_retention"] = options.retention
        return {"extra_body": body}


def _stable_cache_key(provider: str, model_name: str, system_prompt: str) -> str:
    digest = sha1(system_prompt.encode("utf-8"), usedforsecurity=False).hexdigest()[:24]
    return f"{provider}:{model_name}:{digest}"
