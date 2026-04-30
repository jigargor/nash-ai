from typing import Literal

from pydantic import BaseModel, Field

ErrorFamily = Literal[
    "auth",
    "validation",
    "not_found",
    "conflict",
    "rate_limit",
    "dependency",
    "upstream",
    "security",
    "internal",
]

ErrorAction = Literal["retry", "reauth", "fix_input", "contact_support", "none"]


class ErrorPayload(BaseModel):
    code: str = Field(description="Stable machine-readable error code.")
    family: ErrorFamily = Field(description="Broad error category for policy and UI routing.")
    message: str = Field(description="Safe user-facing message.")
    retryable: bool = Field(description="Whether the same action can be retried without input changes.")
    action: ErrorAction = Field(description="Preferred UI/operator action.")
    request_id: str = Field(description="Correlation ID for support, logs, and traces.")
    details: dict[str, object] | None = Field(default=None, description="Sanitized structured details.")


class ErrorEnvelope(BaseModel):
    error: ErrorPayload
    # Compatibility field while existing clients/tests still read FastAPI's legacy `detail`.
    detail: str
