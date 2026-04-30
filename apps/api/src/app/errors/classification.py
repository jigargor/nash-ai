from typing import Literal

FailureClass = Literal[
    "retryable_transient",
    "retryable_backoff_required",
    "permanent_user_actionable",
    "permanent_operator_actionable",
    "security_fail_closed",
]


def failure_class_for_status(status_code: int) -> FailureClass:
    if status_code in {401, 403}:
        return "security_fail_closed"
    if status_code in {400, 404, 409, 422}:
        return "permanent_user_actionable"
    if status_code == 429:
        return "retryable_backoff_required"
    if status_code in {502, 503, 504}:
        return "retryable_transient"
    return "permanent_operator_actionable"


def failure_class_for_exception(exc: Exception) -> FailureClass:
    message = str(exc).lower()
    if "rate limit" in message or "quota" in message or "too many requests" in message:
        return "retryable_backoff_required"
    if "timeout" in message or "temporarily unavailable" in message:
        return "retryable_transient"
    if "signature" in message or "unauthorized" in message or "forbidden" in message:
        return "security_fail_closed"
    if "invalid" in message or "not found" in message:
        return "permanent_user_actionable"
    return "permanent_operator_actionable"
