import time
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx
import jwt

from app.config import settings


_INSTALLATION_TOKEN_CACHE: dict[int, tuple[str, float]] = {}
_INSTALLATION_TOKEN_LOCKS: dict[int, asyncio.Lock] = {}
_INSTALLATION_TOKEN_REFRESH_SKEW_SECONDS = 60.0
_DEFAULT_INSTALLATION_TOKEN_TTL_SECONDS = 300.0


def _normalized_inline_private_key(raw_value: str) -> str:
    return raw_value.replace("\\n", "\n").strip()


def _load_private_key() -> str:
    if settings.APP_PRIVATE_KEY_PEM:
        return _normalized_inline_private_key(settings.APP_PRIVATE_KEY_PEM)

    path = Path(settings.APP_PRIVATE_KEY_PEM_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"GitHub App private key not found at {path}. "
            "Set APP_PRIVATE_KEY_PEM or APP_PRIVATE_KEY_PEM_PATH in apps/api/.env "
            "(path values are relative to apps/api)."
        )
    return path.read_text()


def _github_app_issuer() -> str:
    return str(settings.github_app_id).strip()


def create_jwt() -> str:
    now = int(time.time())
    # PyJWT requires iss to be a str. GitHub accepts the App ID as digits in a string.
    payload = {
        "iat": now - 60,
        "exp": now + 600,
        "iss": _github_app_issuer(),
    }
    return jwt.encode(payload, _load_private_key(), algorithm="RS256")


def create_app_jwt() -> str:
    # Backward-compatible alias for older imports.
    return create_jwt()


async def get_installation_token(installation_id: int) -> str:
    cached = _INSTALLATION_TOKEN_CACHE.get(installation_id)
    now = time.monotonic()
    if cached is not None:
        token, expires_at = cached
        if expires_at > now:
            return token

    lock = _INSTALLATION_TOKEN_LOCKS.setdefault(installation_id, asyncio.Lock())
    async with lock:
        cached = _INSTALLATION_TOKEN_CACHE.get(installation_id)
        now = time.monotonic()
        if cached is not None:
            token, expires_at = cached
            if expires_at > now:
                return token

        app_jwt = create_jwt()
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={},
            )
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                body = (e.response.text or "")[:800]
                hint = ""
                if e.response.status_code == 401:
                    hint = (
                        " Check GITHUB_APP_ID matches the App that owns this key, and that "
                        f"APP_PRIVATE_KEY_PEM is valid or APP_PRIVATE_KEY_PEM_PATH points to the correct .pem ({settings.APP_PRIVATE_KEY_PEM_path})."
                    )
                raise RuntimeError(
                    f"GitHub installation token request failed ({e.response.status_code}): {body}{hint}"
                ) from e
            payload = r.json()
            token = str(payload["token"])
            expires_at = _expires_at_monotonic(payload.get("expires_at"))
            _INSTALLATION_TOKEN_CACHE[installation_id] = (token, expires_at)
            return token


def _expires_at_monotonic(expires_at_raw: object) -> float:
    if not isinstance(expires_at_raw, str) or not expires_at_raw.strip():
        return time.monotonic() + _DEFAULT_INSTALLATION_TOKEN_TTL_SECONDS
    expires_text = expires_at_raw.strip().replace("Z", "+00:00")
    try:
        expires_dt = datetime.fromisoformat(expires_text)
    except ValueError:
        return time.monotonic() + _DEFAULT_INSTALLATION_TOKEN_TTL_SECONDS
    if expires_dt.tzinfo is None:
        expires_dt = expires_dt.replace(tzinfo=timezone.utc)
    ttl_seconds = max((expires_dt - datetime.now(timezone.utc)).total_seconds(), 0.0)
    ttl_seconds = max(ttl_seconds - _INSTALLATION_TOKEN_REFRESH_SKEW_SECONDS, 0.0)
    return time.monotonic() + ttl_seconds


def _reset_installation_token_cache_for_tests() -> None:
    _INSTALLATION_TOKEN_CACHE.clear()
    _INSTALLATION_TOKEN_LOCKS.clear()
