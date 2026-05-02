"""Pydantic event models for the LLMObserver pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class LLMUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# ---------------------------------------------------------------------------
# Review lifecycle
# ---------------------------------------------------------------------------


class ReviewStartEvent(BaseModel):
    review_id: int
    installation_id: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=_now)


class ReviewEndEvent(BaseModel):
    review_id: int
    installation_id: int
    status: str
    duration_ms: int
    ts: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Stage lifecycle
# ---------------------------------------------------------------------------


class StageStartEvent(BaseModel):
    review_id: int
    installation_id: int
    stage: str
    run_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=_now)


class StageEndEvent(BaseModel):
    review_id: int
    installation_id: int
    stage: str
    run_id: str
    duration_ms: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# LLM generation
# ---------------------------------------------------------------------------


class GenerationEvent(BaseModel):
    review_id: int
    installation_id: int
    stage: str
    run_id: str
    provider: str
    model: str
    usage: LLMUsage
    latency_ms: int
    cache_strategy: str = "none"
    stop_reason: str = ""
    ts: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Tool call
# ---------------------------------------------------------------------------


class ToolCallEvent(BaseModel):
    review_id: int
    installation_id: int
    stage: str
    run_id: str
    tool_name: str
    duration_ms: int
    result_tokens: int
    success: bool = True
    ts: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ValidationEvent(BaseModel):
    review_id: int
    installation_id: int
    stage: str
    run_id: str
    validation_type: str
    passed: bool
    errors: list[str] = Field(default_factory=list)
    ts: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Context build
# ---------------------------------------------------------------------------


class ContextBuildEvent(BaseModel):
    review_id: int
    installation_id: int
    stage: str
    run_id: str
    total_tokens: int
    layers: dict[str, int] = Field(default_factory=dict)
    pressure: float = 0.0
    ts: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class ErrorEvent(BaseModel):
    review_id: int
    installation_id: int
    stage: str
    run_id: str
    error_type: str
    message: str
    recoverable: bool = True
    ts: datetime = Field(default_factory=_now)
