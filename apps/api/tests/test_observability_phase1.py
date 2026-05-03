from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.config import settings as app_settings
from app.llm.providers.base import record_usage
from app.llm.types import LLMUsage as ProviderLLMUsage
from app.observability.events import LLMUsage as ObserverLLMUsage
from app.observability.observer import LLMObserver, configure_observer, get_observer, reset_observer
from app.observability.redaction import sanitize_payload
from app.observability.sinks import InMemoryTestSink, LangfuseSink
from app.queue import worker as worker_module


@dataclass
class _RaisingSink:
    def on_review_start(self, event: Any) -> None:
        raise RuntimeError("boom")

    def on_review_end(self, event: Any) -> None:
        raise RuntimeError("boom")

    def on_stage_start(self, event: Any) -> None:
        raise RuntimeError("boom")

    def on_stage_end(self, event: Any) -> None:
        raise RuntimeError("boom")

    def on_generation(self, event: Any) -> None:
        raise RuntimeError("boom")

    def on_tool_call(self, event: Any) -> None:
        raise RuntimeError("boom")

    def on_validation(self, event: Any) -> None:
        raise RuntimeError("boom")

    def on_context_build(self, event: Any) -> None:
        raise RuntimeError("boom")

    def on_error(self, event: Any) -> None:
        raise RuntimeError("boom")

    def flush(self) -> None:
        return


def test_observer_disabled_emits_nothing() -> None:
    sink = InMemoryTestSink()
    observer = LLMObserver(sinks=[sink], enabled=False)
    trace = observer.start_review_trace(review_id=1, installation_id=2, run_id="run-1")
    stage = observer.start_stage(trace, "primary")
    observer.record_generation(
        stage,
        provider="anthropic",
        model="claude-sonnet-4-5",
        usage=ObserverLLMUsage(input_tokens=10, output_tokens=5),
        latency_ms=12,
    )
    observer.finish_stage(stage, status="success")
    observer.finish_review_trace(trace, status="success")
    assert sink.events == []


def test_sink_failure_does_not_raise() -> None:
    observer = LLMObserver(sinks=[_RaisingSink()], enabled=True)
    trace = observer.start_review_trace(review_id=3, installation_id=4, run_id="run-2")
    stage = observer.start_stage(trace, "fast_path")
    observer.record_generation(
        stage,
        provider="openai",
        model="gpt-5.5",
        usage=ObserverLLMUsage(input_tokens=7, output_tokens=9),
        latency_ms=18,
    )
    observer.finish_stage(stage, status="success")
    observer.finish_review_trace(trace, status="success")


def test_one_generation_call_produces_one_generation_event() -> None:
    sink = InMemoryTestSink()
    observer = LLMObserver(sinks=[sink], enabled=True)
    trace = observer.start_review_trace(review_id=5, installation_id=6, run_id="run-3")
    stage = observer.start_stage(trace, "primary_review")
    observer.record_generation(
        stage,
        provider="anthropic",
        model="claude-sonnet-4-5",
        usage=ObserverLLMUsage(input_tokens=11, output_tokens=4),
        latency_ms=11,
    )
    generation_events = [event for event in sink.events if event["event"] == "generation"]
    assert len(generation_events) == 1


def test_redaction_default_blocks_raw_payloads() -> None:
    payload = {
        "prompt_text": "SECRET-CODE-BLOCK-" * 100,
        "response_text": "MODEL-OUTPUT-" * 100,
        "input_token_count": 200,
        "output_token_count": 80,
    }
    sanitized = sanitize_payload(payload, mode="metadata_only", max_metadata_bytes=8192)
    assert "prompt_text" not in sanitized
    assert "response_text" not in sanitized
    assert "prompt_text_hash" in sanitized
    assert "response_text_hash" in sanitized


def test_legacy_usage_parity_with_observer_usage() -> None:
    context: dict[str, Any] = {}
    provider_usage = ProviderLLMUsage(
        input_tokens=123,
        output_tokens=45,
        cached_input_tokens=7,
        cache_creation_input_tokens=3,
    )
    record_usage(context, "anthropic", "claude-sonnet-4-5", provider_usage)
    observer_usage = ObserverLLMUsage(
        input_tokens=provider_usage.input_tokens,
        output_tokens=provider_usage.output_tokens,
        cache_read_tokens=provider_usage.cached_input_tokens,
        cache_write_tokens=provider_usage.cache_creation_input_tokens,
    )
    assert int(context["input_tokens"]) == observer_usage.input_tokens
    assert int(context["output_tokens"]) == observer_usage.output_tokens
    assert int(context["tokens_used"]) == observer_usage.total_tokens


