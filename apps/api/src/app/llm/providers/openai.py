from __future__ import annotations

from hashlib import sha1
from typing import Any

from app.agent.provider_clients import (
    anthropic_tools_to_openai_tools,
    create_openai_compatible_client,
    parse_openai_tool_arguments,
)
from app.llm.errors import coerce_quota_error
from app.llm.providers.base import (
    BaseProviderAdapter,
    CacheRequestOptions,
    StructuredOutputRequest,
    StructuredOutputResult,
    record_usage,
)


class OpenAIAdapter(BaseProviderAdapter):
    provider = "openai"

    def chat_completion_extra_kwargs(
        self,
        *,
        system_prompt: str,
        model_name: str,
        options: CacheRequestOptions | None = None,
    ) -> dict[str, Any]:
        cache_key = (
            options.cache_key
            if options and options.cache_key
            else _stable_cache_key(self.provider, model_name, system_prompt)
        )
        body: dict[str, Any] = {"prompt_cache_key": cache_key}
        if options and options.retention in {"in_memory", "24h"}:
            body["prompt_cache_retention"] = options.retention
        return {"extra_body": body}

    async def structured_output(
        self,
        *,
        request: StructuredOutputRequest,
    ) -> StructuredOutputResult:
        client = create_openai_compatible_client(self.provider)
        messages = list(request.messages)
        has_system = bool(messages and messages[0].get("role") == "system")
        if not has_system:
            messages.insert(0, {"role": "system", "content": request.system_prompt})
        openai_messages_any: Any = messages
        openai_tools_any: Any = anthropic_tools_to_openai_tools(
            [
                {
                    "name": request.tool_name,
                    "description": request.tool_description,
                    "input_schema": request.input_schema,
                }
            ]
        )
        openai_tool_choice_any: Any = {"type": "function", "function": {"name": request.tool_name}}
        try:
            response = await client.chat.completions.create(
                model=request.model_name,
                temperature=request.temperature if request.temperature is not None else 0,
                messages=openai_messages_any,
                tools=openai_tools_any,
                tool_choice=openai_tool_choice_any,
                **self.chat_completion_extra_kwargs(
                    system_prompt=request.system_prompt,
                    model_name=request.model_name,
                    options=CacheRequestOptions(
                        cache_key=_optional_str(request.context.get("llm_prompt_cache_key")),
                        ttl=_optional_str(request.context.get("anthropic_cache_ttl")),
                        retention=_optional_str(request.context.get("openai_prompt_cache_retention")),
                        cached_content_name=_optional_str(
                            request.context.get("gemini_cached_content_name")
                        ),
                    ),
                ),
            )
        except Exception as exc:
            quota_error = coerce_quota_error(exc, provider=self.provider, model=request.model_name)
            if quota_error is not None:
                raise quota_error from exc
            raise
        usage = self.parse_usage(response.usage)
        record_usage(request.context, self.provider, request.model_name, usage)
        if not response.choices:
            raise RuntimeError(f"Model did not return {request.tool_name} output")
        message = response.choices[0].message
        for call in list(message.tool_calls or []):
            function_obj = getattr(call, "function", None)
            if getattr(function_obj, "name", None) != request.tool_name:
                continue
            arguments = getattr(function_obj, "arguments", "{}")
            payload = parse_openai_tool_arguments(arguments if isinstance(arguments, str) else "{}")
            return StructuredOutputResult(payload=payload, raw_response=response, usage=usage)
        raise RuntimeError(f"Model did not return {request.tool_name} tool output")


def _stable_cache_key(provider: str, model_name: str, system_prompt: str) -> str:
    digest = sha1(system_prompt.encode("utf-8"), usedforsecurity=False).hexdigest()[:24]
    return f"{provider}:{model_name}:{digest}"


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
