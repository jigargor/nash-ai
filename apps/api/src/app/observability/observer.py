"""LLMObserver: provider-neutral observation boundary for all LLM interactions."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from random import random
from uuid import uuid4

from app.observability.context import ObservationContext
from app.observability.events import (
    ContextBuildEvent,
    ErrorEvent,
    GenerationEvent,
    LLMUsage,
    ReviewEndEvent,
    ReviewStartEvent,
    StageEndEvent,
    StageStartEvent,
    TerminalStatus,
    ToolCallEvent,
    ValidationEvent,
)
from app.observability.sinks import ObservabilitySink, StructuredLogSink

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight context objects (not persisted; live only for a single review)
# ---------------------------------------------------------------------------


@dataclass
class ReviewTrace:
    """Opaque handle returned by start_review_trace."""

    review_id: int
    installation_id: int
    run_id: str
    trace_id: str
    prompt_version: str
    metadata: dict[str, object]
    _started_ms: float = field(default_factory=time.monotonic, init=False)


@dataclass
class StageSpan:
    """Opaque handle returned by start_stage."""

    review_id: int
    installation_id: int
    trace_id: str
    stage_id: str
    span_id: str
    parent_span_id: str
    stage: str
    run_id: str
    prompt_version: str
    metadata: dict[str, object]
    _started_ms: float = field(default_factory=time.monotonic, init=False)


# ---------------------------------------------------------------------------
# LLMObserver
# ---------------------------------------------------------------------------


class LLMObserver:
    """Provider-neutral observation boundary for all LLM interactions.

    Designed for dependency injection.  Obtain a configured instance via
    ``get_observer()`` or construct one with explicit sinks for tests.
    """

    def __init__(
        self,
        sinks: list[ObservabilitySink] | None = None,
        *,
        enabled: bool = True,
        sample_rate: float = 1.0,
        max_events_per_review: int = 500,
    ) -> None:
        if sinks is None:
            sinks = [StructuredLogSink()]
        self._sinks: list[ObservabilitySink] = sinks
        self._enabled = enabled
        self._sample_rate = sample_rate
        self._max_events_per_review = max_events_per_review
        self._events_per_review: dict[int, int] = {}

    # ------------------------------------------------------------------
    # Sink fan-out helper
    # ------------------------------------------------------------------

    def _dispatch(self, method: str, event: object) -> None:
        if not self._enabled:
            return
        review_id = getattr(event, "review_id", None)
        if isinstance(review_id, int):
            count = self._events_per_review.get(review_id, 0)
            if count >= self._max_events_per_review:
                return
            self._events_per_review[review_id] = count + 1
        if self._sample_rate < 1.0 and random() > self._sample_rate:
            return
        for sink in self._sinks:
            try:
                getattr(sink, method)(event)
            except Exception:
                logger.exception("Sink %s.%s raised; skipping", type(sink).__name__, method)

    # ------------------------------------------------------------------
    # Review lifecycle
    # ------------------------------------------------------------------

    def start_review_trace(
        self,
        review_id: int,
        installation_id: int,
        run_id: str = "",
        trace_id: str = "",
        prompt_version: str = "",
        metadata: dict[str, object] | None = None,
    ) -> ReviewTrace:
        trace = ReviewTrace(
            review_id=review_id,
            installation_id=installation_id,
            run_id=run_id,
            trace_id=trace_id or str(uuid4()),
            prompt_version=prompt_version,
            metadata=metadata or {},
        )
        self._events_per_review[review_id] = 0
        self._dispatch(
            "on_review_start",
            ReviewStartEvent(
                review_id=review_id,
                installation_id=installation_id,
                run_id=trace.run_id,
                trace_id=trace.trace_id,
                prompt_version=trace.prompt_version,
                metadata=dict(trace.metadata),
            ),
        )
        return trace

    def finish_review_trace(self, trace: ReviewTrace, status: TerminalStatus) -> None:
        duration_ms = int((time.monotonic() - trace._started_ms) * 1000)
        self._dispatch(
            "on_review_end",
            ReviewEndEvent(
                review_id=trace.review_id,
                installation_id=trace.installation_id,
                run_id=trace.run_id,
                trace_id=trace.trace_id,
                prompt_version=trace.prompt_version,
                status=status,
                duration_ms=duration_ms,
            ),
        )
        self._events_per_review.pop(trace.review_id, None)

    # ------------------------------------------------------------------
    # Stage lifecycle
    # ------------------------------------------------------------------

    def start_stage(
        self,
        trace: ReviewTrace,
        stage: str,
        run_id: str = "",
        stage_id: str = "",
        span_id: str = "",
        parent_span_id: str = "",
        metadata: dict[str, object] | None = None,
    ) -> StageSpan:
        span = StageSpan(
            review_id=trace.review_id,
            installation_id=trace.installation_id,
            trace_id=trace.trace_id,
            stage_id=stage_id or str(uuid4()),
            span_id=span_id or str(uuid4()),
            parent_span_id=parent_span_id,
            stage=stage,
            run_id=run_id or trace.run_id,
            prompt_version=trace.prompt_version,
            metadata=metadata or {},
        )
        self._dispatch(
            "on_stage_start",
            StageStartEvent(
                review_id=trace.review_id,
                installation_id=trace.installation_id,
                run_id=span.run_id,
                trace_id=span.trace_id,
                stage_id=span.stage_id,
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
                stage=stage,
                prompt_version=span.prompt_version,
                metadata=dict(span.metadata),
            ),
        )
        return span

    def finish_stage(self, span: StageSpan, status: TerminalStatus = "success") -> None:
        duration_ms = int((time.monotonic() - span._started_ms) * 1000)
        self._dispatch(
            "on_stage_end",
            StageEndEvent(
                review_id=span.review_id,
                installation_id=span.installation_id,
                run_id=span.run_id,
                trace_id=span.trace_id,
                stage_id=span.stage_id,
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
                stage=span.stage,
                prompt_version=span.prompt_version,
                status=status,
                duration_ms=duration_ms,
                metadata=dict(span.metadata),
            ),
        )

    # ------------------------------------------------------------------
    # LLM generation events
    # ------------------------------------------------------------------

    def record_generation(
        self,
        span: StageSpan,
        *,
        provider: str,
        model: str,
        usage: LLMUsage,
        latency_ms: int,
        generation_id: str = "",
        attempt_index: int = 0,
        fallback_reason: str = "",
        request_hash: str = "",
        response_hash: str = "",
        error_class: str = "",
        cache_strategy: str = "none",
        stop_reason: str = "",
    ) -> None:
        self._dispatch(
            "on_generation",
            GenerationEvent(
                review_id=span.review_id,
                installation_id=span.installation_id,
                run_id=span.run_id,
                trace_id=span.trace_id,
                stage_id=span.stage_id,
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
                stage=span.stage,
                provider=provider,
                model=model,
                prompt_version=span.prompt_version,
                usage=usage,
                latency_ms=latency_ms,
                generation_id=generation_id or str(uuid4()),
                attempt_index=attempt_index,
                fallback_reason=fallback_reason,
                request_hash=request_hash,
                response_hash=response_hash,
                error_class=error_class,
                cache_strategy=cache_strategy,
                stop_reason=stop_reason,
            ),
        )

    # ------------------------------------------------------------------
    # Tool call events
    # ------------------------------------------------------------------

    def record_tool_call(
        self,
        span: StageSpan,
        *,
        tool_call_id: str = "",
        tool_name: str,
        duration_ms: int,
        result_tokens: int,
        success: bool = True,
        error_class: str = "",
        input_hash: str = "",
        output_hash: str = "",
    ) -> None:
        self._dispatch(
            "on_tool_call",
            ToolCallEvent(
                review_id=span.review_id,
                installation_id=span.installation_id,
                run_id=span.run_id,
                trace_id=span.trace_id,
                stage_id=span.stage_id,
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
                stage=span.stage,
                prompt_version=span.prompt_version,
                tool_call_id=tool_call_id or str(uuid4()),
                tool_name=tool_name,
                duration_ms=duration_ms,
                result_tokens=result_tokens,
                success=success,
                error_class=error_class,
                input_hash=input_hash,
                output_hash=output_hash,
            ),
        )

    # ------------------------------------------------------------------
    # Validation events
    # ------------------------------------------------------------------

    def record_validation(
        self,
        span: StageSpan,
        *,
        validation_type: str,
        passed: bool,
        errors: list[str] | None = None,
        findings_before: int = 0,
        findings_after: int = 0,
        drop_reason: str = "",
    ) -> None:
        self._dispatch(
            "on_validation",
            ValidationEvent(
                review_id=span.review_id,
                installation_id=span.installation_id,
                run_id=span.run_id,
                trace_id=span.trace_id,
                stage_id=span.stage_id,
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
                stage=span.stage,
                prompt_version=span.prompt_version,
                validation_type=validation_type,
                passed=passed,
                errors=errors or [],
                findings_before=findings_before,
                findings_after=findings_after,
                drop_reason=drop_reason,
            ),
        )

    # ------------------------------------------------------------------
    # Context build events
    # ------------------------------------------------------------------

    def record_context_build(
        self,
        span: StageSpan,
        *,
        total_tokens: int,
        layers: dict[str, int],
        pressure: float,
        bloat_score: float = 0.0,
        poisoning_score: float = 0.0,
    ) -> None:
        self._dispatch(
            "on_context_build",
            ContextBuildEvent(
                review_id=span.review_id,
                installation_id=span.installation_id,
                run_id=span.run_id,
                trace_id=span.trace_id,
                stage_id=span.stage_id,
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
                stage=span.stage,
                prompt_version=span.prompt_version,
                total_tokens=total_tokens,
                layers=layers,
                pressure=pressure,
                bloat_score=bloat_score,
                poisoning_score=poisoning_score,
            ),
        )

    # ------------------------------------------------------------------
    # Error events
    # ------------------------------------------------------------------

    def record_error(
        self,
        span: StageSpan | ReviewTrace,
        *,
        error_type: str,
        message: str,
        recoverable: bool = True,
    ) -> None:
        if isinstance(span, ReviewTrace):
            run_id = ""
            trace_id = span.trace_id
            stage_id = ""
            span_id = ""
            parent_span_id = ""
            prompt_version = span.prompt_version
            stage = "_review"
        else:
            run_id = span.run_id
            trace_id = span.trace_id
            stage_id = span.stage_id
            span_id = span.span_id
            parent_span_id = span.parent_span_id
            prompt_version = span.prompt_version
            stage = span.stage
        self._dispatch(
            "on_error",
            ErrorEvent(
                review_id=span.review_id,
                installation_id=span.installation_id,
                run_id=run_id,
                trace_id=trace_id,
                stage_id=stage_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                stage=stage,
                prompt_version=prompt_version,
                error_type=error_type,
                message=message,
                recoverable=recoverable,
            ),
        )


# ---------------------------------------------------------------------------
# Singleton + DI helpers
# ---------------------------------------------------------------------------

_observer: LLMObserver | None = None


def get_observer() -> LLMObserver:
    """Return the process-level LLMObserver.

    Call ``configure_observer`` during app startup to attach real sinks.
    Falls back to a log-only observer so tests work without configuration.
    """
    global _observer
    if _observer is None:
        _observer = LLMObserver(enabled=False)
    return _observer


def configure_observer(
    sinks: list[ObservabilitySink],
    *,
    enabled: bool = True,
    sample_rate: float = 1.0,
    max_events_per_review: int = 500,
) -> LLMObserver:
    """Replace the singleton with a freshly constructed observer.

    Intended for use in the FastAPI lifespan or test fixtures.
    """
    global _observer
    _observer = LLMObserver(
        sinks=sinks,
        enabled=enabled,
        sample_rate=sample_rate,
        max_events_per_review=max_events_per_review,
    )
    return _observer


def reset_observer() -> None:
    """Reset the singleton to None.  Useful in tests to avoid state leakage."""
    global _observer
    _observer = None


__all__ = [
    "LLMObserver",
    "ObservationContext",
    "ReviewTrace",
    "StageSpan",
    "get_observer",
    "configure_observer",
    "reset_observer",
]
