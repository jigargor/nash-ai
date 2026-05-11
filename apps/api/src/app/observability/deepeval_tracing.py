"""Optional DeepEval tracing helpers.

This module keeps DeepEval runtime integration strictly best-effort:
- No hard dependency when deepeval is not installed.
- No review-path failures when DeepEval tracing fails.
- Explicitly gated by settings and API key presence.
"""

from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Callable
from typing import ParamSpec, TypeVar, cast

from app.config import settings

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

ObserveFn = Callable[..., Callable[[Callable[P, R]], Callable[P, R]]]
UpdateSpanFn = Callable[..., None]


def _load_deepeval_tracing() -> tuple[ObserveFn | None, UpdateSpanFn | None]:
    """Load DeepEval tracing helpers when the optional extra is installed.

    Uses importlib so mypy/CI do not require ``deepeval`` to be installed.
    """
    try:
        mod = importlib.import_module("deepeval.tracing")
    except Exception:
        return None, None
    observe_raw = getattr(mod, "observe", None)
    update_raw = getattr(mod, "update_current_span", None)
    if not callable(observe_raw) or not callable(update_raw):
        return None, None
    return cast(ObserveFn, observe_raw), cast(UpdateSpanFn, update_raw)


_observe, _update_current_span = _load_deepeval_tracing()


def is_deepeval_tracing_enabled() -> bool:
    api_key = (settings.confident_api_key or "").strip()
    return bool(settings.deepeval_tracing_enabled and api_key)


def configure_deepeval_runtime() -> None:
    """Set DeepEval runtime env once when tracing is enabled."""
    if not is_deepeval_tracing_enabled():
        return
    if _observe is None:
        logger.warning(
            "DEEPEVAL_TRACING_ENABLED is true, but deepeval package is unavailable"
        )
        return
    os.environ.setdefault("CONFIDENT_API_KEY", (settings.confident_api_key or "").strip())


def observe_span(span_type: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Return a DeepEval observe decorator or a no-op fallback."""

    def _decorator(func: Callable[P, R]) -> Callable[P, R]:
        if not is_deepeval_tracing_enabled():
            return func
        observe = _observe
        if observe is None:
            return func
        try:
            return cast(Callable[P, R], observe(type=span_type)(func))
        except Exception:
            logger.exception("Failed to apply DeepEval observe decorator")
            return func

    return _decorator


def update_deepeval_span(**kwargs: object) -> None:
    """Attach metadata to the current DeepEval span if available."""
    if not is_deepeval_tracing_enabled() or _update_current_span is None:
        return
    try:
        _update_current_span(**kwargs)
    except Exception:
        logger.debug("DeepEval span update failed", exc_info=True)
