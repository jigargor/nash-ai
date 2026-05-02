"""Tests for record_usage() from app.llm.providers.base."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.llm.providers import get_provider_adapter, record_usage
from app.llm.types import LLMUsage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_usage(
    input_tokens: int = 100,
    output_tokens: int = 25,
    total_tokens: int = 0,
    cached_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> LLMUsage:
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens or (input_tokens + output_tokens),
        cached_input_tokens=cached_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
    )


# ---------------------------------------------------------------------------
# Basic accumulation
# ---------------------------------------------------------------------------


def test_record_usage_accumulates_tokens() -> None:
    context: dict[str, Any] = {}

    usage1 = _make_usage(input_tokens=100, output_tokens=20)
    usage2 = _make_usage(input_tokens=200, output_tokens=30)

    record_usage(context, "openai", "gpt-5", usage1)
    record_usage(context, "openai", "gpt-5", usage2)

    assert context["input_tokens"] == 300
    assert context["output_tokens"] == 50
    assert context["tokens_used"] == 350


def test_record_usage_appends_to_llm_usage_list() -> None:
    context: dict[str, Any] = {}

    record_usage(context, "anthropic", "claude-sonnet-4-5", _make_usage(50, 10))
    record_usage(context, "openai", "gpt-5-mini", _make_usage(80, 15))

    entries = context["llm_usage"]
    assert isinstance(entries, list)
    assert len(entries) == 2
    assert entries[0]["provider"] == "anthropic"
    assert entries[0]["model"] == "claude-sonnet-4-5"
    assert entries[1]["provider"] == "openai"
    assert entries[1]["model"] == "gpt-5-mini"


def test_record_usage_entry_shape() -> None:
    context: dict[str, Any] = {}
    usage = _make_usage(
        input_tokens=300,
        output_tokens=40,
        cached_input_tokens=100,
        cache_creation_input_tokens=50,
    )

    record_usage(context, "anthropic", "claude-opus-4-5", usage)

    entry = context["llm_usage"][0]
    assert entry == {
        "provider": "anthropic",
        "model": "claude-opus-4-5",
        "input_tokens": 300,
        "output_tokens": 40,
        "total_tokens": 340,
        "cached_input_tokens": 100,
        "cache_creation_input_tokens": 50,
    }


# ---------------------------------------------------------------------------
# Cached tokens
# ---------------------------------------------------------------------------


def test_record_usage_handles_cached_tokens() -> None:
    context: dict[str, Any] = {}
    usage = _make_usage(input_tokens=1000, output_tokens=100, cached_input_tokens=500)

    record_usage(context, "openai", "gpt-5", usage)

    entry = context["llm_usage"][0]
    assert entry["cached_input_tokens"] == 500
    assert entry["cache_creation_input_tokens"] == 0


def test_record_usage_handles_cache_creation_tokens() -> None:
    context: dict[str, Any] = {}
    usage = _make_usage(
        input_tokens=800, output_tokens=80,
        cached_input_tokens=0, cache_creation_input_tokens=400
    )

    record_usage(context, "anthropic", "claude-sonnet-4-5", usage)

    entry = context["llm_usage"][0]
    assert entry["cache_creation_input_tokens"] == 400


# ---------------------------------------------------------------------------
# Empty / pre-populated context
# ---------------------------------------------------------------------------


def test_record_usage_with_empty_context() -> None:
    context: dict[str, Any] = {}

    record_usage(context, "gemini", "gemini-2.5-flash", _make_usage())

    assert "input_tokens" in context
    assert "output_tokens" in context
    assert "tokens_used" in context
    assert "llm_usage" in context


def test_record_usage_accumulates_onto_existing_context_values() -> None:
    context: dict[str, Any] = {
        "input_tokens": 50,
        "output_tokens": 10,
        "tokens_used": 60,
    }

    record_usage(context, "openai", "gpt-5", _make_usage(100, 20))

    assert context["input_tokens"] == 150
    assert context["output_tokens"] == 30
    assert context["tokens_used"] == 180


def test_record_usage_creates_llm_usage_list_when_absent() -> None:
    context: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "tokens_used": 0}
    assert "llm_usage" not in context

    record_usage(context, "openai", "gpt-5-mini", _make_usage(10, 5))

    assert isinstance(context["llm_usage"], list)
    assert len(context["llm_usage"]) == 1


# ---------------------------------------------------------------------------
# parse_usage + record_usage round-trip via real adapter
# ---------------------------------------------------------------------------


def test_record_usage_round_trip_openai() -> None:
    adapter = get_provider_adapter("openai")
    raw_usage = SimpleNamespace(
        prompt_tokens=250,
        completion_tokens=75,
        total_tokens=325,
        prompt_tokens_details=SimpleNamespace(cached_tokens=128),
    )

    parsed = adapter.parse_usage(raw_usage)
    context: dict[str, Any] = {}
    record_usage(context, "openai", "gpt-5", parsed)

    assert context["input_tokens"] == 250
    assert context["output_tokens"] == 75
    assert context["tokens_used"] == 325
    assert context["llm_usage"][0]["cached_input_tokens"] == 128


def test_record_usage_round_trip_anthropic() -> None:
    adapter = get_provider_adapter("anthropic")
    raw_usage = SimpleNamespace(
        input_tokens=400,
        output_tokens=60,
        cache_read_input_tokens=200,
        cache_creation_input_tokens=100,
    )

    parsed = adapter.parse_usage(raw_usage)
    context: dict[str, Any] = {}
    record_usage(context, "anthropic", "claude-sonnet-4-5", parsed)

    entry = context["llm_usage"][0]
    assert entry["cached_input_tokens"] == 200
    assert entry["cache_creation_input_tokens"] == 100


def test_record_usage_round_trip_gemini() -> None:
    adapter = get_provider_adapter("gemini")
    raw_usage = SimpleNamespace(
        prompt_token_count=2048,
        candidates_token_count=256,
        total_token_count=2304,
        cached_content_token_count=1024,
    )

    parsed = adapter.parse_usage(raw_usage)
    context: dict[str, Any] = {}
    record_usage(context, "gemini", "gemini-2.5-flash", parsed)

    assert context["input_tokens"] == 2048
    assert context["llm_usage"][0]["cached_input_tokens"] == 1024
