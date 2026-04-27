from __future__ import annotations

import builtins
import types
from typing import Any

import pytest

from app.agent import provider_clients
from app.config import settings


def test_get_provider_api_key_returns_expected_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "anth-key")
    monkeypatch.setattr(settings, "openai_api_key", "openai-key")
    monkeypatch.setattr(settings, "gemini_api_key", "gemini-key")

    assert provider_clients.get_provider_api_key("anthropic") == "anth-key"
    assert provider_clients.get_provider_api_key("openai") == "openai-key"
    assert provider_clients.get_provider_api_key("gemini") == "gemini-key"


def test_get_provider_api_key_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", None)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        provider_clients.get_provider_api_key("anthropic")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        provider_clients.get_provider_api_key("openai")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        provider_clients.get_provider_api_key("gemini")


def test_create_openai_compatible_client_selects_base_url_for_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "openai-key")
    monkeypatch.setattr(settings, "gemini_api_key", "gemini-key")

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    fake_module = types.SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI)
    monkeypatch.setitem(__import__("sys").modules, "openai", fake_module)

    openai_client = provider_clients.create_openai_compatible_client("openai")
    assert isinstance(openai_client, _FakeAsyncOpenAI)
    assert openai_client.kwargs == {"api_key": "openai-key"}

    gemini_client = provider_clients.create_openai_compatible_client("gemini")
    assert isinstance(gemini_client, _FakeAsyncOpenAI)
    assert gemini_client.kwargs["api_key"] == "gemini-key"
    assert gemini_client.kwargs["base_url"] == provider_clients.GEMINI_OPENAI_COMPAT_BASE_URL


def test_create_openai_compatible_client_raises_when_openai_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "openai-key")
    monkeypatch.delitem(__import__("sys").modules, "openai", raising=False)
    original_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "openai":
            raise ModuleNotFoundError("No module named 'openai'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    with pytest.raises(RuntimeError, match="openai package is required"):
        provider_clients.create_openai_compatible_client("openai")


def test_anthropic_tools_and_argument_parsing() -> None:
    tools = [
        {
            "name": "search",
            "description": "Search code",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
        }
    ]
    converted = provider_clients.anthropic_tools_to_openai_tools(tools)
    assert converted[0]["type"] == "function"
    assert converted[0]["function"]["name"] == "search"

    assert provider_clients.parse_openai_tool_arguments('{"query":"abc"}') == {"query": "abc"}
    assert provider_clients.parse_openai_tool_arguments("not-json") == {}
    assert provider_clients.parse_openai_tool_arguments('["array"]') == {}
