"""Tests for app.llm.errors — quota/rate-limit error coercion."""
from __future__ import annotations

from types import SimpleNamespace

from app.llm.errors import LLMQuotaOrRateLimitError, coerce_quota_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _exc_with_status(status_code: int, message: str = "error") -> Exception:
    """Build a mock exception that carries an HTTP status_code attribute."""
    exc = RuntimeError(message)
    exc.status_code = status_code  # type: ignore[attr-defined]
    return exc


def _exc_with_response_status(status_code: int, message: str = "error") -> Exception:
    """Build a mock exception with a .response.status_code (SDK-style)."""
    exc = RuntimeError(message)
    exc.response = SimpleNamespace(status_code=status_code)  # type: ignore[attr-defined]
    return exc


def _exc_with_message(message: str) -> Exception:
    return RuntimeError(message)


# ---------------------------------------------------------------------------
# 429 → LLMQuotaOrRateLimitError
# ---------------------------------------------------------------------------


def test_coerce_quota_error_anthropic_429() -> None:
    exc = _exc_with_status(429, "overloaded_error: too many requests")

    result = coerce_quota_error(exc, provider="anthropic", model="claude-sonnet-4-5")

    assert result is not None
    assert isinstance(result, LLMQuotaOrRateLimitError)
    assert result.provider == "anthropic"
    assert result.model == "claude-sonnet-4-5"


def test_coerce_quota_error_openai_429() -> None:
    exc = _exc_with_status(429, "Rate limit exceeded for model gpt-5")

    result = coerce_quota_error(exc, provider="openai", model="gpt-5")

    assert result is not None
    assert isinstance(result, LLMQuotaOrRateLimitError)
    assert result.provider == "openai"
    assert result.model == "gpt-5"


def test_coerce_quota_error_via_response_status() -> None:
    exc = _exc_with_response_status(429, "quota exceeded")

    result = coerce_quota_error(exc, provider="gemini", model="gemini-2.5-flash")

    assert result is not None
    assert result.provider == "gemini"


def test_coerce_quota_error_non_quota_returns_none() -> None:
    exc = _exc_with_status(500, "Internal server error")

    result = coerce_quota_error(exc, provider="openai", model="gpt-5")

    assert result is None


def test_coerce_quota_error_non_quota_400_returns_none() -> None:
    exc = _exc_with_status(400, "Bad request: invalid schema")

    result = coerce_quota_error(exc, provider="anthropic", model="claude-sonnet-4-5")

    assert result is None


def test_coerce_quota_error_plain_exception_returns_none() -> None:
    exc = ValueError("something unexpected")

    result = coerce_quota_error(exc, provider="openai", model="gpt-5-mini")

    assert result is None


# ---------------------------------------------------------------------------
# Keyword-based detection (no status code)
# ---------------------------------------------------------------------------


def test_coerce_quota_error_rate_limit_message() -> None:
    exc = _exc_with_message("rate limit exceeded for your account")

    result = coerce_quota_error(exc, provider="openai", model="gpt-5")

    assert result is not None
    assert isinstance(result, LLMQuotaOrRateLimitError)


def test_coerce_quota_error_insufficient_quota_message() -> None:
    exc = _exc_with_message("insufficient_quota: you have used all your credits")

    result = coerce_quota_error(exc, provider="openai", model="gpt-5")

    assert result is not None


def test_coerce_quota_error_resource_exhausted_message() -> None:
    exc = _exc_with_message("resource exhausted: daily limit reached")

    result = coerce_quota_error(exc, provider="gemini", model="gemini-2.5-flash")

    assert result is not None


def test_coerce_quota_error_too_many_requests_message() -> None:
    exc = _exc_with_message("Too Many Requests")

    result = coerce_quota_error(exc, provider="openai", model="gpt-5-mini")

    assert result is not None


def test_coerce_quota_error_overloaded_message() -> None:
    exc = _exc_with_message("Model overloaded. Please try again later.")

    result = coerce_quota_error(exc, provider="anthropic", model="claude-sonnet-4-5")

    assert result is not None


# ---------------------------------------------------------------------------
# LLMQuotaOrRateLimitError attributes
# ---------------------------------------------------------------------------


def test_llm_quota_error_carries_retry_after() -> None:
    exc = _exc_with_status(429)
    exc.response = SimpleNamespace(  # type: ignore[attr-defined]
        status_code=429,
        headers={"retry-after": "30"},
    )

    result = coerce_quota_error(exc, provider="openai", model="gpt-5")

    assert result is not None
    assert result.retry_after_seconds == 30.0


def test_llm_quota_error_detail_falls_back_when_empty() -> None:
    exc = RuntimeError("")
    exc.status_code = 429  # type: ignore[attr-defined]

    result = coerce_quota_error(exc, provider="anthropic", model="claude-opus-4-5")

    assert result is not None
    assert "quota" in result.detail.lower() or "anthropic" in result.detail.lower()


def test_llm_quota_error_is_runtime_error() -> None:
    exc = _exc_with_status(429, "too many requests")

    result = coerce_quota_error(exc, provider="openai", model="gpt-5")

    assert result is not None
    assert isinstance(result, RuntimeError)
