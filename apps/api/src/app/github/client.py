import base64
import httpx
from app.github.auth import get_installation_token

BASE = "https://api.github.com"


class GitHubClient:
    def __init__(self, token: str):
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @classmethod
    async def for_installation(cls, installation_id: int) -> "GitHubClient":
        token = await get_installation_token(installation_id)
        return cls(token)

    async def get_pull_request(self, owner: str, repo: str, pr_number: int) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}", headers=self._headers)
            r.raise_for_status()
            return r.json()

    async def get_pull_request_diff(self, owner: str, repo: str, pr_number: int) -> str:
        headers = {**self._headers, "Accept": "application/vnd.github.v3.diff"}
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}", headers=headers)
            r.raise_for_status()
            return r.text

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BASE}/repos/{owner}/{repo}/contents/{path}", headers=self._headers, params={"ref": ref})
            r.raise_for_status()
            data = r.json()
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
