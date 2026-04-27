import asyncio
import hmac
import logging
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.crypto import InvalidToken, decrypt_secret, encrypt_secret
from app.db.models import User, UserKeyAuditLog, UserProviderKey
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"anthropic", "openai", "gemini"})


def _verify_api_access(x_api_key: str | None = Header(default=None)) -> None:
    if settings.environment.lower() == "production" and not settings.api_access_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="API key auth is not configured")
    if not settings.api_access_key:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_access_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Api-Key")


router = APIRouter(prefix="/api/v1/users", dependencies=[Depends(_verify_api_access)])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_user(github_id: int) -> User:
    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(User).where(User.github_id == github_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if row.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return row


async def _validate_api_key(provider: str, api_key: str) -> None:
    """Make a cheap probe call to verify the key is valid. Raises HTTPException on failure."""
    try:
        async with asyncio.timeout(5):
            if provider == "anthropic":
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "https://api.anthropic.com/v1/models",
                        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                    )
                    if resp.status_code == 401:
                        raise HTTPException(status_code=422, detail="API key validation failed: invalid Anthropic key")
            elif provider in {"openai", "gemini"}:
                base_url = (
                    "https://generativelanguage.googleapis.com/v1beta/openai/"
                    if provider == "gemini"
                    else "https://api.openai.com/v1/"
                )
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{base_url}models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    if resp.status_code == 401:
                        raise HTTPException(
                            status_code=422,
                            detail=f"API key validation failed: invalid {provider} key",
                        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Key validation probe failed for provider %s: %s", provider, exc)
        raise HTTPException(status_code=422, detail="API key validation failed: could not reach provider")


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class UpsertUserRequest(BaseModel):
    github_id: int
    login: str


class UserResponse(BaseModel):
    id: int
    github_id: int
    login: str
    created_at: str


class UpsertKeyRequest(BaseModel):
    api_key: str

    @field_validator("api_key")
    @classmethod
    def key_must_not_be_empty(cls, v: str) -> str:
        if len(v.strip()) < 20:
            raise ValueError("api_key must be at least 20 characters")
        return v.strip()


class KeyStatusResponse(BaseModel):
    provider: str
    has_key: bool
    created_at: str | None = None
    updated_at: str | None = None
    last_used_at: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/me", response_model=UserResponse)
async def upsert_current_user(body: UpsertUserRequest) -> UserResponse:
    """Upsert a user record on login. Called from the BFF after GitHub OAuth succeeds."""
    stmt = (
        pg_insert(User)
        .values(
            github_id=body.github_id,
            login=body.login,
            updated_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_update(
            index_elements=["github_id"],
            set_={
                "login": body.login,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        .returning(User)
    )
    async with AsyncSessionLocal() as session:
        row = (await session.execute(stmt)).scalar_one()
        await session.commit()
    return UserResponse(
        id=row.id,
        github_id=row.github_id,
        login=row.login,
        created_at=row.created_at.isoformat(),
    )


@router.delete("/me")
async def delete_current_user(
    x_user_github_id: int | None = Header(default=None),
) -> dict[str, str]:
    """GDPR erasure: soft-delete the user. Cascade removes all provider keys via DB FK."""
    if x_user_github_id is None:
        raise HTTPException(status_code=400, detail="X-User-Github-Id header required")
    user = await _resolve_user(x_user_github_id)
    async with AsyncSessionLocal() as session:
        db_user = await session.get(User, user.id)
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        db_user.deleted_at = datetime.now(timezone.utc)
        await session.commit()
    return {"detail": "User marked for deletion"}


@router.get("/me/keys", response_model=list[KeyStatusResponse])
async def list_user_keys(
    x_user_github_id: int | None = Header(default=None),
) -> list[KeyStatusResponse]:
    """List which providers the user has keys stored for. Never returns key material."""
    if x_user_github_id is None:
        raise HTTPException(status_code=400, detail="X-User-Github-Id header required")
    user = await _resolve_user(x_user_github_id)
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(UserProviderKey).where(UserProviderKey.user_id == user.id)
            )
        ).scalars().all()

    stored = {row.provider: row for row in rows}
    return [
        KeyStatusResponse(
            provider=provider,
            has_key=provider in stored,
            created_at=stored[provider].created_at.isoformat() if provider in stored else None,
            updated_at=stored[provider].updated_at.isoformat() if provider in stored else None,
            last_used_at=stored[provider].last_used_at.isoformat() if provider in stored and stored[provider].last_used_at else None,
        )
        for provider in sorted(SUPPORTED_PROVIDERS)
    ]


@router.put("/me/keys/{provider}")
async def upsert_user_key(
    provider: str,
    body: UpsertKeyRequest,
    x_user_github_id: int | None = Header(default=None),
    validate: bool = Query(default=True),
) -> dict[str, str]:
    """Store (or replace) a Fernet-encrypted API key for the given provider."""
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}. Must be one of {sorted(SUPPORTED_PROVIDERS)}")
    if x_user_github_id is None:
        raise HTTPException(status_code=400, detail="X-User-Github-Id header required")

    user = await _resolve_user(x_user_github_id)

    if validate:
        await _validate_api_key(provider, body.api_key)

    key_enc = encrypt_secret(body.api_key)
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(
                select(UserProviderKey).where(
                    UserProviderKey.user_id == user.id,
                    UserProviderKey.provider == provider,
                )
            )
        ).scalar_one_or_none()

        action: Literal["created", "updated"] = "updated" if existing else "created"

        if existing:
            existing.key_enc = key_enc
            existing.updated_at = now
        else:
            session.add(UserProviderKey(user_id=user.id, provider=provider, key_enc=key_enc))

        session.add(UserKeyAuditLog(user_id=user.id, provider=provider, action=action))
        await session.commit()

    return {"detail": f"Key {action} for provider {provider}"}


@router.delete("/me/keys/{provider}")
async def delete_user_key(
    provider: str,
    x_user_github_id: int | None = Header(default=None),
) -> dict[str, str]:
    """Delete a stored provider key and write an audit log entry."""
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")
    if x_user_github_id is None:
        raise HTTPException(status_code=400, detail="X-User-Github-Id header required")

    user = await _resolve_user(x_user_github_id)

    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(UserProviderKey).where(
                    UserProviderKey.user_id == user.id,
                    UserProviderKey.provider == provider,
                )
            )
        ).scalar_one_or_none()

        if row is None:
            raise HTTPException(status_code=404, detail=f"No key stored for provider {provider}")

        await session.delete(row)
        session.add(UserKeyAuditLog(user_id=user.id, provider=provider, action="deleted"))
        await session.commit()

    return {"detail": f"Key deleted for provider {provider}"}
