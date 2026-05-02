"""LLMObserver: provider-neutral observation boundary for all LLM interactions."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

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
    metadata: dict[str, object]
    _started_ms: float = field(default_factory=time.monotonic, init=False)


@dataclass
class StageSpan:
    """Opaque handle returned by start_stage."""

    review_id: int
    installation_id: int
    stage: str
    run_id: str
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

    def __init__(self, sinks: list[ObservabilitySink] | None = None) -> None:
        if sinks is None:
            sinks = [StructuredLogSink()]
        self._sinks: list[ObservabilitySink] = sinks

    # ------------------------------------------------------------------
    # Sink fan-out helper
    # ------------------------------------------------------------------

    def _dispatch(self, method: str, event: object) -> None:
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
        metadata: dict[str, object] | None = None,
    ) -> ReviewTrace:
        trace = ReviewTrace(
            review_id=review_id,
            installation_id=installation_id,
            metadata=metadata or {},
        )
        self._dispatch(
            "on_review_start",
            ReviewStartEvent(
                review_id=review_id,
                installation_id=installation_id,
                metadata=dict(trace.metadata),
            ),
        )
        return trace

    def finish_review_trace(self, trace: ReviewTrace, status: str) -> None:
        duration_ms = int((time.monotonic() - trace._started_ms) * 1000)
        self._dispatch(
            "on_review_end",
            ReviewEndEvent(
                review_id=trace.review_id,
                installation_id=trace.installation_id,
                status=status,
                duration_ms=duration_ms,
            ),
        )

    # ------------------------------------------------------------------
    # Stage lifecycle
    # ------------------------------------------------------------------

    def start_stage(
        self,
        trace: ReviewTrace,
        stage: str,
        run_id: str = "",
        metadata: dict[str, object] | None = None,
    ) -> StageSpan:
        span = StageSpan(
            review_id=trace.review_id,
            installation_id=trace.installation_id,
            stage=stage,
            run_id=run_id,
            metadata=metadata or {},
        )
        self._dispatch(
            "on_stage_start",
            StageStartEvent(
                review_id=trace.review_id,
                installation_id=trace.installation_id,
                stage=stage,
                run_id=run_id,
                metadata=dict(span.metadata),
            ),
        )
        return span

    def finish_stage(self, span: StageSpan) -> None:
        duration_ms = int((time.monotonic() - span._started_ms) * 1000)
        self._dispatch(
            "on_stage_end",
            StageEndEvent(
                review_id=span.review_id,
                installation_id=span.installation_id,
                stage=span.stage,
                run_id=span.run_id,
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
        cache_strategy: str = "none",
        stop_reason: str = "",
    ) -> None:
        self._dispatch(
            "on_generation",
            GenerationEvent(
                review_id=span.review_id,
                installation_id=span.installation_id,
                stage=span.stage,
                run_id=span.run_id,
                provider=provider,
                model=model,
                usage=usage,
                latency_ms=latency_ms,
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
        tool_name: str,
        duration_ms: int,
        result_tokens: int,
        success: bool = True,
    ) -> None:
        self._dispatch(
            "on_tool_call",
            ToolCallEvent(
                review_id=span.review_id,
                installation_id=span.installation_id,
                stage=span.stage,
                run_id=span.run_id,
                tool_name=tool_name,
                duration_ms=duration_ms,
                result_tokens=result_tokens,
                success=success,
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
    ) -> None:
        self._dispatch(
            "on_validation",
            ValidationEvent(
                review_id=span.review_id,
                installation_id=span.installation_id,
                stage=span.stage,
                run_id=span.run_id,
                validation_type=validation_type,
                passed=passed,
                errors=errors or [],
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
    ) -> None:
        self._dispatch(
            "on_context_build",
            ContextBuildEvent(
                review_id=span.review_id,
                installation_id=span.installation_id,
                stage=span.stage,
                run_id=span.run_id,
                total_tokens=total_tokens,
                layers=layers,
                pressure=pressure,
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
            stage = "_review"
        else:
            run_id = span.run_id
            stage = span.stage
        self._dispatch(
            "on_error",
            ErrorEvent(
                review_id=span.review_id,
                installation_id=span.installation_id,
                stage=stage,
                run_id=run_id,
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
        _observer = LLMObserver()
    return _observer


def configure_observer(sinks: list[ObservabilitySink]) -> LLMObserver:
    """Replace the singleton with a freshly constructed observer.

    Intended for use in the FastAPI lifespan or test fixtures.
    """
    global _observer
    _observer = LLMObserver(sinks=sinks)
    return _observer


def reset_observer() -> None:
    """Reset the singleton to None.  Useful in tests to avoid state leakage."""
    global _observer
    _observer = None
