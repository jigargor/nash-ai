"""Observation context propagated through review execution paths."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ObservationContext:
    """Carries trace and stage correlation identifiers across call boundaries."""

    review_id: int
    run_id: str
    trace_id: str
    current_stage_id: str | None = None
    current_span_id: str | None = None
    prompt_version: str = ""
