from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ProbeAction = Literal[
    "none",
    "audit_only",
    "require_human_review",
    "rerun_finalizer",
    "restore_candidate",
]

ProbeReasonCode = Literal[
    "missing_from_final",
    "severity_downgraded_without_evidence",
    "deduplicated_into_weaker_finding",
    "editor_removed_anchor",
    "safe_counterpattern_applies",
    "insufficient_evidence",
    "prompt_injection_suspected",
    "budget_cap_reached",
    "probe_error",
]


class ProbeCandidate(BaseModel):
    candidate_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=500)
    severity: Literal["critical", "high", "medium", "low"]
    category: Literal["security", "performance", "correctness", "style", "maintainability"]
    path: str = Field(..., min_length=1)
    line_start: int = Field(..., ge=1)
    line_end: int | None = Field(default=None, ge=1)
    evidence: Literal["tool_verified", "diff_visible", "verified_fact", "inference"]
    evidence_fact_id: str | None = None
    summary_hash: str = Field(..., min_length=4, max_length=64)


class ProbeSuppressedCandidate(BaseModel):
    candidate_id: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    line_start: int = Field(..., ge=1)
    original_severity: Literal["critical", "high", "medium", "low"]
    final_state: Literal["missing", "downgraded", "deduplicated", "kept"]
    reason_code: ProbeReasonCode
    deterministic_reason: str | None = None


class ProbeRequest(BaseModel):
    review_id: int = Field(..., ge=1)
    installation_id: int = Field(..., ge=1)
    draft_candidates: list[ProbeCandidate] = Field(default_factory=list)
    final_candidates: list[ProbeCandidate] = Field(default_factory=list)
    stripped_evidence: list[str] = Field(default_factory=list)
    config_snapshot: dict[str, object] = Field(default_factory=dict)
    deterministic_reason: str | None = None


class ProbeResult(BaseModel):
    suppression_detected: bool = False
    suppressed_candidates: list[ProbeSuppressedCandidate] = Field(default_factory=list)
    confidence: int = Field(default=0, ge=0, le=100)
    recommended_action: ProbeAction = "none"
    reason_codes: list[ProbeReasonCode] = Field(default_factory=list)
    rationale: str = ""
    model: str | None = None
    provider: str | None = None
    skipped_reason: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class DeterministicSuppression(BaseModel):
    candidate: ProbeCandidate
    reason_code: ProbeReasonCode
    deterministic_reason: str
    unresolved: bool = False


class SuppressionAudit(BaseModel):
    draft_count: int = Field(default=0, ge=0)
    final_count: int = Field(default=0, ge=0)
    suppressed: list[DeterministicSuppression] = Field(default_factory=list)
    unresolved_high_risk: list[DeterministicSuppression] = Field(default_factory=list)

