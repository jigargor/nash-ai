from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ExternalFileDescriptor:
    path: str
    sha: str | None
    size_bytes: int


@dataclass(slots=True)
class PrepassSignals:
    prompt_injection_paths: list[str] = field(default_factory=list)
    filler_paths: list[str] = field(default_factory=list)
    risky_paths: list[str] = field(default_factory=list)
    ignored_paths: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PrepassPlan:
    service_tier: str
    shard_count: int
    shard_size_target: int
    cheap_pass_model: str
    notes: list[str] = field(default_factory=list)

