from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low", "info"]
Category = Literal["security", "performance", "correctness", "style", "maintainability"]


class Finding(BaseModel):
    severity: Severity
    category: Category
    message: str = Field(..., max_length=2000)
    file_path: str
    line_start: int = Field(..., ge=1)
    line_end: int | None = None
    suggestion: str | None = Field(None, description="Code block to replace lines with")
    confidence: float = Field(..., ge=0.0, le=1.0)


class ReviewResult(BaseModel):
    findings: list[Finding]
    summary: str = Field(..., max_length=1000)
