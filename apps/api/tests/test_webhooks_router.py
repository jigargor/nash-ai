import hashlib
import hmac
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from app.config import settings
from app.errors.handlers import register_error_handlers
from app.webhooks import router as webhook_router


class _FakeRedis:
    def __init__(self) -> None:
        self.keys: set[str] = set()

    async def set(
        self,
        key: str,
        _value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        _ = ex
        if nx and key in self.keys:
            return False
        self.keys.add(key)
        return True


def _payload_bytes(action: str = "opened") -> bytes:
    payload = {
        "action": action,
        "installation": {"id": 42},
        "repository": {
            "full_name": "acme/repo",
            "owner": {"login": "acme", "type": "Organization"},
        },
        "pull_request": {
            "number": 10,
            "head": {"sha": "a" * 40},
        },
    }
    return json.dumps(payload).encode("utf-8")


def _installation_payload_bytes(action: str = "created") -> bytes:
    payload = {
        "action": action,
        "installation": {
            "id": 42,
            "account": {"login": "acme", "type": "Organization"},
        },
    }
    return json.dumps(payload).encode("utf-8")


def _signature(payload: bytes) -> str:
    digest = hmac.new(settings.github_webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
def test_app() -> FastAPI:
    application = FastAPI()
    register_error_handlers(application)
    application.include_router(webhook_router.router, prefix="/webhooks")
    application.state.redis = _FakeRedis()
    return application


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


@pytest.mark.anyio
async def test_github_webhook_get_probe_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/webhooks/github")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "POST" in body["deliveries"]


@pytest.mark.anyio
async def test_github_webhook_pull_request_without_redis_returns_503(
    client: httpx.AsyncClient,
    test_app: FastAPI,
) -> None:
    test_app.state.redis = None
    payload = _payload_bytes(action="opened")
    response = await client.post(
        "/webhooks/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": _signature(payload),
            "X-GitHub-Event": "pull_request",
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Redis unavailable"


@pytest.mark.anyio
async def test_github_webhook_with_valid_signature_and_opened_action_enqueues(
    client: httpx.AsyncClient,
    test_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_queue(_redis: object, _payload: object) -> None:
        calls.append("queued")

    test_app.state.redis = _FakeRedis()
    monkeypatch.setattr(webhook_router, "queue_pull_request_review", fake_queue)

    payload = _payload_bytes(action="opened")
    response = await client.post(
        "/webhooks/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": _signature(payload),
            "X-GitHub-Event": "pull_request",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls == ["queued"]


@pytest.mark.anyio
async def test_github_webhook_with_valid_signature_and_synchronize_action_enqueues(
    client: httpx.AsyncClient,
    test_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_queue(_redis: object, _payload: object) -> None:
        calls.append("queued")

    test_app.state.redis = _FakeRedis()
    monkeypatch.setattr(webhook_router, "queue_pull_request_review", fake_queue)

    payload = _payload_bytes(action="synchronize")
    response = await client.post(
        "/webhooks/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": _signature(payload),
            "X-GitHub-Event": "pull_request",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls == ["queued"]


@pytest.mark.anyio
async def test_github_webhook_with_valid_signature_and_reopened_action_enqueues(
    client: httpx.AsyncClient,
    test_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_queue(_redis: object, _payload: object) -> None:
        calls.append("queued")

    test_app.state.redis = object()
    monkeypatch.setattr(webhook_router, "queue_pull_request_review", fake_queue)

    payload = _payload_bytes(action="reopened")
    response = await client.post(
        "/webhooks/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": _signature(payload),
            "X-GitHub-Event": "pull_request",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls == ["queued"]


@pytest.mark.anyio
async def test_github_webhook_with_installation_event_syncs(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_sync(_payload: object) -> None:
        calls.append("synced")

    monkeypatch.setattr(webhook_router, "sync_installation_from_webhook", fake_sync)

    payload = _installation_payload_bytes(action="created")
    response = await client.post(
        "/webhooks/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": _signature(payload),
            "X-GitHub-Event": "installation",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls == ["synced"]


@pytest.mark.anyio
async def test_github_webhook_skips_duplicate_installation_delivery(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_sync(_payload: object) -> None:
        calls.append("synced")

    monkeypatch.setattr(webhook_router, "sync_installation_from_webhook", fake_sync)

    payload = _installation_payload_bytes(action="created")
    headers = {
        "X-Hub-Signature-256": _signature(payload),
        "X-GitHub-Event": "installation",
        "X-GitHub-Delivery": "delivery-123",
    }
    first = await client.post("/webhooks/github", content=payload, headers=headers)
    second = await client.post("/webhooks/github", content=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == ["synced"]


@pytest.mark.anyio
async def test_github_webhook_with_ignored_action_returns_ok_without_enqueue(
    client: httpx.AsyncClient,
    test_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_queue(_redis: object, _payload: object) -> None:
        calls.append("queued")

    test_app.state.redis = object()
    monkeypatch.setattr(webhook_router, "queue_pull_request_review", fake_queue)

    # "closed" enqueues outcome classification; use an unhandled action for the no-op path.
    payload = _payload_bytes(action="edited")
    response = await client.post(
        "/webhooks/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": _signature(payload),
            "X-GitHub-Event": "pull_request",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls == []


@pytest.mark.anyio
async def test_github_webhook_with_invalid_signature_returns_401(client: httpx.AsyncClient) -> None:
    payload = _payload_bytes(action="opened")
    response = await client.post(
        "/webhooks/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Event": "pull_request",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid signature"


@pytest.mark.anyio
async def test_github_webhook_with_malformed_payload_returns_400(client: httpx.AsyncClient) -> None:
    payload = b'{"action":"opened","installation":{"id":42}}'
    response = await client.post(
        "/webhooks/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": _signature(payload),
            "X-GitHub-Event": "pull_request",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid payload"


@pytest.mark.anyio
async def test_github_webhook_skips_duplicate_pull_request_delivery(
    client: httpx.AsyncClient,
    test_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_queue(_redis: object, _payload: object) -> None:
        calls.append("queued")

    test_app.state.redis = _FakeRedis()
    monkeypatch.setattr(webhook_router, "queue_pull_request_review", fake_queue)

    payload = _payload_bytes(action="opened")
    headers = {
        "X-Hub-Signature-256": _signature(payload),
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": "delivery-pr-1",
    }
    first = await client.post("/webhooks/github", content=payload, headers=headers)
    second = await client.post("/webhooks/github", content=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == ["queued"]


@pytest.mark.anyio
async def test_github_webhook_closed_action_enqueues_outcome_classification(
    client: httpx.AsyncClient,
    test_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_queue_outcomes(_redis: object, _payload: object) -> None:
        calls.append("classified")

    async def fake_queue_review(_redis: object, _payload: object) -> None:
        raise AssertionError("closed action should not queue review job")

    test_app.state.redis = object()
    monkeypatch.setattr(
        webhook_router,
        "queue_pull_request_outcome_classification",
        fake_queue_outcomes,
    )
    monkeypatch.setattr(webhook_router, "queue_pull_request_review", fake_queue_review)

    payload = _payload_bytes(action="closed")
    response = await client.post(
        "/webhooks/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": _signature(payload),
            "X-GitHub-Event": "pull_request",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls == ["classified"]
