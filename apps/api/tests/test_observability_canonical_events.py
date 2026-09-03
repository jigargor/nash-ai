"""Telemetry: canonical event names, new drop/outcome events, JSONL sink."""

from __future__ import annotations

import json
from pathlib import Path

from app.observability import InMemoryTestSink, JsonlSink, LLMObserver
from app.observability.events import CANONICAL_EVENT_NAMES, FindingDroppedEvent, ToolCallEvent
from app.telemetry.finding_outcomes import canonical_outcome_event


def test_canonical_names_cover_plan_events() -> None:
    for name in (
        "review.started",
        "stage.finished",
        "provider.fallback",
        "llm.generation",
        "tool.called",
        "finding.dropped",
        "validation.rejected",
        "delivery.rejected",
        "suggestion.accepted",
        "suggestion.edited",
        "suggestion.dismissed",
        "finding.resolved",
        "finding.ignored",
        "budget.exceeded",
        "review.failed",
    ):
        assert name in CANONICAL_EVENT_NAMES.values(), name
    event = ToolCallEvent(review_id=1, installation_id=2, tool_name="x", duration_ms=1, result_tokens=1)
    assert event.canonical_name == "tool.called"
    assert event.model_dump(mode="json")["canonical_name"] == "tool.called"


def test_outcome_mapping_matches_plan() -> None:
    assert canonical_outcome_event("applied_directly") == "suggestion.accepted"
    assert canonical_outcome_event("applied_modified") == "suggestion.edited"
    assert canonical_outcome_event("dismissed") == "suggestion.dismissed"
    assert canonical_outcome_event("acknowledged") == "finding.resolved"
    assert canonical_outcome_event("ignored") == "finding.ignored"
    assert canonical_outcome_event("pending") is None


def test_observer_dispatches_finding_dropped_and_jsonl_sink_writes(tmp_path: Path) -> None:
    memory = InMemoryTestSink()
    jsonl_path = tmp_path / "trace.jsonl"
    observer = LLMObserver([memory, JsonlSink(str(jsonl_path))], enabled=True)
    trace = observer.start_review_trace(review_id=5, installation_id=9, run_id="r1")
    span = observer.start_stage(trace, "validation")

    observer.record_finding_dropped(
        span,
        review_id=5,
        installation_id=9,
        reason="target_line_mismatch",
        detail="line 3 differs",
        file_path="a.py",
        line_start=3,
    )
    observer.record_tool_call(span, tool_name="fetch_file_content", duration_ms=3, result_tokens=10, success=False, error_class="tool_failed")
    observer.record_outcome(review_id=5, installation_id=9, outcome="applied_modified", canonical_outcome="suggestion.edited")

    kinds = [item["event"] for item in memory.events]
    assert "finding_dropped" in kinds and "outcome" in kinds
    dropped = next(item for item in memory.events if item["event"] == "finding_dropped")
    assert dropped["payload"]["reason"] == "target_line_mismatch"
    assert dropped["payload"]["canonical_name"] == "finding.dropped"
    tool = next(item for item in memory.events if item["event"] == "tool_call")
    assert tool["payload"]["success"] is False

    lines = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert {line["event_type"] for line in lines} >= {"review_start", "stage_start", "finding_dropped", "tool_call", "outcome"}


def test_finding_dropped_event_defaults() -> None:
    event = FindingDroppedEvent(review_id=1, installation_id=1, reason="duplicate")
    assert event.stage == ""
    assert event.canonical_name == "finding.dropped"
