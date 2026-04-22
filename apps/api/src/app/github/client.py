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
        return await self.get_json(f"/repos/{owner}/{repo}/pulls/{pr_number}")

    async def get_pull_request_commits(self, owner: str, repo: str, pr_number: int) -> list[dict]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}/commits",
                headers=self._headers,
                params={"per_page": 100},
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    async def get_pull_request_diff(self, owner: str, repo: str, pr_number: int) -> str:
        headers = {**self._headers, "Accept": "application/vnd.github.v3.diff"}
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}", headers=headers)
            r.raise_for_status()
            return r.text

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        data = await self.get_json(f"/repos/{owner}/{repo}/contents/{path}", params={"ref": ref})
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    async def search_code(self, owner: str, repo: str, pattern: str, path_glob: str | None = None) -> list[dict]:
        query = f"{pattern} repo:{owner}/{repo}"
        if path_glob:
            query = f"{query} path:{path_glob}"
        payload = await self.get_json("/search/code", params={"q": query, "per_page": 20})
        return payload.get("items", [])

    async def get_file_history(self, owner: str, repo: str, path: str) -> list[dict]:
        return await self.get_json(f"/repos/{owner}/{repo}/commits", params={"path": path, "per_page": 10})

    async def get_pr_reviews_by_bot(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        bot_login: str | None = None,
    ) -> list[dict]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}/comments",
                headers=self._headers,
                params={"per_page": 100},
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            return []
        bot_comments: list[dict] = []
        normalized_login = bot_login.strip().lower() if isinstance(bot_login, str) and bot_login.strip() else None
        for comment in payload:
            if not isinstance(comment, dict):
                continue
            user = comment.get("user")
            if not isinstance(user, dict):
                continue
            login = user.get("login")
            user_type = str(user.get("type", "")).lower()
            if normalized_login:
                if isinstance(login, str) and login.lower() == normalized_login:
                    bot_comments.append(comment)
                continue
            if user_type == "bot":
                bot_comments.append(comment)
        return bot_comments

    async def get_json(self, path: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BASE}{path}", headers=self._headers, params=params)
            r.raise_for_status()
            return r.json()

    async def post_json(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{BASE}{path}", headers=self._headers, json=payload)
            r.raise_for_status()
            return r.json()
