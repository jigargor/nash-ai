"""Context snapshot capture and retrieval for eval replay.

A snapshot records everything fed to the LLM for a single review: diff text,
resolved prompts, context telemetry, effective config, and all files fetched
from GitHub.  This makes it possible to replay any production review offline
without re-fetching data from GitHub.

Storage: one row in review_context_snapshots per review, gzip-compressed JSON.
Capture is fire-and-forget from runner.py — a failure here never aborts a review.
Export: see evals/export_snapshot.py for writing a snapshot to an eval dataset dir.
"""

import dataclasses
import gzip
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db.models import ReviewContextSnapshot
from app.db.session import AsyncSessionLocal
from app.storage.r2_snapshots import download_snapshot_from_r2, upload_snapshot_to_r2

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "authorization",
    "api_key",
    "private_key",
    "cookie",
)
_SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._-]{8,}"),
    re.compile(r"(?i)\b(gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{16,})\b"),
    re.compile(r"(?i)\b(sk-[A-Za-z0-9]{16,})\b"),
    re.compile(r"(?i)\b(cookie|token|api[_-]?key|secret|password)\s*[:=]\s*[^\s]+"),
]


class SnapshotSchemaError(ValueError):
    """Raised when a stored snapshot cannot be decoded into the current schema."""


# ---------------------------------------------------------------------------
# Payload definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SnapshotPayload:
    """Immutable snapshot of the full LLM input for one review."""

    review_id: int
    pr_metadata: dict[str, Any]       # owner, repo, pr_number, head_sha, title
    diff_text: str
    system_prompt: str
    user_prompt: str
    context_telemetry: dict[str, Any]  # ContextTelemetry.as_dict()
    review_config: dict[str, Any]      # serialized ReviewConfig
    model_resolutions: dict[str, Any]  # context["llm_model_resolutions"]
    fetched_files: dict[str, str]      # {path: content}
    chunk_plan: dict[str, Any] | None = None  # None for non-chunked reviews

    def to_bytes(self) -> bytes:
        payload = _serialize_payload(
            {
            "schema_version": SCHEMA_VERSION,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            **dataclasses.asdict(self),
        }
        )
        return gzip.compress(
            json.dumps(payload, default=_json_default).encode("utf-8"),
            compresslevel=6,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "SnapshotPayload":
        raw = json.loads(gzip.decompress(data).decode("utf-8"))
        schema_version_raw = raw.pop("schema_version", None)
        raw.pop("captured_at", None)
        if isinstance(schema_version_raw, int) and schema_version_raw > SCHEMA_VERSION:
            raise SnapshotSchemaError(
                f"Snapshot schema version {schema_version_raw} is newer than supported {SCHEMA_VERSION}"
            )
        missing_required: list[str] = []
        payload: dict[str, Any] = {}
        for field in dataclasses.fields(cls):
            if field.name in raw:
                payload[field.name] = raw[field.name]
                continue
            if field.default is not dataclasses.MISSING:
                payload[field.name] = field.default
                continue
            if field.default_factory is not dataclasses.MISSING:
                payload[field.name] = field.default_factory()
                continue
            missing_required.append(field.name)
        if missing_required:
            raise SnapshotSchemaError(
                "Snapshot payload is missing required fields: " + ", ".join(sorted(missing_required))
            )
        try:
            return cls(**payload)
        except TypeError as exc:
            raise SnapshotSchemaError(f"Snapshot payload schema mismatch: {exc}") from exc


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def store_snapshot(payload: SnapshotPayload, *, installation_id: int) -> None:
    """Upsert snapshot — reruns overwrite so the latest state always wins."""
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.snapshot_retention_days)
    blob = payload.to_bytes()
    stmt = (
        pg_insert(ReviewContextSnapshot)
        .values(
            review_id=payload.review_id,
            installation_id=installation_id,
            expires_at=expires_at,
            archived_at=None,
            r2_object_key=None,
            schema_version=SCHEMA_VERSION,
            snapshot_gz=blob,
        )
        .on_conflict_do_update(
            index_elements=["review_id"],
            set_={
                "installation_id": installation_id,
                "expires_at": expires_at,
                "archived_at": None,
                "r2_object_key": None,
                "schema_version": SCHEMA_VERSION,
                "snapshot_gz": blob,
                "captured_at": datetime.now(timezone.utc),
            },
        )
    )
    async with AsyncSessionLocal() as session:
        await session.execute(stmt)
        await session.commit()


