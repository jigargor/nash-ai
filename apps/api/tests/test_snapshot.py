from __future__ import annotations

import gzip
import json

import pytest

from app.agent.snapshot import SCHEMA_VERSION, SnapshotPayload, SnapshotSchemaError


def _valid_snapshot_payload() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": "2026-04-27T00:00:00Z",
        "review_id": 1,
        "pr_metadata": {"owner": "acme", "repo": "repo", "pr_number": 1, "head_sha": "abc"},
        "diff_text": "diff --git ...",
        "system_prompt": "system",
        "user_prompt": "user",
        "context_telemetry": {},
        "review_config": {},
        "model_resolutions": {},
        "fetched_files": {"a.py": "print('hi')"},
        "chunk_plan": None,
    }


def _encode_payload(payload: dict[str, object]) -> bytes:
    return gzip.compress(json.dumps(payload).encode("utf-8"))


def test_snapshot_from_bytes_accepts_missing_optional_chunk_plan() -> None:
    payload = _valid_snapshot_payload()
    payload.pop("chunk_plan")
    snapshot = SnapshotPayload.from_bytes(_encode_payload(payload))
    assert snapshot.chunk_plan is None


def test_snapshot_from_bytes_raises_schema_error_on_missing_required_field() -> None:
    payload = _valid_snapshot_payload()
    payload.pop("diff_text")
    with pytest.raises(SnapshotSchemaError):
        SnapshotPayload.from_bytes(_encode_payload(payload))


def test_snapshot_from_bytes_raises_schema_error_on_future_version() -> None:
    payload = _valid_snapshot_payload()
    payload["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(SnapshotSchemaError):
        SnapshotPayload.from_bytes(_encode_payload(payload))
