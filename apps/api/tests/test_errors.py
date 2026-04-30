from collections.abc import AsyncIterator, Awaitable, Callable

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.errors.exceptions import AppError
from app.errors.handlers import register_error_handlers, request_id_middleware


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    register_error_handlers(app)

    @app.middleware("http")
    async def _request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        return await request_id_middleware(request, call_next)

    @app.get("/http-error")
    async def http_error() -> None:
        raise HTTPException(status_code=409, detail="Already running")

    @app.get("/app-error")
    async def app_error() -> None:
        raise AppError(
            code="DEPENDENCY_REDIS_UNAVAILABLE",
            message="Redis unavailable",
            status_code=503,
            family="dependency",
            retryable=True,
            action="retry",
            details={"dependency": "redis"},
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


@pytest.mark.anyio
async def test_http_exception_returns_compatible_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/http-error", headers={"X-Request-ID": "req-test-1"})

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "Already running"
    assert body["error"]["code"] == "CONFLICT"
    assert body["error"]["action"] == "retry"
    assert body["error"]["request_id"] == "req-test-1"
    assert response.headers["X-Request-ID"] == "req-test-1"


@pytest.mark.anyio
async def test_app_error_returns_policy_fields(client: httpx.AsyncClient) -> None:
    response = await client.get("/app-error")

    assert response.status_code == 503
    body = response.json()
    assert body["detail"] == "Redis unavailable"
    assert body["error"]["code"] == "DEPENDENCY_REDIS_UNAVAILABLE"
    assert body["error"]["family"] == "dependency"
    assert body["error"]["retryable"] is True
    assert body["error"]["details"] == {"dependency": "redis"}
