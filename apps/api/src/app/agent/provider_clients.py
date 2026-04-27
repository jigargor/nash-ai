import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openai import AsyncOpenAI

from app.agent.review_config import ModelProvider
from app.config import settings

GEMINI_OPENAI_COMPAT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def get_provider_api_key(
    provider: ModelProvider,
    *,
    user_key_override: str | None = None,
) -> str:
    if user_key_override:
        return user_key_override
    if provider == "anthropic":
        if settings.anthropic_api_key:
            return settings.anthropic_api_key
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    if provider == "openai":
        if settings.openai_api_key:
            return settings.openai_api_key
        raise RuntimeError("OPENAI_API_KEY is not configured")
    if provider == "gemini":
        if settings.gemini_api_key:
            return settings.gemini_api_key
        raise RuntimeError("GEMINI_API_KEY is not configured")
    raise RuntimeError(f"Unsupported LLM provider: {provider}")


def create_openai_compatible_client(
    provider: ModelProvider,
    *,
    user_key_override: str | None = None,
) -> "AsyncOpenAI":
    try:
        from openai import AsyncOpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "openai package is required for OpenAI/Gemini model providers. "
            "Run `uv sync` (or `uv add openai`) in apps/api."
        ) from exc
    api_key = get_provider_api_key(provider, user_key_override=user_key_override)
    if provider == "gemini":
        return AsyncOpenAI(api_key=api_key, base_url=GEMINI_OPENAI_COMPAT_BASE_URL)
    if provider != "openai":
        raise RuntimeError(f"Provider {provider} does not use the OpenAI-compatible client")
    return AsyncOpenAI(api_key=api_key)


def anthropic_tools_to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": str(tool["name"]),
                "description": str(tool["description"]),
                "parameters": tool["input_schema"],
            },
        }
        for tool in tools
    ]


def parse_openai_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_arguments)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return {}
    return {}
