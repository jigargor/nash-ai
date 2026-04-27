"""Tests for the /api/v1/users endpoints (users.py)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api import users as users_module
from app.config import settings
from app.db.models import User, UserProviderKey
from app.db.session import AsyncSessionLocal, engine

from conftest import _auth_headers  # shared across api test files


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _rand_github_id() -> int:
    return int(str(uuid4().int)[:9])


@pytest.fixture(autouse=True)
async def reset_db_pool() -> None:
    """Dispose the engine pool before each test so asyncpg doesn't reuse connections
    bound to a previous test's event loop (Windows asyncio / ProactorEventLoop quirk)."""
    await engine.dispose()


@pytest.fixture
def test_app() -> FastAPI:
    application = FastAPI()
    application.include_router(users_module.router)
    return application


@pytest.fixture
async def client(test_app: FastAPI) -> httpx.AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _seed_user(github_id: int, login: str = "testuser") -> int:
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        stmt = (
            pg_insert(User)
            .values(github_id=github_id, login=login, updated_at=datetime.now(timezone.utc))
            .on_conflict_do_update(
                index_elements=["github_id"],
                set_={"login": login, "updated_at": datetime.now(timezone.utc)},
            )
            .returning(User.id)
        )
        user_id = (await session.execute(stmt)).scalar_one()
        await session.commit()
    return int(user_id)


# ---------------------------------------------------------------------------
# _verify_api_access
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_verify_api_access_production_no_key_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "api_access_key", None)
    with pytest.raises(users_module.HTTPException) as exc_info:
        users_module._verify_api_access(None)
    assert exc_info.value.status_code == 503


@pytest.mark.anyio
async def test_verify_api_access_wrong_key_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_access_key", "correct-key")
    with pytest.raises(users_module.HTTPException) as exc_info:
        users_module._verify_api_access("wrong-key")
    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_verify_api_access_no_key_configured_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_access_key", None)
    users_module._verify_api_access(None)  # should not raise


# ---------------------------------------------------------------------------
# _validate_api_key
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_validate_api_key_anthropic_invalid_key_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 401

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.users.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(users_module.HTTPException) as exc_info:
            await users_module._validate_api_key("anthropic", "sk-bad-key-that-is-long")
    assert exc_info.value.status_code == 422
    assert "Anthropic" in exc_info.value.detail


@pytest.mark.anyio
async def test_validate_api_key_anthropic_valid_key_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.users.httpx.AsyncClient", return_value=mock_client):
        await users_module._validate_api_key("anthropic", "sk-valid-key-that-is-long")


@pytest.mark.anyio
async def test_validate_api_key_openai_invalid_key_raises() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 401

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.users.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(users_module.HTTPException) as exc_info:
            await users_module._validate_api_key("openai", "sk-bad-openai-key-that-is-long")
    assert exc_info.value.status_code == 422
    assert "openai" in exc_info.value.detail


@pytest.mark.anyio
async def test_validate_api_key_gemini_valid_passes() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.users.httpx.AsyncClient", return_value=mock_client):
        await users_module._validate_api_key("gemini", "gemini-api-key-that-is-long")


@pytest.mark.anyio
async def test_validate_api_key_timeout_raises() -> None:
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.users.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(users_module.HTTPException) as exc_info:
            await users_module._validate_api_key("anthropic", "sk-key-that-is-long-enough")
    assert exc_info.value.status_code == 422
    assert "time" in exc_info.value.detail.lower()


