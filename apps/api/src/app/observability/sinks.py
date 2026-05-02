"""Sink Protocol and built-in sink implementations."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Protocol, runtime_checkable

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

    def __init__(self, log_level: int = logging.DEBUG) -> None:
        self._level = log_level
        self._log = logging.getLogger("nash.observability")

    def _emit(self, event_type: str, payload: dict[str, object]) -> None:
        if self._log.isEnabledFor(self._level):
            self._log.log(
                self._level,
                json.dumps({"event": event_type, **payload}, default=str),
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
                        existing.update(event.metadata)
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
                        "latency_ms": event.latency_ms,
                        "cache_strategy": event.cache_strategy,
                        "stop_reason": event.stop_reason,
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
