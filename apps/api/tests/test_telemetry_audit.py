from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent import telemetry_audit


@pytest.mark.anyio
async def test_summarize_target_line_mismatch_telemetry_aggregates_subtypes(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        (1, {"target_line_mismatch_subtypes": {"a": 2, "b": 1}}),
        (2, None),
        (3, {"target_line_mismatch_subtypes": "not-a-dict"}),
    ]
    fake_result = MagicMock()
    fake_result.all.return_value = rows

    fake_session = MagicMock()
    fake_session.execute = AsyncMock(return_value=fake_result)
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(telemetry_audit, "AsyncSessionLocal", lambda: fake_session)

    summary = await telemetry_audit.summarize_target_line_mismatch_telemetry(limit=50)

    assert summary["review_count"] == 3
    assert summary["reviews_with_debug_artifacts"] == 2
    assert summary["total_target_line_mismatch_drops"] == 3
    assert summary["subtypes"] == {"a": 2, "b": 1}