@pytest.mark.anyio
async def test_validate_api_key_network_error_raises() -> None:
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.users.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(users_module.HTTPException) as exc_info:
            await users_module._validate_api_key("anthropic", "sk-key-that-is-long-enough")
    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# upsert_current_user
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_upsert_current_user_creates_new_user(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    github_id = _rand_github_id()

    resp = await client.post(
        "/api/v1/users/me",
        json={"github_id": github_id, "login": "newuser"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["github_id"] == github_id
    assert body["login"] == "newuser"


@pytest.mark.anyio
async def test_upsert_current_user_updates_existing_user(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    github_id = _rand_github_id()
    await _seed_user(github_id, login="old-login")

    resp = await client.post(
        "/api/v1/users/me",
        json={"github_id": github_id, "login": "new-login"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["login"] == "new-login"


# ---------------------------------------------------------------------------
# delete_current_user
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_current_user_missing_header_returns_400(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    resp = await client.delete("/api/v1/users/me", headers=_auth_headers())
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_delete_current_user_not_found_returns_404(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    resp = await client.delete(
        "/api/v1/users/me",
        headers={**_auth_headers(), "X-User-Github-Id": "9999999"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_delete_current_user_soft_deletes(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    github_id = _rand_github_id()
    await _seed_user(github_id)

    resp = await client.delete(
        "/api/v1/users/me",
        headers={**_auth_headers(), "X-User-Github-Id": str(github_id)},
    )
    assert resp.status_code == 200

    # Verify soft-deleted — a second delete should 404
    resp2 = await client.delete(
        "/api/v1/users/me",
        headers={**_auth_headers(), "X-User-Github-Id": str(github_id)},
    )
    assert resp2.status_code == 404


# ---------------------------------------------------------------------------
# list_user_keys
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_user_keys_missing_header_returns_400(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    resp = await client.get("/api/v1/users/me/keys", headers=_auth_headers())
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_list_user_keys_unknown_user_returns_empty_list(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    resp = await client.get(
        "/api/v1/users/me/keys",
        headers={**_auth_headers(), "X-User-Github-Id": "8888888"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert all(item["has_key"] is False for item in body)


@pytest.mark.anyio
async def test_list_user_keys_returns_correct_providers(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    github_id = _rand_github_id()
    user_id = await _seed_user(github_id)

    from app.crypto import encrypt_secret
    await engine.dispose()
    async with AsyncSessionLocal() as session:
        session.add(UserProviderKey(
            user_id=user_id,
            provider="anthropic",
            key_enc=encrypt_secret("sk-test-key-that-is-at-least-20-chars"),
        ))
        await session.commit()

    resp = await client.get(
        "/api/v1/users/me/keys",
        headers={**_auth_headers(), "X-User-Github-Id": str(github_id)},
    )
    assert resp.status_code == 200
    body = {item["provider"]: item for item in resp.json()}
    assert body["anthropic"]["has_key"] is True
    assert body["openai"]["has_key"] is False
    assert body["gemini"]["has_key"] is False


# ---------------------------------------------------------------------------
# upsert_user_key
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_upsert_user_key_bad_provider_returns_400(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    resp = await client.put(
        "/api/v1/users/me/keys/cohere",
        json={"api_key": "sk-test-key-long-enough-here"},
        headers={**_auth_headers(), "X-User-Github-Id": "12345"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_upsert_user_key_missing_header_returns_400(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    resp = await client.put(
        "/api/v1/users/me/keys/anthropic?validate=false",
        json={"api_key": "sk-test-key-long-enough-here"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_upsert_user_key_creates_key(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    github_id = _rand_github_id()
    await _seed_user(github_id)

    resp = await client.put(
        "/api/v1/users/me/keys/anthropic?validate=false",
        json={"api_key": "sk-test-key-long-enough-here"},
        headers={**_auth_headers(), "X-User-Github-Id": str(github_id)},
    )
    assert resp.status_code == 200
    assert "created" in resp.json()["detail"]


@pytest.mark.anyio
async def test_upsert_user_key_updates_existing_key(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    github_id = _rand_github_id()
    await _seed_user(github_id)

    headers = {**_auth_headers(), "X-User-Github-Id": str(github_id)}
    # create
    await client.put(
        "/api/v1/users/me/keys/openai?validate=false",
        json={"api_key": "sk-first-key-long-enough-here"},
        headers=headers,
    )
    # update
    resp = await client.put(
        "/api/v1/users/me/keys/openai?validate=false",
        json={"api_key": "sk-second-key-long-enough-here"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert "updated" in resp.json()["detail"]


@pytest.mark.anyio
async def test_upsert_user_key_user_not_found_returns_404(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    resp = await client.put(
        "/api/v1/users/me/keys/anthropic?validate=false",
        json={"api_key": "sk-test-key-long-enough-here"},
        headers={**_auth_headers(), "X-User-Github-Id": "7777777"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_upsert_user_key_short_key_rejected_by_validator(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    github_id = _rand_github_id()
    await _seed_user(github_id)

    resp = await client.put(
        "/api/v1/users/me/keys/anthropic?validate=false",
        json={"api_key": "short"},
        headers={**_auth_headers(), "X-User-Github-Id": str(github_id)},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# delete_user_key
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_user_key_bad_provider_returns_400(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    resp = await client.delete(
        "/api/v1/users/me/keys/unknown",
        headers={**_auth_headers(), "X-User-Github-Id": "12345"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_delete_user_key_missing_header_returns_400(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    resp = await client.delete("/api/v1/users/me/keys/anthropic", headers=_auth_headers())
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_delete_user_key_no_key_stored_returns_404(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    github_id = _rand_github_id()
    await _seed_user(github_id)

    resp = await client.delete(
        "/api/v1/users/me/keys/anthropic",
        headers={**_auth_headers(), "X-User-Github-Id": str(github_id)},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_delete_user_key_success(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    github_id = _rand_github_id()
    await _seed_user(github_id)

    headers = {**_auth_headers(), "X-User-Github-Id": str(github_id)}
    # create key first
    await client.put(
        "/api/v1/users/me/keys/gemini?validate=false",
        json={"api_key": "gemini-api-key-long-enough-here"},
        headers=headers,
    )
    # now delete it
    resp = await client.delete("/api/v1/users/me/keys/gemini", headers=headers)
    assert resp.status_code == 200
    assert "deleted" in resp.json()["detail"]


@pytest.mark.anyio
async def test_delete_user_key_user_not_found_returns_404(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "api_access_key", None)
    resp = await client.delete(
        "/api/v1/users/me/keys/anthropic",
        headers={**_auth_headers(), "X-User-Github-Id": "6666666"},
    )
    assert resp.status_code == 404