async def load_snapshot(review_id: int) -> SnapshotPayload | None:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(ReviewContextSnapshot).where(
                    ReviewContextSnapshot.review_id == review_id
                )
            )
        ).scalar_one_or_none()
    if row is None:
        return None
    if row.snapshot_gz is None and isinstance(row.r2_object_key, str) and row.r2_object_key.strip():
        archived_blob = await download_snapshot_from_r2(object_key=row.r2_object_key.strip())
        if archived_blob is not None:
            try:
                return SnapshotPayload.from_bytes(archived_blob)
            except SnapshotSchemaError:
                logger.warning(
                    "Failed to decode archived snapshot review_id=%s due to schema mismatch",
                    review_id,
                )
                return None
        return None
    if row.snapshot_gz is None:
        return None
    try:
        return SnapshotPayload.from_bytes(row.snapshot_gz)
    except SnapshotSchemaError:
        logger.warning("Failed to decode snapshot review_id=%s due to schema mismatch", review_id)
        return None


async def archive_expired_snapshots(batch_size: int | None = None) -> int:
    if not settings.has_r2_snapshot_archive_configured():
        return 0
    now = datetime.now(timezone.utc)
    limit = batch_size or settings.snapshot_archive_batch_size
    archived_count = 0
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(ReviewContextSnapshot)
                .where(ReviewContextSnapshot.expires_at.is_not(None))
                .where(ReviewContextSnapshot.expires_at <= now)
                .where(ReviewContextSnapshot.archived_at.is_(None))
                .where(ReviewContextSnapshot.snapshot_gz.is_not(None))
                .order_by(ReviewContextSnapshot.expires_at.asc())
                .limit(limit)
            )
        ).scalars()
        for row in rows:
            if row.snapshot_gz is None:
                continue
            object_key = _snapshot_object_key(
                installation_id=int(row.installation_id),
                review_id=int(row.review_id),
            )
            try:
                await upload_snapshot_to_r2(object_key=object_key, payload=row.snapshot_gz)
            except Exception:
                logger.warning(
                    "Failed to archive snapshot review_id=%s object_key=%s",
                    int(row.review_id),
                    object_key,
                    exc_info=True,
                )
                continue
            row.r2_object_key = object_key
            row.archived_at = now
            row.snapshot_gz = None
            archived_count += 1
        if archived_count > 0:
            await session.commit()
    return archived_count


# ---------------------------------------------------------------------------
# JSON serialisation helpers
# ---------------------------------------------------------------------------


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serialisable")


def _serialize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = _redact_value(payload, parent_key=None)
    if isinstance(redacted, dict):
        return redacted
    return payload


def _redact_value(value: Any, *, parent_key: str | None) -> Any:
    if _is_sensitive_key(parent_key):
        return _REDACTED
    if isinstance(value, dict):
        return {key: _redact_value(item, parent_key=key) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, parent_key=parent_key) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item, parent_key=parent_key) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return redacted


def _is_sensitive_key(key: str | None) -> bool:
    if key is None:
        return False
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _snapshot_object_key(*, installation_id: int, review_id: int) -> str:
    prefix = settings.r2_snapshot_prefix.strip("/") if settings.r2_snapshot_prefix else "review-snapshots"
    return f"{prefix}/{installation_id}/{review_id}.json.gz"
