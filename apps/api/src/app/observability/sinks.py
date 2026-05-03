"""Sink Protocol and built-in sink implementations."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Protocol, cast, runtime_checkable

from app.observability.events import (
    ContextBuildEvent,
    ErrorEvent,
    GenerationEvent,
    ReviewEndEvent,
    ReviewStartEvent,
    StageEndEvent,
    StageStartEvent,
    ToolCallEvent,
    ValidationEvent,
)
from app.observability.redaction import ObservabilityPayloadMode, sanitize_payload

logger = logging.getLogger(__name__)

# A session factory is any callable that works as an async context manager
# returning an AsyncSession, e.g. async_sessionmaker(engine).
SessionFactory = Callable[[], Any]  # AsyncSession context manager


@runtime_checkable
class ObservabilitySink(Protocol):
    """Receive observability events.  Every method is fire-and-forget."""

    def on_review_start(self, event: ReviewStartEvent) -> None: ...

    def on_review_end(self, event: ReviewEndEvent) -> None: ...

    def on_stage_start(self, event: StageStartEvent) -> None: ...

    def on_stage_end(self, event: StageEndEvent) -> None: ...

    def on_generation(self, event: GenerationEvent) -> None: ...

    def on_tool_call(self, event: ToolCallEvent) -> None: ...

    def on_validation(self, event: ValidationEvent) -> None: ...

    def on_context_build(self, event: ContextBuildEvent) -> None: ...

    def on_error(self, event: ErrorEvent) -> None: ...

    def flush(self) -> None: ...


# ---------------------------------------------------------------------------
# StructuredLogSink
# ---------------------------------------------------------------------------


class StructuredLogSink:
    """Emits every event as a structured JSON log line at DEBUG level.

    Always active so there is always a cheap, zero-dependency audit trail.
    """

    def __init__(
        self,
        log_level: int = logging.DEBUG,
        *,
        payload_mode: ObservabilityPayloadMode = "metadata_only",
        max_metadata_bytes: int = 8192,
    ) -> None:
        self._level = log_level
        self._log = logging.getLogger("nash.observability")
        self._payload_mode = payload_mode
        self._max_metadata_bytes = max_metadata_bytes

    def _emit(self, event_type: str, payload: dict[str, object]) -> None:
        if self._log.isEnabledFor(self._level):
            safe_payload = sanitize_payload(
                payload,
                mode=self._payload_mode,
                max_metadata_bytes=self._max_metadata_bytes,
            )
            self._log.log(
                self._level,
                json.dumps({"event": event_type, **safe_payload}, default=str),
            )

    def on_review_start(self, event: ReviewStartEvent) -> None:
        self._emit("review_start", event.model_dump(mode="json"))

    def on_review_end(self, event: ReviewEndEvent) -> None:
        self._emit("review_end", event.model_dump(mode="json"))

    def on_stage_start(self, event: StageStartEvent) -> None:
        self._emit("stage_start", event.model_dump(mode="json"))

    def on_stage_end(self, event: StageEndEvent) -> None:
        self._emit("stage_end", event.model_dump(mode="json"))

    def on_generation(self, event: GenerationEvent) -> None:
        self._emit("generation", event.model_dump(mode="json"))

    def on_tool_call(self, event: ToolCallEvent) -> None:
        self._emit("tool_call", event.model_dump(mode="json"))

    def on_validation(self, event: ValidationEvent) -> None:
        self._emit("validation", event.model_dump(mode="json"))

    def on_context_build(self, event: ContextBuildEvent) -> None:
        self._emit("context_build", event.model_dump(mode="json"))

    def on_error(self, event: ErrorEvent) -> None:
        self._emit("error", event.model_dump(mode="json"))

    def flush(self) -> None:
        pass


# ---------------------------------------------------------------------------
# DBSink
# ---------------------------------------------------------------------------


class DBSink:
    """Writes generation events to the ReviewModelAudit table.

    Session factory is injected so the sink can open its own short-lived
    session without holding a connection open during the entire review.
    """

    def __init__(
        self,
        session_factory: SessionFactory | None = None,
    ) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _schedule(self, coro: object) -> None:
        """Schedule a coroutine fire-and-forget on the running event loop."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop; drop silently (e.g. during startup/test setup)
            return
        loop.create_task(coro)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Protocol implementation
    # ------------------------------------------------------------------

    def on_review_start(self, event: ReviewStartEvent) -> None:
        pass

    def on_review_end(self, event: ReviewEndEvent) -> None:
        pass

    def on_stage_start(self, event: StageStartEvent) -> None:
        pass

    def on_stage_end(self, event: StageEndEvent) -> None:
        if self._session_factory is None:
            return
        self._schedule(self._persist_stage_end(event))

    async def _persist_stage_end(self, event: StageEndEvent) -> None:
        """Upsert stage metadata into ReviewModelAudit.metadata_json."""
        from sqlalchemy import select

        from app.db.models import ReviewModelAudit

        if self._session_factory is None:
            return
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    result = await session.execute(
                        select(ReviewModelAudit).where(
                            ReviewModelAudit.review_id == event.review_id,
                            ReviewModelAudit.stage == event.stage,
                            ReviewModelAudit.run_id == event.run_id,
                        )
                    )
                    audit = result.scalars().first()
                    if audit is not None:
                        existing: dict[str, object] = dict(audit.metadata_json or {})
                        existing.update(
                            {
                                **event.metadata,
                                "trace_id": event.trace_id,
                                "stage_id": event.stage_id,
                                "span_id": event.span_id,
                                "parent_span_id": event.parent_span_id,
                                "stage_status": event.status,
                            }
                        )
                        if event.duration_ms:
                            audit.stage_duration_ms = event.duration_ms
                        audit.metadata_json = existing
        except Exception:
            logger.exception(
                "DBSink._persist_stage_end failed review_id=%s stage=%s",
                event.review_id,
                event.stage,
            )

    def on_generation(self, event: GenerationEvent) -> None:
        if self._session_factory is None:
            return
        self._schedule(self._persist_generation(event))

    async def _persist_generation(self, event: GenerationEvent) -> None:
        """Insert or update a ReviewModelAudit row for the generation."""
        from sqlalchemy import select

        from app.db.models import ReviewModelAudit

        if self._session_factory is None:
            return
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    result = await session.execute(
                        select(ReviewModelAudit).where(
                            ReviewModelAudit.review_id == event.review_id,
                            ReviewModelAudit.stage == event.stage,
                            ReviewModelAudit.run_id == event.run_id,
                        )
                    )
                    audit = result.scalars().first()
                    meta: dict[str, object] = {
                        "trace_id": event.trace_id,
                        "stage_id": event.stage_id,
                        "span_id": event.span_id,
                        "parent_span_id": event.parent_span_id,
                        "generation_id": event.generation_id,
                        "event_id": event.event_id,
                        "prompt_version": event.prompt_version,
                        "attempt_index": event.attempt_index,
                        "fallback_reason": event.fallback_reason,
                        "latency_ms": event.latency_ms,
                        "cache_strategy": event.cache_strategy,
                        "stop_reason": event.stop_reason,
                        "request_hash": event.request_hash,
                        "response_hash": event.response_hash,
                        "error_class": event.error_class,
                        "cache_read_tokens": event.usage.cache_read_tokens,
                        "cache_write_tokens": event.usage.cache_write_tokens,
                    }
                    if audit is None:
                        audit = ReviewModelAudit(
                            review_id=event.review_id,
                            installation_id=event.installation_id,
                            run_id=event.run_id,
                            stage=event.stage,
                            provider=event.provider,
                            model=event.model,
                            input_tokens=event.usage.input_tokens,
                            output_tokens=event.usage.output_tokens,
                            total_tokens=event.usage.total_tokens,
                            metadata_json=meta,
                        )
                        session.add(audit)
                    else:
                        audit.input_tokens += event.usage.input_tokens
                        audit.output_tokens += event.usage.output_tokens
                        audit.total_tokens += event.usage.total_tokens
                        existing_meta: dict[str, object] = dict(audit.metadata_json or {})
                        existing_meta.update(meta)
                        audit.metadata_json = existing_meta
        except Exception:
            logger.exception(
                "DBSink._persist_generation failed review_id=%s stage=%s",
                event.review_id,
                event.stage,
            )

    def on_tool_call(self, event: ToolCallEvent) -> None:
        pass

    def on_validation(self, event: ValidationEvent) -> None:
        pass

    def on_context_build(self, event: ContextBuildEvent) -> None:
        pass

    def on_error(self, event: ErrorEvent) -> None:
        if self._session_factory is None:
            return
        self._schedule(self._persist_error(event))

    async def _persist_error(self, event: ErrorEvent) -> None:
        from sqlalchemy import select

        from app.db.models import ReviewModelAudit

        if self._session_factory is None:
            return
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    result = await session.execute(
                        select(ReviewModelAudit).where(
                            ReviewModelAudit.review_id == event.review_id,
                            ReviewModelAudit.stage == event.stage,
                            ReviewModelAudit.run_id == event.run_id,
                        )
                    )
                    audit = result.scalars().first()
                    if audit is not None:
                        existing: dict[str, object] = dict(audit.metadata_json or {})
                        raw_errors = existing.get("errors", [])
                        errors: list[dict[str, object]] = (
                            raw_errors if isinstance(raw_errors, list) else []
                        )
                        errors.append(
                            {
                                "type": event.error_type,
                                "message": event.message,
                                "recoverable": event.recoverable,
                                "trace_id": event.trace_id,
                                "stage_id": event.stage_id,
                                "span_id": event.span_id,
                                "event_id": event.event_id,
                                "ts": event.ts.isoformat(),
                            }
                        )
                        existing["errors"] = errors
                        audit.metadata_json = existing
        except Exception:
            logger.exception(
                "DBSink._persist_error failed review_id=%s stage=%s",
                event.review_id,
                event.stage,
            )

    def flush(self) -> None:
        pass


