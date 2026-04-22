import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["critical", "high", "medium", "low"]
Category = Literal["security", "performance", "correctness", "style", "maintainability"]
ContextFidelity = Literal["high", "summary", "reference"]
DropReason = Literal[
    "target_line_mismatch",
    "line_out_of_range",
    "syntax_invalid_suggestion",
    "incoherent_suggestion",
    "line_not_in_diff",
    "file_not_in_context",
]


class Finding(BaseModel):
    severity: Severity
    category: Category
    message: str = Field(..., max_length=500)
    file_path: str
    line_start: int = Field(..., ge=1)
    line_end: int | None = None
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

    @field_validator("message")
    @classmethod
    def message_word_limit(cls, value: str) -> str:
        word_count = len(value.split())
        if word_count > 80:
            raise ValueError(f"message exceeds 80 words ({word_count})")
        return value


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


class ContextSegment(BaseModel):
    layer: Literal["project", "repo", "review"]
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
