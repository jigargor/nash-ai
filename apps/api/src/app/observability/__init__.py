"""Observability package for Nash AI.

All symbols that were exported from the legacy ``app.observability`` module
remain importable from this package so that existing call sites continue to
work without modification.
"""

from __future__ import annotations

from anthropic import AsyncAnthropic

# Re-export legacy public surface from setup.py
from app.observability.setup import (
    init_observability,
    record_review_trace,
)

# Re-export new observer API
from app.observability.observer import (
    LLMObserver,
    ObservationContext,
    ReviewTrace,
    StageSpan,
    configure_observer,
    get_observer,
    reset_observer,
)

# Re-export event models
from app.observability.events import (
    ContextBuildEvent,
    ErrorEvent,
    GenerationEvent,
    LLMUsage,
    ReviewEndEvent,
    ReviewStartEvent,
    StageEndEvent,
    StageStartEvent,
    ToolCallEvent,
    ValidationEvent,
)

# Re-export sink types
from app.observability.sinks import (
    DBSink,
    InMemoryTestSink,
    LangfuseSink,
    ObservabilitySink,
    StructuredLogSink,
)


def create_async_anthropic_client(api_key: str) -> AsyncAnthropic:
    """Return the official Anthropic async client.

    Langfuse v4 removed ``langfuse.anthropic``; LLM calls are not wrapped here.
    Use ``record_review_trace`` / LLMObserver for observability.
    """
    return AsyncAnthropic(api_key=api_key)


__all__ = [
    # Legacy surface (backward-compat)
    "init_observability",
    "record_review_trace",
    "create_async_anthropic_client",
    # Observer
    "LLMObserver",
    "ObservationContext",
    "ReviewTrace",
    "StageSpan",
    "get_observer",
    "configure_observer",
    "reset_observer",
    # Events
    "LLMUsage",
    "ReviewStartEvent",
    "ReviewEndEvent",
    "StageStartEvent",
    "StageEndEvent",
    "GenerationEvent",
    "ToolCallEvent",
    "ValidationEvent",
    "ContextBuildEvent",
    "ErrorEvent",
    # Sinks
    "ObservabilitySink",
    "DBSink",
    "InMemoryTestSink",
    "LangfuseSink",
    "StructuredLogSink",
]
