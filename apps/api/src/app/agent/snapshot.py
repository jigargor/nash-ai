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
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import ReviewContextSnapshot
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


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
    chunk_plan: dict[str, Any] | None  # None for non-chunked reviews

    def to_bytes(self) -> bytes:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            **dataclasses.asdict(self),
        }
        return gzip.compress(
            json.dumps(payload, default=_json_default).encode("utf-8"),
            compresslevel=6,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "SnapshotPayload":
        raw = json.loads(gzip.decompress(data).decode("utf-8"))
        raw.pop("schema_version", None)
        raw.pop("captured_at", None)
        return cls(**{k: raw[k] for k in dataclasses.fields(cls) if k in raw})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def store_snapshot(payload: SnapshotPayload) -> None:
    """Upsert snapshot — reruns overwrite so the latest state always wins."""
    blob = payload.to_bytes()
    stmt = (
        pg_insert(ReviewContextSnapshot)
        .values(
            review_id=payload.review_id,
            schema_version=SCHEMA_VERSION,
            snapshot_gz=blob,
        )
        .on_conflict_do_update(
            index_elements=["review_id"],
            set_={
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
    return SnapshotPayload.from_bytes(row.snapshot_gz)


# ---------------------------------------------------------------------------
# JSON serialisation helpers
# ---------------------------------------------------------------------------


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serialisable")
