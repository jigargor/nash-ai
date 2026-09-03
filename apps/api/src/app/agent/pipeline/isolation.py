"""Stage isolation — failures degrade a stage, never crash the pipeline by default."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def with_isolation(
    stage: str,
    fn: Callable[[], Awaitable[T]],
    *,
    fallback: T,
    errors_out: list[str] | None = None,
    reraise: bool = False,
    timeout_s: float | None = None,
) -> T:
    """Run ``fn``; on exception log, record, and return ``fallback`` unless ``reraise``."""
    try:
        if timeout_s is not None:
            return await asyncio.wait_for(fn(), timeout=timeout_s)
        return await fn()
    except Exception as exc:
        message = f"{stage}: {exc.__class__.__name__}: {exc}"
        logger.warning("Stage degraded stage=%s err=%s", stage, message, exc_info=True)
        if errors_out is not None:
            errors_out.append(message)
        if reraise:
            raise
        return fallback
