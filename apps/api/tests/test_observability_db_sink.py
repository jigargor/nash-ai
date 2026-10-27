"""DBSink persists drop/validation/delivery-rejection diagnostics (no real DB needed)."""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Any

from app.db.models import ReviewModelAudit
from app.observability.events import (
    DeliveryRejectedEvent,
    FindingDroppedEvent,
    ValidationEvent,
)
from app.observability.sinks import DBSink


class _FakeResult:
    def __init__(self, row: ReviewModelAudit | None) -> None:
        self._row = row

    def scalars(self) -> _FakeResult:
        return self

    def first(self) -> ReviewModelAudit | None:
        return self._row


class _FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class _FakeSession:
    def __init__(self, store: list[ReviewModelAudit]) -> None:
        self._store = store

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction()

    async def execute(self, _stmt: object) -> _FakeResult:
        return _FakeResult(self._store[0] if self._store else None)

    def add(self, row: ReviewModelAudit) -> None:
        self._store.append(row)


def _make_sink() -> tuple[DBSink, list[ReviewModelAudit]]:
    store: list[ReviewModelAudit] = []

    def factory() -> _FakeSession:
        return _FakeSession(store)

    return DBSink(session_factory=factory), store


def _common() -> dict[str, Any]:
    return {
        "review_id": 1,
        "installation_id": 2,
        "run_id": "run-1",
        "trace_id": "trace-1",
        "stage": "validation",
    }


async def _drain(coro_fn: Any) -> None:
    coro_fn()
    # Let fire-and-forget tasks scheduled by the sink complete.
    await asyncio.sleep(0)
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)


def test_db_sink_persists_finding_dropped_validation_and_delivery_rejected() -> None:
    sink, store = _make_sink()

    async def scenario() -> None:
        await _drain(
            lambda: sink.on_finding_dropped(
                FindingDroppedEvent(
                    **_common(),
                    reason="target_line_mismatch",
                    detail="x" * 2000,
                    file_path="a.py",
                    line_start=7,
                    finding_id="f1",
                )
            )
        )
        await _drain(
            lambda: sink.on_validation(
                ValidationEvent(
                    **_common(),
                    validation_type="finding_validation",
                    passed=False,
                    errors=["bad anchor"],
                    findings_before=3,
                    findings_after=2,
                    drop_reason="target_line_mismatch",
                )
            )
        )
        await _drain(
            lambda: sink.on_delivery_rejected(
                DeliveryRejectedEvent(
                    **_common(),
                    file_path="a.py",
                    line_start=7,
                    error_class="UnprocessableEntity",
                )
            )
        )

    asyncio.run(scenario())

    assert len(store) == 1
    meta = store[0].metadata_json
    assert meta["trace_id"] == "trace-1"
    dropped = meta["dropped_findings"]
    assert dropped[0]["reason"] == "target_line_mismatch"
    assert dropped[0]["finding_id"] == "f1"
    assert len(dropped[0]["detail"]) == 500  # truncated; never persist unbounded code text
    assert meta["validations"][0]["passed"] is False
    assert meta["validations"][0]["findings_after"] == 2
    assert meta["delivery_rejections"][0]["error_class"] == "UnprocessableEntity"


def test_db_sink_caps_persisted_entries() -> None:
    sink, store = _make_sink()

    async def scenario() -> None:
        for index in range(60):
            await _drain(
                lambda index=index: sink.on_finding_dropped(
                    FindingDroppedEvent(**_common(), reason="line_not_in_diff", line_start=index)
                )
            )

    asyncio.run(scenario())

    meta = store[0].metadata_json
    assert len(meta["dropped_findings"]) == 50
    assert meta["dropped_findings_truncated"] is True


def test_db_sink_without_session_factory_is_noop() -> None:
    sink = DBSink(session_factory=None)
    sink.on_finding_dropped(FindingDroppedEvent(**_common(), reason="x"))
    sink.on_delivery_rejected(DeliveryRejectedEvent(**_common()))
    sink.on_validation(ValidationEvent(**_common(), validation_type="t", passed=True))
