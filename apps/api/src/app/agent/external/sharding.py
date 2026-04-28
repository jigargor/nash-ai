from __future__ import annotations

from collections import defaultdict

from app.agent.external.types import ExternalFileDescriptor


def _dirname(path: str) -> str:
    if "/" not in path:
        return "."
    return path.rsplit("/", 1)[0]


def assign_shards(files: list[ExternalFileDescriptor], shard_count: int) -> dict[str, list[ExternalFileDescriptor]]:
    if shard_count <= 0:
        shard_count = 1
    grouped: dict[str, list[ExternalFileDescriptor]] = defaultdict(list)
    for descriptor in files:
        grouped[_dirname(descriptor.path)].append(descriptor)

    sorted_groups = sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)
    shard_keys = [f"shard-{index + 1:02d}" for index in range(shard_count)]
    shard_sizes = {key: 0 for key in shard_keys}
    shards: dict[str, list[ExternalFileDescriptor]] = {key: [] for key in shard_keys}
    for _group_key, group_files in sorted_groups:
        target_key = min(shard_sizes, key=lambda key: shard_sizes[key])
        shards[target_key].extend(group_files)
        shard_sizes[target_key] += len(group_files)
    return {key: value for key, value in shards.items() if value}


def build_shards(
    files: list[ExternalFileDescriptor],
    *,
    shard_count: int,
    target_size: int,
    excluded_paths: set[str],
) -> list[list[ExternalFileDescriptor]]:
    eligible = [item for item in files if item.path not in excluded_paths]
    if not eligible:
        return []
    grouped: dict[str, list[ExternalFileDescriptor]] = defaultdict(list)
    for item in eligible:
        top_level = item.path.split("/", 1)[0] if "/" in item.path else "."
        grouped[top_level].append(item)

    buckets: list[list[ExternalFileDescriptor]] = [[] for _ in range(max(1, shard_count))]
    sizes = [0 for _ in buckets]
    group_entries = sorted(grouped.items(), key=lambda pair: len(pair[1]), reverse=True)
    for _, group_files in group_entries:
        index = min(range(len(buckets)), key=lambda idx: sizes[idx])
        buckets[index].extend(group_files)
        sizes[index] += len(group_files)

    normalized: list[list[ExternalFileDescriptor]] = []
    for bucket in buckets:
        if not bucket:
            continue
        for start in range(0, len(bucket), max(1, target_size)):
            chunk = bucket[start : start + max(1, target_size)]
            if chunk:
                normalized.append(chunk)
    return normalized

