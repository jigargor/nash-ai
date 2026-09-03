import re
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import TypedDict

from app.categories import CanonicalCategory as Category

if TYPE_CHECKING:
    from app.github.client import GitHubClient


class RunContext(TypedDict, total=False):
    """Mutable bag passed through the review pipeline stages in runner.py.

    Keys marked with `total=False` may be absent early in the pipeline and
    are progressively populated as stages complete.
    """

    review_id: int
    installation_id: int
    owner: str
    repo: str
    pr_number: int
    head_sha: str
    github_client: "GitHubClient"
    fetched_files: dict[str, str]
    input_tokens: int
    output_tokens: int
    tokens_used: int
    debug_artifacts: dict[str, Any]
    agent_metrics: dict[str, Any]


FastPathDecisionValue = Literal["skip_review", "light_review", "full_review", "high_risk_review"]


class FastPathAuditMetadata(BaseModel):
    """Typed metadata contract for fast-path stage telemetry and UI rendering."""

    model_config = ConfigDict(extra="forbid")

    decision: FastPathDecisionValue
    risk_labels: list[str] = Field(default_factory=list)
    confidence: int | None = Field(default=None, ge=0, le=100)
    confidence_source: str = "model"
    reason: str
    review_surface_paths: list[str] = Field(default_factory=list)
    review_surface_count: int = Field(default=0, ge=0)
    # Backward-compat key retained while clients migrate to review_surface_paths.
    review_surface: list[str] = Field(default_factory=list)
    requires_full_context: bool = True
    fallback_reason: str | None = None
    diff_tokens: int = Field(default=0, ge=0)
    changed_file_count: int = Field(default=0, ge=0)
    changed_line_count: int = Field(default=0, ge=0)
    file_classes: dict[str, int] = Field(default_factory=dict)
    skip_min_confidence_applied: int = Field(default=0, ge=0)
    light_review_min_confidence_applied: int = Field(default=0, ge=0)
    produces_findings: bool = False

    @model_validator(mode="after")
    def check_surface_count(self) -> "FastPathAuditMetadata":
        expected = len(self.review_surface_paths)
        if self.review_surface_count != expected:
            raise ValueError(
                f"review_surface_count={self.review_surface_count} does not match "
                f"review_surface_paths length={expected}"
            )
        return self


Severity = Literal["critical", "high", "medium", "low"]
Evidence = Literal["tool_verified", "diff_visible", "verified_fact", "inference"]
ContextFidelity = Literal["high", "summary", "reference"]
DropReason = Literal[
    "target_line_mismatch",
    "line_out_of_range",
    "syntax_invalid_suggestion",
    "incoherent_suggestion",
    "line_not_in_diff",
    "file_not_in_context",
    "validator_error",
]


