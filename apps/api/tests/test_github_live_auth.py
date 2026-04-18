import os

import httpx
import pytest

from app.github.auth import create_jwt, get_installation_token
from app.github.smoke_check import resolve_installation_id


pytestmark = pytest.mark.live_github


def _is_live_test_enabled() -> bool:
    return os.getenv("RUN_LIVE_GITHUB_TESTS", "").lower() in {"1", "true", "yes"}


@pytest.mark.skipif(not _is_live_test_enabled(), reason="Set RUN_LIVE_GITHUB_TESTS=1 to run live GitHub API auth test.")
@pytest.mark.anyio
async def test_installation_token_live_round_trip() -> None:
    app_jwt = create_jwt()
    app_headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient() as client:
        app_response = await client.get("https://api.github.com/app", headers=app_headers)
        app_response.raise_for_status()

    installation_id = await resolve_installation_id()
    installation_token = await get_installation_token(installation_id)

    install_headers = {
        "Authorization": f"Bearer {installation_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient() as client:
        repos_response = await client.get("https://api.github.com/installation/repositories", headers=install_headers)
        repos_response.raise_for_status()
        payload = repos_response.json()

    assert "repositories" in payload