class LangfuseSink:
    """Mirror observer events into Langfuse using internal trace IDs for correlation."""

    def __init__(self, client: object, *, environment: str) -> None:
        self._client = client
        self._environment = environment
        self._traces: dict[str, object] = {}
        self._spans: dict[str, object] = {}

    def _call(self, target: object, method_name: str, **kwargs: object) -> object | None:
        method = getattr(target, method_name, None)
        if not callable(method):
            return None
        try:
            return cast(object, method(**kwargs))
        except TypeError:
            kwargs.pop("id", None)
            try:
                return cast(object, method(**kwargs))
            except Exception:
                logger.exception("LangfuseSink.%s failed after id fallback", method_name)
                return None
        except Exception:
            logger.exception("LangfuseSink.%s failed", method_name)
            return None

    def _trace_or_client(self, trace_id: str) -> object:
        return self._traces.get(trace_id) or self._client

    def _span_or_trace(self, event: StageStartEvent | StageEndEvent | GenerationEvent | ToolCallEvent | ValidationEvent | ContextBuildEvent | ErrorEvent) -> object:
        return self._spans.get(event.span_id) or self._trace_or_client(event.trace_id)

    def _event_metadata(self, event: object, extra: dict[str, object] | None = None) -> dict[str, object]:
        base: dict[str, object] = {
            "event_id": getattr(event, "event_id", ""),
            "review_id": getattr(event, "review_id", 0),
            "installation_id": getattr(event, "installation_id", 0),
            "run_id": getattr(event, "run_id", ""),
            "trace_id": getattr(event, "trace_id", ""),
            "stage_id": getattr(event, "stage_id", ""),
            "span_id": getattr(event, "span_id", ""),
            "parent_span_id": getattr(event, "parent_span_id", ""),
            "stage": getattr(event, "stage", ""),
            "prompt_version": getattr(event, "prompt_version", ""),
        }
        if extra:
            base.update(extra)
        return base

    def on_review_start(self, event: ReviewStartEvent) -> None:
        trace = self._call(
            self._client,
            "trace",
            id=event.trace_id,
            name="pr_review",
            metadata={
                **event.metadata,
                "event_id": event.event_id,
                "review_id": event.review_id,
                "installation_id": event.installation_id,
                "run_id": event.run_id,
                "prompt_version": event.prompt_version,
            },
            tags=["review", self._environment],
        )
        if trace is not None:
            self._traces[event.trace_id] = trace

    def on_review_end(self, event: ReviewEndEvent) -> None:
        trace = self._trace_or_client(event.trace_id)
        self._call(
            trace,
            "score",
            name="review_status",
            value=1 if event.status == "success" else 0,
            comment=event.status,
        )
        self._call(
            trace,
            "update",
            metadata=self._event_metadata(
                event,
                {"status": event.status, "duration_ms": event.duration_ms},
            ),
        )
        self._traces.pop(event.trace_id, None)

    def on_stage_start(self, event: StageStartEvent) -> None:
        parent = self._trace_or_client(event.trace_id)
        span = self._call(
            parent,
            "span",
            id=event.span_id,
            name=event.stage,
            metadata=self._event_metadata(event, event.metadata),
        )
        if span is not None:
            self._spans[event.span_id] = span

    def on_stage_end(self, event: StageEndEvent) -> None:
        span = self._spans.get(event.span_id)
        if span is not None:
            self._call(
                span,
                "end",
                output={"status": event.status, "duration_ms": event.duration_ms},
                metadata=self._event_metadata(event, event.metadata),
            )
            self._spans.pop(event.span_id, None)

    def on_generation(self, event: GenerationEvent) -> None:
        parent = self._span_or_trace(event)
        usage_details = {
            "input": event.usage.input_tokens,
            "output": event.usage.output_tokens,
            "total": event.usage.total_tokens,
            "cache_read": event.usage.cache_read_tokens,
            "cache_write": event.usage.cache_write_tokens,
        }
        self._call(
            parent,
            "generation",
            id=event.generation_id,
            name=f"{event.stage}:{event.provider}:{event.model}",
            model=event.model,
            usage_details=usage_details,
            metadata=self._event_metadata(
                event,
                {
                    "provider": event.provider,
                    "latency_ms": event.latency_ms,
                    "attempt_index": event.attempt_index,
                    "fallback_reason": event.fallback_reason,
                    "request_hash": event.request_hash,
                    "response_hash": event.response_hash,
                    "cache_strategy": event.cache_strategy,
                    "stop_reason": event.stop_reason,
                    "error_class": event.error_class,
                },
            ),
        )

    def on_tool_call(self, event: ToolCallEvent) -> None:
        self._emit_child_event(
            event,
            "tool_call",
            {
                "tool_call_id": event.tool_call_id,
                "tool_name": event.tool_name,
                "duration_ms": event.duration_ms,
                "result_tokens": event.result_tokens,
                "success": event.success,
                "error_class": event.error_class,
                "input_hash": event.input_hash,
                "output_hash": event.output_hash,
            },
        )

    def on_validation(self, event: ValidationEvent) -> None:
        self._emit_child_event(
            event,
            "validation",
            {
                "validation_type": event.validation_type,
                "passed": event.passed,
                "error_count": len(event.errors),
                "findings_before": event.findings_before,
                "findings_after": event.findings_after,
                "drop_reason": event.drop_reason,
            },
        )

    def on_context_build(self, event: ContextBuildEvent) -> None:
        self._emit_child_event(
            event,
            "context_build",
            {
                "total_tokens": event.total_tokens,
                "layers": event.layers,
                "pressure": event.pressure,
                "bloat_score": event.bloat_score,
                "poisoning_score": event.poisoning_score,
            },
        )

    def on_error(self, event: ErrorEvent) -> None:
        self._emit_child_event(
            event,
            "error",
            {
                "error_type": event.error_type,
                "message": event.message,
                "recoverable": event.recoverable,
            },
        )

    def _emit_child_event(self, event: object, name: str, metadata: dict[str, object]) -> None:
        parent = self._span_or_trace(event)  # type: ignore[arg-type]
        self._call(parent, "event", name=name, metadata=self._event_metadata(event, metadata))

    def flush(self) -> None:
        flush = getattr(self._client, "flush", None)
        if callable(flush):
            try:
                flush()
            except Exception:
                logger.exception("LangfuseSink.flush failed")


class InMemoryTestSink:
    """Collect all events in memory for unit/integration tests."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def _append(self, event_type: str, event: object) -> None:
        payload = event.model_dump(mode="json") if hasattr(event, "model_dump") else {"raw": event}
        self.events.append({"event": event_type, "payload": payload})

    def on_review_start(self, event: ReviewStartEvent) -> None:
        self._append("review_start", event)

    def on_review_end(self, event: ReviewEndEvent) -> None:
        self._append("review_end", event)

    def on_stage_start(self, event: StageStartEvent) -> None:
        self._append("stage_start", event)

    def on_stage_end(self, event: StageEndEvent) -> None:
        self._append("stage_end", event)

    def on_generation(self, event: GenerationEvent) -> None:
        self._append("generation", event)

    def on_tool_call(self, event: ToolCallEvent) -> None:
        self._append("tool_call", event)

    def on_validation(self, event: ValidationEvent) -> None:
        self._append("validation", event)

    def on_context_build(self, event: ContextBuildEvent) -> None:
        self._append("context_build", event)

    def on_error(self, event: ErrorEvent) -> None:
        self._append("error", event)

    def flush(self) -> None:
        return