class Finding(BaseModel):
    severity: Severity
    category: Category
    message: str = Field(..., max_length=500)
    file_path: str
    line_start: int = Field(..., ge=1)
    line_end: int | None = None
    finding_id: str | None = Field(
        default=None,
        description="Stable id for delivery markers and outcome tracking (optional).",
    )
    target_line_content: str = Field(
        ...,
        max_length=2000,
        description="The exact content of line_start as it appears in the file at HEAD.",
    )
    suggestion: str | None = Field(None, description="Code block to replace lines with")
    confidence: int = Field(
        ...,
        ge=0,
        le=100,
        description=(
            "Calibrated confidence this finding is correct and actionable. "
            "95-100: verified via tool call, no plausible counter-argument. "
            "80-94: strong evidence from diff + context. "
            "60-79: plausible but unverified. "
            "40-59: speculative (only submit if severity is critical). "
            "Below 40: do not submit."
        ),
    )
    verified_via_tool: bool = Field(
        default=False,
        description="True if a tool call was made that touched this file during the review.",
    )
    evidence: Evidence
    evidence_tool_calls: list[str] | None = Field(
        default=None,
        description="Tool names called to verify this finding. Required when evidence == 'tool_verified'.",
    )
    evidence_fact_id: str | None = Field(
        default=None,
        description="ID from verified_facts.yaml. Required when evidence == 'verified_fact'.",
    )
    is_vendor_claim: bool = Field(
        default=False,
        description=(
            "True if the finding's correctness depends on external vendor, "
            "platform, framework, or library behavior. See vendor-claim rules."
        ),
    )
    side: Literal["RIGHT", "LEFT"] = Field(
        default="RIGHT",
        description="GitHub diff side anchor for line.",
    )
    start_side: Literal["RIGHT", "LEFT"] | None = Field(
        default=None,
        description="GitHub diff side anchor for start_line in multi-line comments.",
    )
    old_line_no: int | None = Field(default=None, ge=1)
    new_line_no: int | None = Field(default=None, ge=1)
    patch_hunk: str | None = Field(
        default=None,
        description="Best-effort diff hunk identifier used for anchor diagnostics.",
    )

    @field_validator("message")
    @classmethod
    def message_word_limit(cls, value: str) -> str:
        word_count = len(value.split())
        if word_count > 80:
            raise ValueError(f"message exceeds 80 words ({word_count})")
        return value

    @model_validator(mode="after")
    def check_evidence_consistency(self) -> "Finding":
        if self.severity == "critical" and self.evidence != "tool_verified":
            raise ValueError(
                f"critical severity requires evidence='tool_verified', got '{self.evidence}'"
            )
        if self.severity == "high" and self.evidence == "inference":
            raise ValueError("high severity may not use evidence='inference'")

        if self.evidence == "inference":
            if self.severity not in {"low", "medium"}:
                raise ValueError("evidence='inference' is permitted only for low/medium severity")
            if self.confidence > 75:
                raise ValueError(f"inference evidence caps confidence at 75, got {self.confidence}")

        if self.evidence == "tool_verified" and not self.evidence_tool_calls:
            raise ValueError("evidence='tool_verified' requires evidence_tool_calls")
        if self.evidence == "verified_fact" and not self.evidence_fact_id:
            raise ValueError("evidence='verified_fact' requires evidence_fact_id")

        return self

    @model_validator(mode="after")
    def check_vendor_claim_evidence(self) -> "Finding":
        if not self.is_vendor_claim:
            return self

        if self.severity == "critical" and self.evidence != "tool_verified":
            raise ValueError("Vendor claims at critical severity require evidence='tool_verified'")
        if self.severity == "high" and self.evidence not in ("tool_verified", "verified_fact"):
            raise ValueError(
                "Vendor claims at high severity require 'tool_verified' or 'verified_fact'"
            )
        if self.evidence != "tool_verified" and self.confidence > 85:
            raise ValueError("Vendor claims without tool_verified evidence cap confidence at 85")

        return self


class ReviewResult(BaseModel):
    findings: list[Finding]
    summary: str = Field(..., max_length=800)

    @field_validator("summary")
    @classmethod
    def summary_sentence_limit(cls, value: str) -> str:
        sentences = len(re.findall(r"[.!?](?:\s|$)", value))
        if sentences > 8:
            raise ValueError(f"summary exceeds 8 sentences ({sentences})")
        return value


class EditorDecision(BaseModel):
    original_index: int
    action: Literal["keep", "drop", "modify"]
    reason: str | None = None
    changes: dict[str, object] | None = None


class EditedReview(BaseModel):
    findings: list[Finding]
    summary: str = Field(..., max_length=800)
    decisions: list[EditorDecision]


class ContextBudgets(BaseModel):
    system_prompt: int = Field(default=3000, ge=0)
    repo_profile: int = Field(default=1500, ge=0)
    repo_additions: int = Field(default=1000, ge=0)
    diff_hunks: int = Field(default=40_000, ge=0)
    surrounding_context: int = Field(default=15_000, ge=0)
    fetched_files_headroom: int = Field(default=20_000, ge=0)
    output: int = Field(default=8000, ge=0)
    total_cap: int = Field(default=120_000, ge=1)
    pressure_yellow: float = Field(default=0.60, ge=0.0, le=1.0)
    pressure_orange: float = Field(default=0.80, ge=0.0, le=1.0)
    pressure_red: float = Field(default=0.95, ge=0.0, le=1.0)
    enforcement: Literal["observe", "advise", "enforce"] = "observe"


class ContextSegment(BaseModel):
    layer: Literal[
        "project",
        "repo",
        "review",
        "L0.base_static",
        "L1.repo_profile",
        "L2.repo_dynamic",
        "L3.user_policy",
        "L4.review_hunks",
        "L5.surrounding_context",
        "L6.anchors",
        "L7.tool_results",
        "L8.output_reserve",
    ]
    source_id: str
    fidelity: ContextFidelity
    text: str
    token_count: int = Field(ge=0)
    file_path: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    score: float | None = None


