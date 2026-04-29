"""Cheap deterministic prepass over a repository tree.

Produces ``PrepassSignals`` + ``PrepassPlan`` used to:

* warn callers about prompt-injection and filler content,
* surface risky subtrees that deserve priority analysis,
* size the sharded analysis plan.

All helpers are pure and free of I/O; the only awaitable work is a
bounded number of sample fetches through the shared ``RepoSource``.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from collections.abc import Iterable

from app.review.external.models import (
    FileDescriptor,
    PrepassPlan,
    PrepassSignals,
    RepoRef,
    ServiceTier,
)
from app.review.external.sources.base import RepoSource

_PROMPT_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+previous\s+instructions",
        r"system\s+prompt",
        r"developer\s+message",
        r"you\s+must\s+obey",
        r"bypass\s+safety",
        r"disable\s+guardrail",
    )
)

_FILLER_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(lorem ipsum(?:\s+lorem ipsum)+)",
        r"(foo|bar|baz)[\s,;]+(foo|bar|baz)[\s,;]+(foo|bar|baz)",
        r"(test|dummy|sample)[-_ ]?(data|file|content){2,}",
    )
)

_RISKY_PATH_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(^|/)\.github/workflows/",
        r"(^|/)docker",
        r"(^|/)k8s/",
        r"(^|/)terraform/",
        r"(^|/)secrets?",
        r"(^|/)auth",
        r"(^|/)middleware",
        r"(^|/)payments?",
    )
)

_IGNORED_SUFFIXES: tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".lock",
    ".min.js",
    ".svg",
)
_IGNORED_DIR_PREFIXES: tuple[str, ...] = (
    "node_modules/",
    "vendor/",
    "dist/",
    "build/",
    ".next/",
    ".git/",
)


def is_ignored_path(path: str) -> bool:
    normalized = path.strip().lower()
    if normalized.endswith(_IGNORED_SUFFIXES):
        return True
    return normalized.startswith(_IGNORED_DIR_PREFIXES)


def is_risky_path(path: str) -> bool:
    return any(pattern.search(path) for pattern in _RISKY_PATH_PATTERNS)


def looks_like_prompt_injection(text: str) -> bool:
    lowered = text.lower()
    return any(pattern.search(lowered) for pattern in _PROMPT_INJECTION_PATTERNS)


def looks_like_filler(text: str) -> bool:
    compact = " ".join(text.split())
    if any(pattern.search(compact) for pattern in _FILLER_PATTERNS):
        return True
    if len(compact) < 80:
        return False
    unique_chars = len(set(compact))
    if unique_chars <= 6:
        return True
    if max(Counter(compact).values()) > len(compact) * 0.4:
        return True
    return False


def partition_files(
    files: Iterable[FileDescriptor],
) -> tuple[list[FileDescriptor], list[str], list[str]]:
    """Split files into ``(inspectable, ignored_paths, risky_paths)``."""

    inspectable: list[FileDescriptor] = []
    ignored_paths: list[str] = []
    risky_paths: list[str] = []
    for descriptor in files:
        if is_ignored_path(descriptor.path):
            ignored_paths.append(descriptor.path)
            continue
        inspectable.append(descriptor)
        if is_risky_path(descriptor.path):
            risky_paths.append(descriptor.path)
    return inspectable, ignored_paths, risky_paths


def recommended_plan(
    *,
    file_count: int,
    risky_paths: int,
    cheap_pass_model: str,
) -> PrepassPlan:
    """Choose service tier + shard geometry based on repo footprint."""

    if file_count >= 2_500 or risky_paths >= 120:
        return PrepassPlan(
            service_tier="high",
            shard_count=20,
            shard_size_target=140,
            cheap_pass_model=cheap_pass_model,
            notes=("Large repository footprint; prioritize high-risk areas first.",),
        )
    if file_count >= 800 or risky_paths >= 40:
        return PrepassPlan(
            service_tier="balanced",
            shard_count=10,
            shard_size_target=120,
            cheap_pass_model=cheap_pass_model,
            notes=("Medium repository footprint; use balanced shard concurrency.",),
        )
    return PrepassPlan(
        service_tier="economy",
        shard_count=4,
        shard_size_target=100,
        cheap_pass_model=cheap_pass_model,
        notes=("Smaller repository; fewer shards reduce coordination overhead.",),
    )


async def run_prepass(
    *,
    source: RepoSource,
    repo_ref: RepoRef,
    files: list[FileDescriptor],
    cheap_pass_model: str,
    sample_limit: int = 80,
    sample_bytes: int = 5_000,
    concurrency: int = 8,
) -> tuple[PrepassSignals, PrepassPlan]:
    """Execute the cheap pre-pass and return ``(signals, plan)``.

    Fetches up to ``sample_limit`` files concurrently (bounded by
    ``concurrency``) so even moderately sized repos prepass in seconds.
    """

    inspectable, ignored_paths, risky_paths = partition_files(files)

    signals = PrepassSignals(
        risky_paths=risky_paths[:500],
        ignored_paths_count=len(ignored_paths),
        inspected_file_count=min(len(inspectable), sample_limit),
    )

    targets = inspectable[:sample_limit]
    if targets:
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def _inspect(descriptor: FileDescriptor) -> tuple[str, str]:
            async with semaphore:
                sample = await source.fetch_file(
                    repo_ref, descriptor.path, max_bytes=sample_bytes
                )
            return descriptor.path, sample

        results = await asyncio.gather(
            *[_inspect(descriptor) for descriptor in targets],
            return_exceptions=False,
        )
        for path, sample in results:
            if not sample:
                continue
            if looks_like_prompt_injection(sample):
                signals.prompt_injection_paths.append(path)
            if looks_like_filler(sample):
                signals.filler_paths.append(path)

    plan = recommended_plan(
        file_count=len(inspectable),
        risky_paths=len(risky_paths),
        cheap_pass_model=cheap_pass_model,
    )
    return signals, plan


def select_service_tier(plan: PrepassPlan) -> ServiceTier:
    return plan.service_tier
