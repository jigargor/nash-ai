from http import HTTPStatus

from app.errors.envelope import ErrorAction, ErrorFamily


def family_for_status(status_code: int) -> ErrorFamily:
    if status_code in {401, 403}:
        return "auth"
    if status_code in {400, 422}:
        return "validation"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 429:
        return "rate_limit"
    if status_code == 503:
        return "dependency"
    if status_code in {502, 504}:
        return "upstream"
    return "internal"


def action_for_status(status_code: int) -> ErrorAction:
    if status_code == 401:
        return "reauth"
    if status_code in {400, 422}:
        return "fix_input"
    if status_code in {409, 429, 502, 503, 504}:
        return "retry"
    if status_code >= 500:
        return "contact_support"
    return "none"


def retryable_for_status(status_code: int) -> bool:
    return status_code in {409, 429, 502, 503, 504}


def code_for_status(status_code: int) -> str:
    if status_code == 400:
        return "VALIDATION_BAD_REQUEST"
    if status_code == 401:
        return "AUTH_UNAUTHORIZED"
    if status_code == 403:
        return "AUTH_FORBIDDEN"
    if status_code == 404:
        return "NOT_FOUND"
    if status_code == 409:
        return "CONFLICT"
    if status_code == 413:
        return "VALIDATION_BODY_TOO_LARGE"
    if status_code == 422:
        return "VALIDATION_FAILED"
    if status_code == 429:
        return "RATE_LIMITED"
    if status_code == 502:
        return "UPSTREAM_BAD_GATEWAY"
    if status_code == 503:
        return "DEPENDENCY_UNAVAILABLE"
    if status_code == 504:
        return "UPSTREAM_TIMEOUT"
    if status_code >= 500:
        return "INTERNAL_ERROR"
    return f"HTTP_{status_code}"


def safe_status_message(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Request failed"
