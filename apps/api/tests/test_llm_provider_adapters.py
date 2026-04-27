from types import SimpleNamespace

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
