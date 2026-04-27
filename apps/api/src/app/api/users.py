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

from app.api.auth import CurrentDashboardUser, get_current_dashboard_user
from app.config import settings
from app.crypto import encrypt_secret
from app.db.models import Installation, InstallationUser, User, UserKeyAuditLog, UserProviderKey
from app.db.session import AsyncSessionLocal, set_user_context

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"anthropic", "openai", "gemini"})


def _verify_api_access(x_api_key: str | None = Header(default=None)) -> None:
    if settings.environment.lower() == "production" and not settings.api_access_key:
        raise HTTPException(  # pragma: no cover
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="API key auth is not configured"
        )
    if not settings.api_access_key:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_access_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Api-Key"
        )


router = APIRouter(prefix="/api/v1/users", dependencies=[Depends(_verify_api_access)])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_user(github_id: int) -> User:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(select(User).where(User.github_id == github_id))
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found — please log out and back in to register your account.",
        )
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
                        raise HTTPException(
                            status_code=422,
                            detail="API key validation failed: invalid Anthropic key",
                        )
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
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=422, detail="API key validation failed: provider did not respond in time"
        )
    except Exception as exc:
        logger.warning("Key validation probe failed for provider %s: %s", provider, exc)
        raise HTTPException(
            status_code=422, detail="API key validation failed: could not reach provider"
        )


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class UpsertUserRequest(BaseModel):
    login: str | None = None


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


class InstallationSyncItem(BaseModel):
    installation_id: int
    account_login: str
    account_type: str


class SyncInstallationsRequest(BaseModel):
    installations: list[InstallationSyncItem]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/me", response_model=UserResponse)
async def upsert_current_user(
    body: UpsertUserRequest,
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> UserResponse:
    """Upsert a user record on login. Called from the BFF after GitHub OAuth succeeds."""
    login = body.login or current_user.login
    if not login:
        raise HTTPException(status_code=422, detail="login is required")
    stmt = (
        pg_insert(User)
        .values(
            github_id=current_user.github_id,
            login=login,
            updated_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_update(
            index_elements=["github_id"],
            set_={
                "login": login,
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


@router.post("/me/installations-sync")
async def sync_current_user_installations(
    body: SyncInstallationsRequest,
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> dict[str, int]:
    installation_ids = sorted(
        {
            item.installation_id
            for item in body.installations
            if item.installation_id > 0 and item.account_login.strip()
        }
    )

    async with AsyncSessionLocal() as session:
        await set_user_context(session, current_user.github_id)
        user = (
            await session.execute(select(User).where(User.github_id == current_user.github_id))
        ).scalar_one_or_none()
        if user is None or user.deleted_at is not None:
            raise HTTPException(
                status_code=404,
                detail="Account not found — please log out and back in to register your account.",
            )

        if installation_ids:
            existing_installations = {
                int(installation.installation_id): installation
                for installation in (
                    (
                        await session.execute(
                            select(Installation).where(Installation.installation_id.in_(installation_ids))
                        )
                    )
                    .scalars()
                    .all()
                )
            }
            for item in body.installations:
                if item.installation_id <= 0 or not item.account_login.strip():
                    continue
                installation = existing_installations.get(item.installation_id)
                if installation is None:
                    installation = Installation(
                        installation_id=item.installation_id,
                        account_login=item.account_login.strip(),
                        account_type=item.account_type.strip() or "Unknown",
                    )
                    session.add(installation)
                    existing_installations[item.installation_id] = installation
                else:
                    installation.account_login = item.account_login.strip()
                    installation.account_type = item.account_type.strip() or "Unknown"

        existing_rows = (
            (
                await session.execute(
                    select(InstallationUser).where(InstallationUser.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        existing_ids = {int(row.installation_id) for row in existing_rows}
        target_ids = set(installation_ids)

        for row in existing_rows:
            if int(row.installation_id) not in target_ids:
                await session.delete(row)

        for installation_id in sorted(target_ids - existing_ids):
            session.add(InstallationUser(installation_id=installation_id, user_id=user.id, role="member"))

        await session.commit()

    return {"linked_installations": len(installation_ids)}


@router.delete("/me")
async def delete_current_user(
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> dict[str, str]:
    """GDPR erasure: soft-delete the user. Cascade removes all provider keys via DB FK."""
    async with AsyncSessionLocal() as session:
        await set_user_context(session, current_user.github_id)
        row = (
            await session.execute(select(User).where(User.github_id == current_user.github_id))
        ).scalar_one_or_none()
        if row is None or row.deleted_at is not None:
            raise HTTPException(status_code=404, detail="User not found")
        row.deleted_at = datetime.now(timezone.utc)
        await session.commit()
    return {"detail": "User marked for deletion"}


def _empty_key_list() -> list[KeyStatusResponse]:
    return [KeyStatusResponse(provider=p, has_key=False) for p in sorted(SUPPORTED_PROVIDERS)]


@router.get("/me/keys", response_model=list[KeyStatusResponse])
async def list_user_keys(
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> list[KeyStatusResponse]:
    """List which providers the user has keys stored for. Never returns key material."""
    async with AsyncSessionLocal() as session:
        await set_user_context(session, current_user.github_id)
        user = (
            await session.execute(select(User).where(User.github_id == current_user.github_id))
        ).scalar_one_or_none()
        # User row may not exist yet if they logged in before the upsert-on-login was deployed.
        # Return empty list rather than 404 — the UI will show all providers as "Not set".
        if user is None or user.deleted_at is not None:
            return _empty_key_list()
        rows = (
            (
                await session.execute(
                    select(UserProviderKey).where(UserProviderKey.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )

    stored = {row.provider: row for row in rows}
    result = []
    for provider in sorted(SUPPORTED_PROVIDERS):
        row = stored.get(provider)
        last_used = row.last_used_at if row is not None else None
        result.append(
            KeyStatusResponse(
                provider=provider,
                has_key=row is not None,
                created_at=row.created_at.isoformat() if row is not None else None,
                updated_at=row.updated_at.isoformat() if row is not None else None,
                last_used_at=last_used.isoformat() if last_used is not None else None,
            )
        )
    return result


@router.put("/me/keys/{provider}")
async def upsert_user_key(
    provider: str,
    body: UpsertKeyRequest,
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
    validate: bool = Query(default=True),
) -> dict[str, str]:
    """Store (or replace) a Fernet-encrypted API key for the given provider."""
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider: {provider}. Must be one of {sorted(SUPPORTED_PROVIDERS)}",
        )
    if validate:
        await _validate_api_key(provider, body.api_key)

    key_enc = encrypt_secret(body.api_key)
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        await set_user_context(session, current_user.github_id)
        user = (
            await session.execute(select(User).where(User.github_id == current_user.github_id))
        ).scalar_one_or_none()
        if user is None or user.deleted_at is not None:
            raise HTTPException(
                status_code=404,
                detail="Account not found — please log out and back in to register your account.",
            )

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
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> dict[str, str]:
    """Delete a stored provider key and write an audit log entry."""
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")
    async with AsyncSessionLocal() as session:
        await set_user_context(session, current_user.github_id)
        user = (
            await session.execute(select(User).where(User.github_id == current_user.github_id))
        ).scalar_one_or_none()
        if user is None or user.deleted_at is not None:
            raise HTTPException(
                status_code=404,
                detail="Account not found — please log out and back in to register your account.",
            )

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
