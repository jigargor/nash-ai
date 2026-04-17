import time
from pathlib import Path

import httpx
import jwt

from app.config import settings


def _load_private_key() -> str:
    return Path(settings.github_private_key_path).read_text()


def create_jwt() -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 600,
        "iss": settings.github_app_id,
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
        )
        r.raise_for_status()
        return r.json()["token"]
