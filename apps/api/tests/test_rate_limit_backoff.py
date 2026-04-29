"""Tests for LLM rate-limit header parsing."""

from __future__ import annotations

from types import SimpleNamespace

from app.llm.rate_limit_backoff import parse_retry_after_seconds_from_exception


def test_parse_retry_after_seconds_integer_header() -> None:
    exc = SimpleNamespace(
        response=SimpleNamespace(headers={"retry-after": "42"}),
    )
    assert parse_retry_after_seconds_from_exception(exc) == 42.0


def test_parse_retry_after_seconds_missing() -> None:
    exc = SimpleNamespace(response=SimpleNamespace(headers={}))
    assert parse_retry_after_seconds_from_exception(exc) is None
