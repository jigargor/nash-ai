"""Sleep/backoff for LLM HTTP 429 so we do not hammer the same API key."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

logger = logging.getLogger(__name__)


def parse_retry_after_seconds_from_exception(exc: BaseException) -> float | None:
    """Best-effort parse of ``Retry-After`` from httpx/SDK exception payloads."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None or not str(raw).strip():
        return None
    text = str(raw).strip()
    if text.isdigit():
        return float(int(text))
    try:
        when = parsedate_to_datetime(text)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        delta = (when - datetime.now(timezone.utc)).total_seconds()
        if delta > 0:
            return float(delta)
    except (TypeError, ValueError, OverflowError):
        return None
    return None


def parse_rate_limit_reset_http_date(exc: BaseException) -> str | None:
    """Return provider reset hint if present (for logs / future UI)."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers: Any = getattr(response, "headers", None)
    if headers is None:
        return None
    for key in (
        "x-ratelimit-reset",
        "x-ratelimit-reset-requests",
        "anthropic-ratelimit-requests-reset",
        "openai-ratelimit-reset-requests",
    ):
        value = headers.get(key) or headers.get(key.title())
        if value and str(value).strip():
            return str(value).strip()
    return None


async def sleep_after_llm_rate_limit(
    *,
    provider: str,
    model: str,
    attempt_index: int,
    retry_after_seconds: float | None,
    rate_limit_reset_hint: str | None,
) -> None:
    """Sleep before trying another model/provider with the same billing identity."""
    if retry_after_seconds is not None and retry_after_seconds > 0:
        delay = min(max(retry_after_seconds, 0.5), 120.0)
    else:
        delay = min(max(2.0**attempt_index, 2.0), 120.0)
    logger.info(
        "LLM rate-limit backoff seconds=%.2f provider=%s model=%s attempt=%s reset_hint=%s",
        delay,
        provider,
        model,
        attempt_index,
        rate_limit_reset_hint or "—",
    )
    await asyncio.sleep(delay)
