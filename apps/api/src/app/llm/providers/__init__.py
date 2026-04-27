from app.llm.providers.anthropic import AnthropicAdapter
from app.llm.providers.base import CacheRequestOptions, ProviderAdapter, record_usage
from app.llm.providers.gemini import GeminiAdapter
from app.llm.providers.openai import OpenAIAdapter

_ADAPTERS: dict[str, ProviderAdapter] = {
    "anthropic": AnthropicAdapter(),
    "openai": OpenAIAdapter(),
    "gemini": GeminiAdapter(),
}


def get_provider_adapter(provider: str) -> ProviderAdapter:
    try:
        return _ADAPTERS[provider]
    except KeyError as exc:
        raise RuntimeError(f"No LLM provider adapter registered for {provider}") from exc


def registered_provider_ids() -> set[str]:
    return set(_ADAPTERS)


__all__ = ["CacheRequestOptions", "ProviderAdapter", "get_provider_adapter", "record_usage", "registered_provider_ids"]
