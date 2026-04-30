import logging
from collections.abc import Awaitable, Callable
from typing import cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.errors.codes import (
    action_for_status,
    code_for_status,
    family_for_status,
    retryable_for_status,
    safe_status_message,
)
from app.errors.envelope import ErrorAction, ErrorEnvelope, ErrorFamily, ErrorPayload
from app.errors.exceptions import AppError

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


def request_id_from_request(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    incoming = request.headers.get(REQUEST_ID_HEADER)
    if incoming and 8 <= len(incoming) <= 128:
        return incoming
    return uuid4().hex


async def request_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request_id_from_request(request)
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "Unhandled request exception request_id=%s method=%s path=%s",
            request_id,
            request.method,
            request.url.path,
        )
        raise
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


def build_error_envelope(
    *,
    request_id: str,
    code: str,
    family: str,
    message: str,
    retryable: bool,
    action: str,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    envelope = ErrorEnvelope(
        error=ErrorPayload(
            code=code,
            family=cast(ErrorFamily, family),
            message=message,
            retryable=retryable,
            action=cast(ErrorAction, action),
            request_id=request_id,
            details=details,
        ),
        detail=message,
    )
    return envelope.model_dump(mode="json", exclude_none=True)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = request_id_from_request(request)
    payload = build_error_envelope(
        request_id=request_id,
        code=exc.code,
        family=exc.family,
        message=exc.message,
        retryable=exc.retryable,
        action=exc.action,
        details=exc.details,
    )
    headers = {REQUEST_ID_HEADER: request_id, **(exc.headers or {})}
    return JSONResponse(payload, status_code=exc.status_code, headers=headers)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = request_id_from_request(request)
    message = exc.detail if isinstance(exc.detail, str) else safe_status_message(exc.status_code)
    payload = build_error_envelope(
        request_id=request_id,
        code=code_for_status(exc.status_code),
        family=family_for_status(exc.status_code),
        message=message,
        retryable=retryable_for_status(exc.status_code),
        action=action_for_status(exc.status_code),
        details=exc.detail if isinstance(exc.detail, dict) else None,
    )
    headers = {REQUEST_ID_HEADER: request_id, **(exc.headers or {})}
    return JSONResponse(payload, status_code=exc.status_code, headers=headers)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id = request_id_from_request(request)
    payload = build_error_envelope(
        request_id=request_id,
        code="VALIDATION_REQUEST",
        family="validation",
        message="Request validation failed.",
        retryable=False,
        action="fix_input",
        details={"errors": exc.errors()},
    )
    return JSONResponse(payload, status_code=422, headers={REQUEST_ID_HEADER: request_id})


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = request_id_from_request(request)
    logger.exception(
        "Unhandled API error request_id=%s method=%s path=%s",
        request_id,
        request.method,
        request.url.path,
        exc_info=exc,
    )
    payload = build_error_envelope(
        request_id=request_id,
        code="INTERNAL_ERROR",
        family="internal",
        message="Internal server error.",
        retryable=False,
        action="contact_support",
    )
    return JSONResponse(payload, status_code=500, headers={REQUEST_ID_HEADER: request_id})


def register_error_handlers(app: FastAPI) -> None:
    async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return await app_error_handler(request, cast(AppError, exc))

    async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return await http_exception_handler(request, cast(HTTPException, exc))

    async def _validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return await validation_exception_handler(request, cast(RequestValidationError, exc))

    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
