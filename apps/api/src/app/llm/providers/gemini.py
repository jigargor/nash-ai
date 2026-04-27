from __future__ import annotations

from typing import Any

import httpx

from app.llm.providers.base import BaseProviderAdapter, CacheRequestOptions


class GeminiAdapter(BaseProviderAdapter):
    provider = "gemini"

    def chat_completion_extra_kwargs(
        self,
        *,
        system_prompt: str,
        model_name: str,
        options: CacheRequestOptions | None = None,
    ) -> dict[str, Any]:
        if options and options.cached_content_name:
            return {"extra_body": {"cached_content": options.cached_content_name}}
        return {}

    async def create_cached_content(
        self,
        *,
        api_key: str,
        model_name: str,
        system_prompt: str,
        ttl_seconds: int = 3600,
    ) -> str:
        payload = {
            "model": f"models/{model_name}",
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "ttl": f"{ttl_seconds}s",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/cachedContents",
                params={"key": api_key},
                json=payload,
            )
            response.raise_for_status()
        data = response.json()
        name = data.get("name")
        if not isinstance(name, str) or not name:
            raise RuntimeError("Gemini cached content response did not include a cache name")
        return name
