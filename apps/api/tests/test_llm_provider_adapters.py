from types import SimpleNamespace

import pytest

from app.llm.providers import StructuredOutputRequest
from app.llm.providers import get_provider_adapter, record_usage


def test_anthropic_adapter_parses_cache_usage_and_renders_cache_control() -> None:
    adapter = get_provider_adapter("anthropic")
    usage = SimpleNamespace(
        input_tokens=10,
        output_tokens=5,
        cache_read_input_tokens=100,
        cache_creation_input_tokens=25,
    )

    parsed = adapter.parse_usage(usage)
    system = adapter.render_anthropic_system("system")

    assert parsed.input_tokens == 10
    assert parsed.output_tokens == 5
    assert parsed.cached_input_tokens == 100
    assert parsed.cache_creation_input_tokens == 25
    assert system[0]["cache_control"]["type"] == "ephemeral"


def test_openai_adapter_parses_cached_prompt_tokens_and_sets_cache_key() -> None:
    adapter = get_provider_adapter("openai")
    usage = SimpleNamespace(
        prompt_tokens=2000,
        completion_tokens=100,
        total_tokens=2100,
        prompt_tokens_details=SimpleNamespace(cached_tokens=1024),
    )

    parsed = adapter.parse_usage(usage)
    kwargs = adapter.chat_completion_extra_kwargs(system_prompt="stable", model_name="gpt-5.2")

    assert parsed.input_tokens == 2000
    assert parsed.cached_input_tokens == 1024
    assert kwargs["extra_body"]["prompt_cache_key"].startswith("openai:gpt-5.2:")


def test_gemini_adapter_parses_cached_content_tokens() -> None:
    adapter = get_provider_adapter("gemini")
    usage = SimpleNamespace(
        prompt_token_count=4096,
        candidates_token_count=256,
        total_token_count=4352,
        cached_content_token_count=2048,
    )

    parsed = adapter.parse_usage(usage)

    assert parsed.input_tokens == 4096
    assert parsed.output_tokens == 256
    assert parsed.cached_input_tokens == 2048


def test_record_usage_updates_context_and_preserves_cache_metrics() -> None:
    adapter = get_provider_adapter("openai")
    parsed = adapter.parse_usage(
        SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=25,
            total_tokens=125,
            prompt_tokens_details=SimpleNamespace(cached_tokens=50),
        )
    )
    context: dict[str, object] = {}

    record_usage(context, "openai", "gpt-5.2", parsed)

    assert context["input_tokens"] == 100
    assert context["output_tokens"] == 25
    assert context["tokens_used"] == 125
    assert context["llm_usage"] == [
        {
            "provider": "openai",
            "model": "gpt-5.2",
            "input_tokens": 100,
            "output_tokens": 25,
            "total_tokens": 125,
            "cached_input_tokens": 50,
            "cache_creation_input_tokens": 0,
        }
    ]


