from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.agent import snapshot as snapshot_module
from app.agent.snapshot import SCHEMA_VERSION, SnapshotPayload, SnapshotSchemaError
from app.agent.schema import ContextBudgets
from app.config import settings
from app.db.models import ReviewContextSnapshot
from app.db.session import AsyncSessionLocal, set_installation_context
from conftest import _insert_installation, _insert_review, _random_installation_id


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


def test_snapshot_to_bytes_redacts_sensitive_fields_and_tokens() -> None:
    payload = SnapshotPayload(
        review_id=42,
        pr_metadata={"owner": "acme", "repo": "repo", "pr_number": 3, "head_sha": "abc"},
        diff_text='Authorization: Bearer top-secret-token\napi_key="sk-ABCDEF1234567890"',
        system_prompt="system prompt",
        user_prompt="github token ghp_abcdefghijklmnopqrstuvwxyz123456",
        context_telemetry={"request_secret": "hidden-secret-value"},
        review_config={"provider_api_key": "super-secret"},
        model_resolutions={},
        fetched_files={"sample.txt": "cookie=session-value"},
        chunk_plan=None,
    )

    raw = json.loads(gzip.decompress(payload.to_bytes()).decode("utf-8"))
    assert raw["context_telemetry"]["request_secret"] == "[REDACTED]"
    assert raw["review_config"]["provider_api_key"] == "[REDACTED]"
    assert "[REDACTED]" in raw["diff_text"]
    assert "[REDACTED]" in raw["user_prompt"]
    assert raw["fetched_files"]["sample.txt"] == "[REDACTED]"


def test_snapshot_to_bytes_serializes_pydantic_context_budgets() -> None:
    payload = SnapshotPayload(
        review_id=77,
        pr_metadata={"owner": "acme", "repo": "repo", "pr_number": 8, "head_sha": "abc"},
        diff_text="diff --git a/x.py b/x.py",
        system_prompt="system",
        user_prompt="user",
        context_telemetry={},
        review_config={"budgets": ContextBudgets(total_cap=54321)},
        model_resolutions={},
        fetched_files={},
        chunk_plan=None,
    )

    raw = json.loads(gzip.decompress(payload.to_bytes()).decode("utf-8"))
    assert raw["review_config"]["budgets"]["total_cap"] == 54321


@pytest.mark.anyio
async def test_archive_expired_snapshots_moves_blob_and_load_reads_archived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation_id = _random_installation_id()
    await _insert_installation(installation_id)
    review_id = await _insert_review(installation_id, status="done")

    payload = SnapshotPayload(
        review_id=review_id,
        pr_metadata={
            "owner": "acme",
            "repo": "repo",
            "pr_number": 11,
            "head_sha": "a" * 40,
            "title": "snapshot archive test",
        },
        diff_text="diff --git a/app.py b/app.py",
        system_prompt="system",
        user_prompt="user",
        context_telemetry={},
        review_config={},
        model_resolutions={},
        fetched_files={"app.py": "print('ok')"},
        chunk_plan=None,
    )
    await snapshot_module.store_snapshot(payload, installation_id=installation_id)

    original_blob: bytes | None = None
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        row = await session.scalar(
            select(ReviewContextSnapshot).where(ReviewContextSnapshot.review_id == review_id)
        )
        assert row is not None
        original_blob = row.snapshot_gz
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await session.commit()

    uploaded: dict[str, bytes] = {}

    async def _fake_upload_snapshot_to_r2(*, object_key: str, payload: bytes) -> None:
        uploaded[object_key] = payload

    async def _fake_download_snapshot_from_r2(*, object_key: str) -> bytes | None:
        return uploaded.get(object_key)

    monkeypatch.setattr(settings, "r2_endpoint_url", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setattr(settings, "r2_bucket", "snapshot-bucket")
    monkeypatch.setattr(settings, "r2_access_key_id", "key-id")
    monkeypatch.setattr(settings, "r2_secret_access_key", "key-secret")
    monkeypatch.setattr(snapshot_module, "upload_snapshot_to_r2", _fake_upload_snapshot_to_r2)
    monkeypatch.setattr(snapshot_module, "download_snapshot_from_r2", _fake_download_snapshot_from_r2)

    archived = await snapshot_module.archive_expired_snapshots(batch_size=10)
    assert archived == 1

    async with AsyncSessionLocal() as session:
        row = await session.scalar(
            select(ReviewContextSnapshot).where(ReviewContextSnapshot.review_id == review_id)
        )
        assert row is not None
        assert row.archived_at is not None
        assert row.snapshot_gz is None
        assert isinstance(row.r2_object_key, str)
        assert row.r2_object_key in uploaded
        assert uploaded[row.r2_object_key] == original_blob

    loaded = await snapshot_module.load_snapshot(review_id)
    assert loaded is not None
    assert loaded.review_id == review_id
    assert loaded.pr_metadata["title"] == "snapshot archive test"