class ContextAnchor(BaseModel):
    file_path: str
    line_no: int = Field(ge=1)
    line_content: str


class LayeredContextPackage(BaseModel):
    project: list[ContextSegment] = Field(default_factory=list)
    repo: list[ContextSegment] = Field(default_factory=list)
    review: list[ContextSegment] = Field(default_factory=list)
    anchors: list[ContextAnchor] = Field(default_factory=list)
    ignored_anchor_files: list[str] = Field(default_factory=list)
    anchor_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    dropped_segments: list[str] = Field(default_factory=list)
    summarization_used: bool = False
    summarization_calls: int = Field(default=0, ge=0)
    partial_review_mode: bool = False
    partial_review_note: str | None = None

    def all_segments(self) -> list[ContextSegment]:
        return [*self.project, *self.repo, *self.review]


class CommitSummary(BaseModel):
    sha: str | None = None
    message: str = ""


class PRContext(BaseModel):
    """Shared PR input for worker and eval harness (extend, do not fork)."""

    model_config = ConfigDict(extra="forbid")

    owner: str
    repo: str
    pr_number: int = Field(ge=1)
    head_sha: str
    base_sha: str | None = None
    title: str = ""
    body: str = ""
    draft: bool = False
    commits: list[CommitSummary] = Field(default_factory=list)
    diff_text: str = ""
    files_at_head: dict[str, str] = Field(default_factory=dict)
    commentable_lines: list[tuple[str, int]] = Field(default_factory=list)
    ignore_paths: list[str] = Field(default_factory=list)
    prompt_additions: str | None = None
    installation_id: int | None = None
    review_id: int | None = None
    diff_cross_check_warnings: list[str] = Field(
        default_factory=list,
        description="Files API vs unidiff line-number disagreements (anchoring probe).",
    )

    @property
    def repo_full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


class DroppedFinding(BaseModel):
    """A finding removed by some stage.

    ``finding`` is a plain JSON snapshot (not a ``Finding``) on purpose: rejected findings
    are often in a state that fails ``Finding`` validation (that is why they were dropped),
    so re-validating them here would turn a routine drop into a stage failure.
    """

    finding: dict[str, Any] | None = None
    reason: DropReason | str
    detail: str | None = None
    stage: str = "validation"

    @classmethod
    def from_finding(
        cls,
        finding: Finding | None,
        *,
        reason: DropReason | str,
        detail: str | None = None,
        stage: str = "validation",
    ) -> "DroppedFinding":
        snapshot: dict[str, Any] | None = None
        if finding is not None:
            snapshot = finding.model_dump(mode="json")
        return cls(finding=snapshot, reason=reason, detail=detail, stage=stage)

    @property
    def file_path(self) -> str:
        return str((self.finding or {}).get("file_path") or "")

    @property
    def line_start(self) -> int:
        try:
            return int((self.finding or {}).get("line_start") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def finding_id(self) -> str | None:
        value = (self.finding or {}).get("finding_id")
        return str(value) if value else None


class ToolTraceEntry(BaseModel):
    tool_name: str
    success: bool
    duration_ms: int = 0
    input_hash: str = ""
    output_hash: str = ""
    error: str | None = None


class ReviewRunReport(BaseModel):
    """Full pipeline output for harness metrics and production debug."""

    model_config = ConfigDict(extra="forbid")

    result: ReviewResult
    drops: list[DroppedFinding] = Field(default_factory=list)
    tool_trace: list[ToolTraceEntry] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    tokens_used: int = 0
    cached_input_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: int = 0
    stage_latencies_ms: dict[str, int] = Field(default_factory=dict)
    exceptions: list[str] = Field(default_factory=list)
    pipeline_errors: list[str] = Field(default_factory=list)
    models_served: list[str] = Field(default_factory=list)
    providers_served: list[str] = Field(default_factory=list)
    prompt_version: str | None = None
    system_prompt: str | None = None
    user_prompt: str | None = None
    dry_run: bool = True
    delivery: dict[str, object] = Field(default_factory=dict)
    debug_artifacts: dict[str, object] = Field(default_factory=dict)