@pytest.mark.anyio
async def test_anthropic_structured_output_extracts_tool_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm.providers import anthropic as anthropic_module

    class _FakeClient:
        class _Messages:
            @staticmethod
            async def create(**_kwargs: object) -> object:
                return SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=7, output_tokens=3, total_tokens=10),
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            name="submit_review",
                            input={"summary": "ok", "findings": []},
                        )
                    ],
                )

        messages = _Messages()

    monkeypatch.setattr(
        anthropic_module, "create_async_anthropic_client", lambda _api_key: _FakeClient()
    )
    monkeypatch.setattr(anthropic_module, "get_provider_api_key", lambda _provider: "test")

    adapter = get_provider_adapter("anthropic")
    context: dict[str, object] = {}
    out = await adapter.structured_output(
        request=StructuredOutputRequest(
            model_name="claude-sonnet-4-5",
            system_prompt="system",
            messages=[{"role": "user", "content": "go"}],
            tool_name="submit_review",
            tool_description="Submit review",
            input_schema={"type": "object"},
            context=context,
            max_tokens=512,
            temperature=0,
        )
    )
    assert out.payload == {"summary": "ok", "findings": []}
    assert context["llm_usage"] == [
        {
            "provider": "anthropic",
            "model": "claude-sonnet-4-5",
            "input_tokens": 7,
            "output_tokens": 3,
            "total_tokens": 10,
            "cached_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["openai", "gemini"])
async def test_openai_compatible_structured_output_extracts_tool_payload(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    from app.llm.providers import openai as openai_module

    class _FakeCompletions:
        @staticmethod
        async def create(**_kwargs: object) -> object:
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=9, completion_tokens=5, total_tokens=14),
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        name="submit_review",
                                        arguments='{"summary":"ok","findings":[]}',
                                    )
                                )
                            ]
                        )
                    )
                ],
            )

    class _FakeClient:
        chat = SimpleNamespace(completions=_FakeCompletions())

    monkeypatch.setattr(
        openai_module,
        "create_openai_compatible_client",
        lambda _provider, user_key_override=None: _FakeClient(),  # noqa: ARG005
    )

    adapter = get_provider_adapter(provider)
    context: dict[str, object] = {}
    out = await adapter.structured_output(
        request=StructuredOutputRequest(
            model_name="model",
            system_prompt="system",
            messages=[{"role": "user", "content": "go"}],
            tool_name="submit_review",
            tool_description="Submit review",
            input_schema={"type": "object"},
            context=context,
            max_tokens=512,
            temperature=0,
        )
    )
    assert out.payload == {"summary": "ok", "findings": []}
    assert context["llm_usage"] == [
        {
            "provider": provider,
            "model": "model",
            "input_tokens": 9,
            "output_tokens": 5,
            "total_tokens": 14,
            "cached_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
    ]


@pytest.mark.anyio
async def test_openai_compatible_adapter_prefers_user_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm.providers import openai as openai_module

    captured_key: str | None = None

    class _FakeCompletions:
        @staticmethod
        async def create(**_kwargs: object) -> object:
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        name="submit_review",
                                        arguments='{"summary":"ok","findings":[]}',
                                    )
                                )
                            ]
                        )
                    )
                ],
            )

    class _FakeClient:
        chat = SimpleNamespace(completions=_FakeCompletions())

    def fake_client_factory(_provider: str, user_key_override: str | None = None) -> object:
        nonlocal captured_key
        captured_key = user_key_override
        return _FakeClient()

    monkeypatch.setattr(openai_module, "create_openai_compatible_client", fake_client_factory)

    adapter = get_provider_adapter("openai")
    context: dict[str, object] = {"user_provider_keys": {"openai": "user-openai-key"}}
    await adapter.structured_output(
        request=StructuredOutputRequest(
            model_name="gpt-5-mini",
            system_prompt="system",
            messages=[{"role": "user", "content": "go"}],
            tool_name="submit_review",
            tool_description="Submit review",
            input_schema={"type": "object"},
            context=context,
            max_tokens=256,
            temperature=0,
        )
    )

    assert captured_key == "user-openai-key"


# ---------------------------------------------------------------------------
# parse_usage edge cases (BaseProviderAdapter)
# ---------------------------------------------------------------------------


def test_parse_usage_handles_empty_object() -> None:
    adapter = get_provider_adapter("openai")
    parsed = adapter.parse_usage(SimpleNamespace())

    assert parsed.input_tokens == 0
    assert parsed.output_tokens == 0
    assert parsed.total_tokens == 0
    assert parsed.cached_input_tokens == 0
    assert parsed.cache_creation_input_tokens == 0


def test_parse_usage_handles_float_tokens() -> None:
    adapter = get_provider_adapter("openai")
    parsed = adapter.parse_usage(
        SimpleNamespace(
            prompt_tokens=1500.0,
            completion_tokens=200.0,
            total_tokens=1700.0,
            prompt_tokens_details=None,
        )
    )

    assert parsed.input_tokens == 1500
    assert parsed.output_tokens == 200
    assert parsed.total_tokens == 1700


def test_parse_usage_handles_none_fields() -> None:
    adapter = get_provider_adapter("anthropic")
    parsed = adapter.parse_usage(
        SimpleNamespace(
            input_tokens=None,
            output_tokens=None,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=None,
        )
    )

    assert parsed.input_tokens == 0
    assert parsed.output_tokens == 0
    assert parsed.cached_input_tokens == 0
    assert parsed.cache_creation_input_tokens == 0


def test_parse_usage_uses_total_tokens_when_provided() -> None:
    adapter = get_provider_adapter("gemini")
    parsed = adapter.parse_usage(
        SimpleNamespace(
            prompt_token_count=100,
            candidates_token_count=50,
            total_token_count=200,
        )
    )

    assert parsed.input_tokens == 100
    assert parsed.output_tokens == 50
    assert parsed.total_tokens == 200


def test_parse_usage_fills_total_when_missing() -> None:
    adapter = get_provider_adapter("openai")
    parsed = adapter.parse_usage(
        SimpleNamespace(
            prompt_tokens=80,
            completion_tokens=20,
        )
    )

    assert parsed.total_tokens == 100


