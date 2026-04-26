import time
from pathlib import Path

import httpx
import jwt

from app.config import settings


def _load_private_key() -> str:
    path = Path(settings.github_private_key_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"GitHub App private key not found at {path}. "
            "Set GITHUB_PRIVATE_KEY_PATH in apps/api/.env (paths are relative to apps/api)."
        )
    return path.read_text()


def create_jwt() -> str:
    now = int(time.time())
    # PyJWT requires iss to be a str. GitHub accepts the App ID as digits in a string.
    payload = {
        "iat": now - 60,
        "exp": now + 600,
        "iss": str(settings.github_app_id).strip(),
    }
    return jwt.encode(payload, _load_private_key(), algorithm="RS256")


def create_app_jwt() -> str:
    # Backward-compatible alias for older imports.
    return create_jwt()


async def get_installation_token(installation_id: int) -> str:
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
                    f"GITHUB_PRIVATE_KEY_PATH points to the correct .pem ({settings.github_private_key_path})."
                )
            raise RuntimeError(
                f"GitHub installation token request failed ({e.response.status_code}): {body}{hint}"
            ) from e
        return str(r.json()["token"])
