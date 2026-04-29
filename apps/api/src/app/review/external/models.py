"""Pydantic models for the external repository review engine.

Every boundary of the engine — input to the CLI, input to an MCP tool,
inter-stage hand-off — is a Pydantic model. That gives us:

* JSON-schema generation for MCP tool registration,
* deterministic serialization for caching and persistence,
* runtime validation so the core never has to defensively re-check fields.

Internal helpers may still use plain dataclasses for speed where an
instance never crosses a process or cache boundary.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FindingSeverity = Literal["critical", "high", "medium", "low"]
FindingCategory = Literal[
    "security",
    "performance",
    "correctness",
    "best-practice",
    "maintainability",
    "style",
]
ServiceTier = Literal["economy", "balanced", "high"]
ShardStatus = Literal["queued", "running", "done", "skipped", "failed"]
EvaluationStatus = Literal[
    "queued",
    "scanning",
    "analyzing",
    "synthesizing",
    "complete",
    "partial",
    "failed",
    "canceled",
]

_GITHUB_REPO_URL = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RepoRef(_FrozenModel):
    """A resolved pointer to a public GitHub repository at a specific ref."""

    owner: str = Field(..., min_length=1, max_length=100)
    repo: str = Field(..., min_length=1, max_length=100)
    ref: str = Field(..., min_length=1, max_length=255)
    default_branch: str = Field(..., min_length=1, max_length=255)

    @classmethod
    def parse_url(cls, repo_url: str) -> tuple[str, str]:
        """Extract ``(owner, repo)`` from a public GitHub HTTPS URL."""

        match = _GITHUB_REPO_URL.fullmatch(repo_url.strip())
        if not match:
            raise ValueError(
                "Only public GitHub URLs in the form "
                "https://github.com/<owner>/<repo> are supported."
            )
        return match.group("owner"), match.group("repo")


class FileDescriptor(_FrozenModel):
    """Metadata for a single file in the repository tree."""

    path: str = Field(..., min_length=1)
    sha: str | None = Field(default=None, max_length=64)
    size_bytes: int = Field(..., ge=0)


class PrepassSignals(BaseModel):
    """Heuristic signals produced by the cheap pre-pass.

    These signals are deterministic and safe to cache keyed by
    ``(owner, repo, ref)``. The LLM in front of the MCP server is the
    principal consumer, so we keep the payload compact and bounded.
    """

    model_config = ConfigDict(extra="forbid")

    prompt_injection_paths: list[str] = Field(default_factory=list, max_length=500)
    filler_paths: list[str] = Field(default_factory=list, max_length=500)
    risky_paths: list[str] = Field(default_factory=list, max_length=500)
    ignored_paths_count: int = Field(default=0, ge=0)
    inspected_file_count: int = Field(default=0, ge=0)


class PrepassPlan(_FrozenModel):
    """Plan chosen by the pre-pass for downstream sharded analysis."""

    service_tier: ServiceTier
    shard_count: int = Field(..., ge=1, le=64)
    shard_size_target: int = Field(..., ge=1, le=1024)
    cheap_pass_model: str
    notes: tuple[str, ...] = ()


class Shard(_FrozenModel):
    """A group of files to analyze as a single unit."""

    shard_key: str = Field(..., min_length=1, max_length=64)
    paths: tuple[str, ...] = Field(...)

    @property
    def file_count(self) -> int:
        return len(self.paths)


class RuleMatch(_FrozenModel):
    """Raw output of a single analyzer rule firing on a single file."""

    rule_id: str
    category: FindingCategory
    severity: FindingSeverity
    title: str
    message: str
    file_path: str
    line_start: Annotated[int, Field(ge=1)]
    line_end: Annotated[int, Field(ge=1)]
    pattern: str
    excerpt: str = Field(..., max_length=512)
    confidence: float = Field(..., ge=0.0, le=1.0)


class Finding(BaseModel):
    """A critical or high-severity finding ready for persistence.

    The structure is identical to ``RuleMatch`` plus an ``evidence``
    envelope so LLM-generated findings and rule-generated findings can
    share the same storage and UI contracts.
    """

    model_config = ConfigDict(extra="forbid")

    category: FindingCategory
    severity: FindingSeverity
    title: str = Field(..., max_length=200)
    message: str = Field(..., max_length=1000)
    file_path: str
    line_start: Annotated[int, Field(ge=1)]
    line_end: Annotated[int | None, Field(ge=1)] = None
    evidence: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _coerce_line_end(self) -> "Finding":
        if self.line_end is not None and self.line_end < self.line_start:
            raise ValueError("line_end must be >= line_start")
        return self

    @classmethod
    def from_rule_match(cls, match: RuleMatch) -> "Finding":
        return cls(
            category=match.category,
            severity=match.severity,
            title=match.title,
            message=f"{match.title} detected in {match.file_path}.",
            file_path=match.file_path,
            line_start=match.line_start,
            line_end=match.line_end,
            evidence={
                "rule_id": match.rule_id,
                "pattern": match.pattern,
                "excerpt": match.excerpt,
                "confidence": match.confidence,
            },
        )


class ShardResult(BaseModel):
    """Outcome of analyzing a single shard."""

    model_config = ConfigDict(extra="forbid")

    shard_key: str
    status: ShardStatus
    file_count: int = Field(..., ge=0)
    findings: list[Finding] = Field(default_factory=list)
    tokens_used: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    skip_reason: str | None = None


class EngineConfig(BaseModel):
    """Runtime knobs for a ``ReviewEngine`` instance.

    Defaults are chosen for small-to-medium public repos; the MCP caller
    can override them per invocation.
    """

    model_config = ConfigDict(extra="forbid")

    max_files: int = Field(default=3_000, ge=1, le=50_000)
    max_shard_files: int = Field(default=200, ge=1, le=1024)
    prepass_sample_limit: int = Field(default=80, ge=0, le=2000)
    prepass_sample_bytes: int = Field(default=5_000, ge=256, le=200_000)
    analyze_sample_bytes: int = Field(default=6_000, ge=256, le=200_000)
    max_analyze_files_per_shard: int = Field(default=200, ge=1, le=2000)
    request_concurrency: int = Field(default=8, ge=1, le=64)
    http_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    token_budget_cap: int = Field(default=2_000_000, ge=10_000, le=50_000_000)
    cost_budget_cap_usd: float = Field(default=25.0, ge=0.5, le=1000.0)
    ack_required_token_threshold: int = Field(default=250_000, ge=1_000, le=50_000_000)
    ack_required_cost_threshold_usd: float = Field(default=3.0, ge=0.0, le=1000.0)
    price_per_1m_tokens_usd: float = Field(default=0.15, ge=0.0, le=500.0)
    github_token: str | None = Field(default=None, repr=False)


class StageTelemetry(_FrozenModel):
    """Structured per-stage telemetry for observability."""

    stage: str = Field(..., min_length=1, max_length=64)
    duration_ms: int = Field(..., ge=0)
    details: dict[str, int | float | str | bool] = Field(default_factory=dict)


class ReviewReport(BaseModel):
    """Top-level result returned by a full repository review."""

    model_config = ConfigDict(extra="forbid")

    repo_ref: RepoRef
    status: EvaluationStatus
    file_count: int = Field(..., ge=0)
    inspected_file_count: int = Field(..., ge=0)
    signals: PrepassSignals
    plan: PrepassPlan
    shards: list[ShardResult] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    tokens_used: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    estimated_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    summary: str = Field(default="", max_length=2000)
    truncated: bool = False
    telemetry: list[StageTelemetry] = Field(default_factory=list)
