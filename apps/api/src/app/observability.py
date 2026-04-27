import importlib.util
import logging
from typing import Any

from anthropic import AsyncAnthropic

from app.config import settings

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
_LANGFUSE_ANTHROPIC_SHIM_WARNED = False


def init_observability(service_name: str) -> None:
    _init_sentry(service_name)
    _init_langfuse()


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


def record_review_trace(metadata: dict[str, Any]) -> None:
    if _LANGFUSE_CLIENT is None:
        return
    try:
        trace_fn = getattr(_LANGFUSE_CLIENT, "trace", None)
        if callable(trace_fn):
            trace_fn(name="review_pr", metadata=metadata, tags=["review", settings.environment])
    except Exception:
        logger.exception("Failed to emit Langfuse trace")


def create_async_anthropic_client(api_key: str) -> AsyncAnthropic:
    """Return Anthropic async client; Langfuse auto-wrap only when ``langfuse.anthropic`` exists (dropped in v4+)."""
    global _LANGFUSE_ANTHROPIC_SHIM_WARNED
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        if importlib.util.find_spec("langfuse.anthropic") is None:
            if not _LANGFUSE_ANTHROPIC_SHIM_WARNED:
                logger.warning(
                    "Langfuse Anthropic shim not present (expected on langfuse>=4); "
                    "using anthropic.AsyncAnthropic; traces still use Langfuse SDK when configured"
                )
                _LANGFUSE_ANTHROPIC_SHIM_WARNED = True
        else:
            try:
                from langfuse.anthropic import AsyncAnthropic as LangfuseAsyncAnthropic  # type: ignore[import-not-found]
            except ImportError:
                logger.exception("Failed to import Langfuse Anthropic wrapper; using standard client")
            else:
                try:
                    return LangfuseAsyncAnthropic(api_key=api_key)
                except Exception:
                    logger.exception("Failed to construct Langfuse Anthropic client; using standard client")
    return AsyncAnthropic(api_key=api_key)