@pytest.mark.asyncio
async def test_worker_startup_configures_observer(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_observer()
    monkeypatch.setattr(worker_module, "assert_r2_credentials_within_rotation_policy", lambda _: None)

    async def _fake_recover() -> int:
        return 0

    monkeypatch.setattr(worker_module, "recover_stale_running_reviews", _fake_recover)

    monkeypatch.setattr(app_settings, "observability_enabled", True, raising=False)
    monkeypatch.setattr(app_settings, "observability_sinks", "log", raising=False)

    ctx: dict[str, Any] = {}
    await worker_module.worker_startup(ctx)
    assert get_observer() is not None


def test_trace_terminal_statuses_emit_end_event() -> None:
    sink = InMemoryTestSink()
    observer = configure_observer([sink], enabled=True)
    trace = observer.start_review_trace(review_id=8, installation_id=9, run_id="run-8")
    observer.finish_review_trace(trace, status="skipped")
    review_end_events = [
        event for event in sink.events if event["event"] == "review_end"
    ]
    assert review_end_events
    assert review_end_events[-1]["payload"]["status"] == "skipped"


def test_stage_failed_status_emits_end_event() -> None:
    sink = InMemoryTestSink()
    observer = configure_observer([sink], enabled=True)
    trace = observer.start_review_trace(review_id=10, installation_id=11, run_id="run-10")
    stage = observer.start_stage(trace, "primary")
    observer.finish_stage(stage, status="failed")
    stage_end_events = [event for event in sink.events if event["event"] == "stage_end"]
    assert stage_end_events
    assert stage_end_events[-1]["payload"]["status"] == "failed"


class _FakeLangfuseNode:
    def __init__(self, calls: list[dict[str, Any]], name: str = "root") -> None:
        self._calls = calls
        self._name = name

    def trace(self, **kwargs: object) -> "_FakeLangfuseNode":
        self._calls.append({"method": "trace", "node": self._name, "kwargs": kwargs})
        return _FakeLangfuseNode(self._calls, "trace")

    def span(self, **kwargs: object) -> "_FakeLangfuseNode":
        self._calls.append({"method": "span", "node": self._name, "kwargs": kwargs})
        return _FakeLangfuseNode(self._calls, "span")

    def generation(self, **kwargs: object) -> "_FakeLangfuseNode":
        self._calls.append({"method": "generation", "node": self._name, "kwargs": kwargs})
        return _FakeLangfuseNode(self._calls, "generation")

    def event(self, **kwargs: object) -> None:
        self._calls.append({"method": "event", "node": self._name, "kwargs": kwargs})

    def score(self, **kwargs: object) -> None:
        self._calls.append({"method": "score", "node": self._name, "kwargs": kwargs})

    def update(self, **kwargs: object) -> None:
        self._calls.append({"method": "update", "node": self._name, "kwargs": kwargs})

    def end(self, **kwargs: object) -> None:
        self._calls.append({"method": "end", "node": self._name, "kwargs": kwargs})

    def flush(self) -> None:
        self._calls.append({"method": "flush", "node": self._name, "kwargs": {}})


def test_langfuse_sink_mirrors_trace_span_generation_ids() -> None:
    calls: list[dict[str, Any]] = []
    client = _FakeLangfuseNode(calls)
    sink = LangfuseSink(client, environment="test")
    observer = LLMObserver(sinks=[sink], enabled=True)
    trace = observer.start_review_trace(
        review_id=20,
        installation_id=30,
        run_id="run-20",
        trace_id="trace-20",
        prompt_version="prompt-v1",
    )
    stage = observer.start_stage(
        trace,
        "primary_review",
        stage_id="stage-20",
        span_id="span-20",
    )
    observer.record_generation(
        stage,
        provider="anthropic",
        model="claude-sonnet-4-5",
        usage=ObserverLLMUsage(input_tokens=100, output_tokens=50),
        latency_ms=123,
        generation_id="generation-20",
        request_hash="request-hash",
        response_hash="response-hash",
    )
    observer.finish_stage(stage, status="success")
    observer.finish_review_trace(trace, status="success")

    trace_call = next(call for call in calls if call["method"] == "trace")
    span_call = next(call for call in calls if call["method"] == "span")
    generation_call = next(call for call in calls if call["method"] == "generation")
    assert trace_call["kwargs"]["id"] == "trace-20"
    assert span_call["kwargs"]["id"] == "span-20"
    assert generation_call["kwargs"]["id"] == "generation-20"
    assert generation_call["kwargs"]["metadata"]["request_hash"] == "request-hash"
