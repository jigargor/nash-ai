from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low", "info"]
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
    message: str = Field(..., max_length=2000)
    file_path: str
    line_start: int = Field(..., ge=1)
    line_end: int | None = None
    target_line_content: str = Field(..., max_length=2000)
    target_line_content_reasoning: str = Field(..., max_length=2000)
    suggestion: str | None = Field(None, description="Code block to replace lines with")
    confidence: float = Field(..., ge=0.0, le=1.0)


class ReviewResult(BaseModel):
    findings: list[Finding]
    summary: str = Field(..., max_length=1000)


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
