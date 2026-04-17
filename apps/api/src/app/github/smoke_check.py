import asyncio
import os

import httpx

from app.github.auth import create_jwt, get_installation_token


async def resolve_installation_id() -> int:
    value = os.getenv("GITHUB_INSTALLATION_ID")
    if value:
        return int(value)

    headers = {
        "Authorization": f"Bearer {create_jwt()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.github.com/app/installations", headers=headers)
        response.raise_for_status()
        installations = response.json()

    if not installations:
        raise RuntimeError("No GitHub App installations found. Set GITHUB_INSTALLATION_ID explicitly.")

    return int(installations[0]["id"])


async def main() -> None:
    installation_id = await resolve_installation_id()
    token = await get_installation_token(installation_id)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.github.com/installation/repositories", headers=headers)
        response.raise_for_status()
        data = response.json()

    repo_count = len(data.get("repositories", []))
    print(f"Installation {installation_id} token is valid. Accessible repositories: {repo_count}")


if __name__ == "__main__":
    asyncio.run(main())