# ---------------------------------------------------------------------------
# Anthropic cache TTL variants
# ---------------------------------------------------------------------------


def test_anthropic_cache_ttl_5m() -> None:
    adapter = get_provider_adapter("anthropic")
    from app.llm.providers.base import CacheRequestOptions

    system = adapter.render_anthropic_system(
        "my system prompt", CacheRequestOptions(ttl="5m")
    )

    assert system[0]["cache_control"]["type"] == "ephemeral"
    assert system[0]["cache_control"]["ttl"] == "5m"


def test_anthropic_cache_ttl_1h() -> None:
    adapter = get_provider_adapter("anthropic")
    from app.llm.providers.base import CacheRequestOptions

    system = adapter.render_anthropic_system(
        "my system prompt", CacheRequestOptions(ttl="1h")
    )

    assert system[0]["cache_control"]["type"] == "ephemeral"
    assert system[0]["cache_control"]["ttl"] == "1h"


def test_anthropic_cache_ttl_invalid_not_propagated() -> None:
    adapter = get_provider_adapter("anthropic")
    from app.llm.providers.base import CacheRequestOptions

    system = adapter.render_anthropic_system(
        "my system prompt", CacheRequestOptions(ttl="99h")
    )

    assert system[0]["cache_control"]["type"] == "ephemeral"
    assert "ttl" not in system[0]["cache_control"]


def test_anthropic_cache_ttl_no_options() -> None:
    adapter = get_provider_adapter("anthropic")
    system = adapter.render_anthropic_system("system prompt", None)

    assert system[0]["cache_control"]["type"] == "ephemeral"
    assert "ttl" not in system[0]["cache_control"]


def test_anthropic_parse_usage_cache_creation_tokens() -> None:
    adapter = get_provider_adapter("anthropic")
    parsed = adapter.parse_usage(
        SimpleNamespace(
            input_tokens=500,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=300,
        )
    )

    assert parsed.cache_creation_input_tokens == 300
    assert parsed.cached_input_tokens == 0


# ---------------------------------------------------------------------------
# OpenAI nested cached tokens
# ---------------------------------------------------------------------------


def test_openai_nested_cached_tokens_parsing() -> None:
    adapter = get_provider_adapter("openai")
    parsed = adapter.parse_usage(
        SimpleNamespace(
            prompt_tokens=3000,
            completion_tokens=150,
            total_tokens=3150,
            prompt_tokens_details=SimpleNamespace(cached_tokens=2048),
        )
    )

    assert parsed.cached_input_tokens == 2048


def test_openai_nested_cached_tokens_zero_falls_back() -> None:
    adapter = get_provider_adapter("openai")
    # When nested cached_tokens == 0 and cache_read_input_tokens is also not present → 0
    parsed = adapter.parse_usage(
        SimpleNamespace(
            prompt_tokens=500,
            completion_tokens=50,
            total_tokens=550,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        )
    )

    assert parsed.cached_input_tokens == 0


def test_openai_cache_key_is_deterministic() -> None:
    adapter = get_provider_adapter("openai")
    kwargs1 = adapter.chat_completion_extra_kwargs(
        system_prompt="same prompt", model_name="gpt-5"
    )
    kwargs2 = adapter.chat_completion_extra_kwargs(
        system_prompt="same prompt", model_name="gpt-5"
    )

    assert kwargs1["extra_body"]["prompt_cache_key"] == kwargs2["extra_body"]["prompt_cache_key"]


def test_openai_cache_key_differs_per_model() -> None:
    adapter = get_provider_adapter("openai")
    kwargs_a = adapter.chat_completion_extra_kwargs(
        system_prompt="same", model_name="gpt-5"
    )
    kwargs_b = adapter.chat_completion_extra_kwargs(
        system_prompt="same", model_name="gpt-5-mini"
    )

    assert kwargs_a["extra_body"]["prompt_cache_key"] != kwargs_b["extra_body"]["prompt_cache_key"]


# ---------------------------------------------------------------------------
# Gemini: inherits OpenAI structured_output path + cached content kwargs
# ---------------------------------------------------------------------------


def test_gemini_cached_content_tokens() -> None:
    adapter = get_provider_adapter("gemini")
    parsed = adapter.parse_usage(
        SimpleNamespace(
            prompt_token_count=8192,
            candidates_token_count=512,
            total_token_count=8704,
            cached_content_token_count=4096,
        )
    )

    assert parsed.cached_input_tokens == 4096


