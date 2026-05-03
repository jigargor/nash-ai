"""Pydantic event models for the LLMObserver pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

TerminalStatus = Literal[
    "success", "skipped", "failed", "canceled", "partial", "rate_limited", "budget_exhausted"
]


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _event_id() -> str:
    return str(uuid4())


class EventBase(BaseModel):
    review_id: int
    installation_id: int
    run_id: str = ""
    trace_id: str = ""
    stage_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""
    event_id: str = Field(default_factory=_event_id)
    event_type: str
    stage: str = ""
    provider: str = ""
    model: str = ""
    prompt_version: str = ""
    ts: datetime = Field(default_factory=_now)


class LLMUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ReviewStartEvent(EventBase):
    event_type: str = "review_start"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewEndEvent(EventBase):
    event_type: str = "review_end"
    status: TerminalStatus
    duration_ms: int


class StageStartEvent(EventBase):
    event_type: str = "stage_start"
    metadata: dict[str, Any] = Field(default_factory=dict)


class StageEndEvent(EventBase):
    event_type: str = "stage_end"
    status: TerminalStatus
    duration_ms: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerationEvent(EventBase):
    event_type: str = "generation"
    usage: LLMUsage
    latency_ms: int
    generation_id: str = ""
    attempt_index: int = 0
    fallback_reason: str = ""
    request_hash: str = ""
    response_hash: str = ""
    error_class: str = ""
    cache_strategy: str = "none"
    stop_reason: str = ""


class ToolCallEvent(EventBase):
    event_type: str = "tool_call"
    tool_call_id: str = ""
    tool_name: str
    duration_ms: int
    result_tokens: int
    success: bool = True
    error_class: str = ""
    input_hash: str = ""
    output_hash: str = ""


class ValidationEvent(EventBase):
    event_type: str = "validation"
    validation_type: str
    passed: bool
    errors: list[str] = Field(default_factory=list)
    findings_before: int = 0
    findings_after: int = 0
    drop_reason: str = ""


class ContextBuildEvent(EventBase):
    event_type: str = "context_build"
    total_tokens: int
    layers: dict[str, int] = Field(default_factory=dict)
    pressure: float = 0.0
    bloat_score: float = 0.0
    poisoning_score: float = 0.0


class ErrorEvent(EventBase):
    event_type: str = "error"
    error_type: str
    message: str
    recoverable: bool = True
