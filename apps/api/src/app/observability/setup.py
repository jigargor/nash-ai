"""Sentry and Langfuse initialisation, extracted from the legacy observability module."""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.observability.deepeval_tracing import configure_deepeval_runtime
from app.observability.observer import configure_observer
from app.observability.sinks import DBSink, LangfuseSink, ObservabilitySink, StructuredLogSink

logger = logging.getLogger(__name__)

try:
    import sentry_sdk
except Exception:  # pragma: no cover - optional dependency
    sentry_sdk = None  # type: ignore[assignment]

LangfuseClass: Any
try:
    from langfuse import Langfuse as LangfuseClass
except Exception:  # pragma: no cover - optional dependency
    LangfuseClass = None

_LANGFUSE_CLIENT: Any | None = None
_SENTRY_READY = False


def init_observability(service_name: str) -> None:
    """Initialise Sentry and Langfuse.  Safe to call multiple times."""
    configure_deepeval_runtime()
    _init_sentry(service_name)
    _init_langfuse()
    _init_observer_sinks()


def _init_sentry(service_name: str) -> None:
    global _SENTRY_READY
    if _SENTRY_READY or sentry_sdk is None or not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.2,
        send_default_pii=False,
        release=service_name,
    )
    _SENTRY_READY = True


def _init_langfuse() -> None:
    global _LANGFUSE_CLIENT
    if _LANGFUSE_CLIENT is not None or LangfuseClass is None:
        return
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return
    _LANGFUSE_CLIENT = LangfuseClass(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )


def _init_observer_sinks() -> None:
    enabled = bool(settings.observability_enabled)
    sinks = _build_observer_sinks()
    configure_observer(
        sinks=sinks,
        enabled=enabled and bool(sinks),
        sample_rate=float(settings.observability_sample_rate),
        max_events_per_review=int(settings.observability_max_events_per_review),
    )


def _build_observer_sinks() -> list[ObservabilitySink]:
    sink_names = [
        name.strip().lower()
        for name in str(settings.observability_sinks or "disabled").split(",")
        if name.strip()
    ]
    if not sink_names or "disabled" in sink_names:
        return []

    sinks: list[ObservabilitySink] = []
    if "log" in sink_names:
        sinks.append(
            StructuredLogSink(
                payload_mode=settings.observability_payload_mode,  # type: ignore[arg-type]
                max_metadata_bytes=settings.observability_max_metadata_bytes,
            )
        )
    if "db" in sink_names:
        from app.db.session import AsyncSessionLocal

        sinks.append(DBSink(session_factory=AsyncSessionLocal))
    if "langfuse" in sink_names:
        if _LANGFUSE_CLIENT is None:
            logger.warning("OBSERVABILITY_SINKS includes langfuse but Langfuse is not configured")
        else:
            sinks.append(LangfuseSink(_LANGFUSE_CLIENT, environment=settings.environment))
    return sinks


def record_review_trace(metadata: dict[str, Any]) -> None:
    """Emit a coarse Langfuse trace for an entire review run."""
    if _LANGFUSE_CLIENT is None:
        return
    try:
        trace_fn = getattr(_LANGFUSE_CLIENT, "trace", None)
        if callable(trace_fn):
            trace_fn(
                name="review_pr",
                metadata=metadata,
                tags=["review", settings.environment],
            )
    except Exception:
        logger.exception("Failed to emit Langfuse trace")
