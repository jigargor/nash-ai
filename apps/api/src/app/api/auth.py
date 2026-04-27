from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException, status
from jwt import InvalidTokenError

from app.config import settings


@dataclass(frozen=True)
class CurrentDashboardUser:
    github_id: int
    login: str | None


def _dashboard_jwt_secret() -> str:
    secret = (settings.dashboard_user_jwt_secret or "").strip()
    if secret:
        return secret
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Dashboard user token auth is not configured",
    )


def get_current_dashboard_user(
    x_dashboard_user_token: str | None = Header(default=None),
) -> CurrentDashboardUser:
    if not x_dashboard_user_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Dashboard-User-Token",
        )

    try:
        payload = jwt.decode(
            x_dashboard_user_token,
            _dashboard_jwt_secret(),
            algorithms=["HS256"],
            audience=settings.dashboard_user_jwt_audience,
            issuer=settings.dashboard_user_jwt_issuer,
            options={"require": ["sub", "exp", "aud", "iss"]},
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired dashboard user token",
        ) from None

    github_id_raw = payload.get("sub")
    if not isinstance(github_id_raw, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid dashboard user token subject",
        )
    try:
        github_id = int(github_id_raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid dashboard user token subject",
        ) from None
    if github_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid dashboard user token subject",
        )

    login = payload.get("login")
    return CurrentDashboardUser(github_id=github_id, login=login if isinstance(login, str) else None)
