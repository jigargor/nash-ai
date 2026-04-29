from __future__ import annotations

from typing import Any

_QUOTA_KEYWORDS = (
    "insufficient_quota",
    "quota",
    "rate limit",
    "rate_limit",
    "resource exhausted",
    "too many requests",
    "overloaded",
)


class LLMQuotaOrRateLimitError(RuntimeError):
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        detail: str,
        retry_after_seconds: float | None = None,
        rate_limit_reset_hint: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.provider = provider
        self.model = model
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds
        self.rate_limit_reset_hint = rate_limit_reset_hint


def coerce_quota_error(exc: Exception, *, provider: str, model: str) -> LLMQuotaOrRateLimitError | None:
    if _has_quota_signal(exc):
        detail = str(exc) or f"{provider} quota or rate limit exceeded"
        retry_after = _parse_retry_after_seconds_from_exc(exc)
        reset_hint = _parse_rate_limit_reset_hint_from_exc(exc)
        return LLMQuotaOrRateLimitError(
            provider=provider,
            model=model,
            detail=detail,
            retry_after_seconds=retry_after,
            rate_limit_reset_hint=reset_hint,
        )
    return None


def _parse_retry_after_seconds_from_exc(exc: BaseException) -> float | None:
    from app.llm import rate_limit_backoff

    return rate_limit_backoff.parse_retry_after_seconds_from_exception(exc)


def _parse_rate_limit_reset_hint_from_exc(exc: BaseException) -> str | None:
    from app.llm import rate_limit_backoff

    return rate_limit_backoff.parse_rate_limit_reset_http_date(exc)


def _has_quota_signal(exc: Exception) -> bool:
    status_code = _status_code_from_error(exc)
    if status_code == 429:
        return True
    message = str(exc).lower()
    return any(token in message for token in _QUOTA_KEYWORDS)


def _status_code_from_error(exc: Exception) -> int | None:
    direct = _coerce_int(getattr(exc, "status_code", None))
    if direct is not None:
        return direct
    response = getattr(exc, "response", None)
    if response is None:
        return None
    return _coerce_int(getattr(response, "status_code", None))


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
