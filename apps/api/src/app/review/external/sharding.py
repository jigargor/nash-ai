"""Deterministic file sharding for parallel analysis.

The strategy is:

1. Group files by directory so each shard tends to contain logically
   related files (better cache hits in the LLM context).
2. Distribute groups across ``shard_count`` buckets greedily by file
   count so shards stay balanced.
3. Optionally split each bucket into ``shard_size_target`` chunks to
   fit model context limits.

Returns immutable ``Shard`` models ready to ship to the worker queue
or an MCP tool result.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from app.review.external.models import FileDescriptor, Shard


def _dirname(path: str) -> str:
    if "/" not in path:
        return "."
    return path.rsplit("/", 1)[0]


def build_shards(
    files: Iterable[FileDescriptor],
    *,
    shard_count: int,
    shard_size_target: int | None = None,
    excluded_paths: set[str] | None = None,
) -> list[Shard]:
    """Produce a balanced list of ``Shard`` objects.

    Parameters
    ----------
    shard_count:
        Number of buckets to distribute files across before optional
        splitting. Must be >= 1.
    shard_size_target:
        If provided, each bucket is split into chunks of at most this
        many files (useful when downstream model context is bounded).
    excluded_paths:
        Optional set of paths to drop entirely (ignored files, vendored
        directories, skip-listed risky paths, etc.).
    """

    if shard_count <= 0:
        shard_count = 1

    excluded = excluded_paths or set()
    eligible = [descriptor for descriptor in files if descriptor.path not in excluded]
    if not eligible:
        return []

    grouped: dict[str, list[FileDescriptor]] = defaultdict(list)
    for descriptor in eligible:
        grouped[_dirname(descriptor.path)].append(descriptor)

    buckets: list[list[FileDescriptor]] = [[] for _ in range(shard_count)]
    sizes = [0 for _ in buckets]
    for _group_key, group_files in sorted(
        grouped.items(), key=lambda item: len(item[1]), reverse=True
    ):
        index = min(range(len(buckets)), key=lambda idx: sizes[idx])
        buckets[index].extend(group_files)
        sizes[index] += len(group_files)

    shards: list[Shard] = []
    shard_index = 1
    for bucket in buckets:
        if not bucket:
            continue
        if shard_size_target is None or len(bucket) <= shard_size_target:
            shards.append(
                Shard(
                    shard_key=f"shard-{shard_index:02d}",
                    paths=tuple(item.path for item in bucket),
                )
            )
            shard_index += 1
            continue
        step = max(1, shard_size_target)
        for start in range(0, len(bucket), step):
            chunk = bucket[start : start + step]
            if not chunk:
                continue
            shards.append(
                Shard(
                    shard_key=f"shard-{shard_index:02d}",
                    paths=tuple(item.path for item in chunk),
                )
            )
            shard_index += 1
    return shards
