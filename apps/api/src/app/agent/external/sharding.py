"""Compatibility shim exposing legacy sharding helpers.

The legacy API works on a list of ``ExternalFileDescriptor`` objects
(now Pydantic models) and returns a ``dict[str, list[...]]``. The new
``build_shards`` helper uses immutable ``Shard`` models; this shim keeps
both forms available.
"""

from __future__ import annotations

from app.review.external.models import FileDescriptor
from app.review.external.sharding import build_shards as _build_shards


def assign_shards(
    files: list[FileDescriptor], shard_count: int
) -> dict[str, list[FileDescriptor]]:
    """Assign files to shards keyed by ``shard-XX`` string."""

    shards = _build_shards(files, shard_count=shard_count)
    lookup: dict[str, FileDescriptor] = {item.path: item for item in files}
    return {
        shard.shard_key: [lookup[path] for path in shard.paths if path in lookup]
        for shard in shards
    }


def build_shards(
    files: list[FileDescriptor],
    *,
    shard_count: int,
    target_size: int,
    excluded_paths: set[str],
) -> list[list[FileDescriptor]]:
    """Legacy helper returning buckets of descriptors."""

    shards = _build_shards(
        files,
        shard_count=shard_count,
        shard_size_target=target_size,
        excluded_paths=excluded_paths,
    )
    lookup: dict[str, FileDescriptor] = {item.path: item for item in files}
    return [
        [lookup[path] for path in shard.paths if path in lookup]
        for shard in shards
    ]


__all__ = ["assign_shards", "build_shards"]