def test_gemini_inherits_openai_structured_output() -> None:
    """GeminiAdapter subclasses OpenAIAdapter — structured_output is the same code path."""
    from app.llm.providers.gemini import GeminiAdapter
    from app.llm.providers.openai import OpenAIAdapter

    assert issubclass(GeminiAdapter, OpenAIAdapter)


def test_gemini_chat_completion_extra_kwargs_with_cached_content() -> None:
    adapter = get_provider_adapter("gemini")
    from app.llm.providers.base import CacheRequestOptions

    kwargs = adapter.chat_completion_extra_kwargs(
        system_prompt="prompt",
        model_name="gemini-2.5-flash",
        options=CacheRequestOptions(cached_content_name="cachedContents/abc123"),
    )

    assert kwargs["extra_body"]["cached_content"] == "cachedContents/abc123"


def test_gemini_chat_completion_extra_kwargs_without_cached_content_is_empty() -> None:
    adapter = get_provider_adapter("gemini")

    kwargs = adapter.chat_completion_extra_kwargs(
        system_prompt="prompt", model_name="gemini-2.5-flash"
    )

    assert kwargs == {}


@pytest.mark.anyio
async def test_anthropic_structured_output_raises_on_missing_tool_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm.providers import anthropic as anthropic_module

    class _FakeClient:
        class _Messages:
            @staticmethod
            async def create(**_kwargs: object) -> object:
                return SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=5, output_tokens=2, total_tokens=7),
                    content=[
                        SimpleNamespace(type="text", text="I can't do that"),
                    ],
                )

        messages = _Messages()

    monkeypatch.setattr(
        anthropic_module, "create_async_anthropic_client", lambda _api_key: _FakeClient()
    )
    monkeypatch.setattr(anthropic_module, "get_provider_api_key", lambda _provider: "test")

    adapter = get_provider_adapter("anthropic")
    import pytest as _pytest

    with _pytest.raises(RuntimeError, match="did not return"):
        await adapter.structured_output(
            request=StructuredOutputRequest(
                model_name="claude-sonnet-4-5",
                system_prompt="system",
                messages=[{"role": "user", "content": "go"}],
                tool_name="submit_review",
                tool_description="desc",
                input_schema={"type": "object"},
                context={},
                max_tokens=256,
                temperature=0,
            )
        )


@pytest.mark.anyio
async def test_openai_structured_output_raises_on_no_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.llm.providers import openai as openai_module

    class _FakeCompletions:
        @staticmethod
        async def create(**_kwargs: object) -> object:
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(tool_calls=None)
                    )
                ],
            )

    class _FakeClient:
        chat = SimpleNamespace(completions=_FakeCompletions())

    monkeypatch.setattr(
        openai_module,
        "create_openai_compatible_client",
        lambda _provider, user_key_override=None: _FakeClient(),  # noqa: ARG005
    )

    adapter = get_provider_adapter("openai")
    import pytest as _pytest

    with _pytest.raises(RuntimeError, match="did not return"):
        await adapter.structured_output(
            request=StructuredOutputRequest(
                model_name="gpt-5",
                system_prompt="system",
                messages=[{"role": "user", "content": "go"}],
                tool_name="submit_review",
                tool_description="desc",
                input_schema={"type": "object"},
                context={},
                max_tokens=256,
                temperature=0,
            )
        )


@pytest.mark.anyio
async def test_openai_structured_output_multiple_tool_calls_uses_first_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When multiple tool_calls are returned, the correct tool name is matched."""
    from app.llm.providers import openai as openai_module

    class _FakeCompletions:
        @staticmethod
        async def create(**_kwargs: object) -> object:
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        name="other_tool",
                                        arguments='{"x": 1}',
                                    )
                                ),
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        name="submit_review",
                                        arguments='{"summary":"found","findings":[]}',
                                    )
                                ),
                            ]
                        )
                    )
                ],
            )

    class _FakeClient:
        chat = SimpleNamespace(completions=_FakeCompletions())

    monkeypatch.setattr(
        openai_module,
        "create_openai_compatible_client",
        lambda _provider, user_key_override=None: _FakeClient(),  # noqa: ARG005
    )

    adapter = get_provider_adapter("openai")
    out = await adapter.structured_output(
        request=StructuredOutputRequest(
            model_name="gpt-5",
            system_prompt="system",
            messages=[{"role": "user", "content": "go"}],
            tool_name="submit_review",
            tool_description="desc",
            input_schema={"type": "object"},
            context={},
            max_tokens=256,
            temperature=0,
        )
    )

    assert out.payload == {"summary": "found", "findings": []}
