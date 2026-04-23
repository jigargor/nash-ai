import base64
from datetime import datetime
from typing import Any, cast

import httpx

from app.github.auth import get_installation_token

BASE = "https://api.github.com"

JsonDict = dict[str, Any]


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

    async def get_pull_request(self, owner: str, repo: str, pr_number: int) -> JsonDict:
        return await self.get_json(f"/repos/{owner}/{repo}/pulls/{pr_number}")

    async def get_pull_request_commits(self, owner: str, repo: str, pr_number: int) -> list[JsonDict]:
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

    async def get_pull_request_files(self, owner: str, repo: str, pr_number: int) -> list[JsonDict]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}/files",
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
        raw = data.get("content")
        if not isinstance(raw, str):
            return ""
        return base64.b64decode(raw).decode("utf-8", errors="replace")

    async def search_code(self, owner: str, repo: str, pattern: str, path_glob: str | None = None) -> list[JsonDict]:
        query = f"{pattern} repo:{owner}/{repo}"
        if path_glob:
            query = f"{query} path:{path_glob}"
        payload = await self.get_json("/search/code", params={"q": query, "per_page": 20})
        items = payload.get("items", [])
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    async def get_file_history(self, owner: str, repo: str, path: str) -> list[JsonDict]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE}/repos/{owner}/{repo}/commits",
                headers=self._headers,
                params={"path": path, "per_page": 10},
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    async def get_commits_touching_file(
        self,
        *,
        owner: str,
        repo: str,
        path: str,
        since: datetime | None = None,
    ) -> list[JsonDict]:
        params: dict[str, str | int] = {"path": path, "per_page": 100}
        if since is not None:
            params["since"] = since.isoformat()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE}/repos/{owner}/{repo}/commits",
                headers=self._headers,
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            return []
        normalized: list[JsonDict] = []
        for commit in payload:
            if not isinstance(commit, dict):
                continue
            commit_obj = commit.get("commit")
            commit_meta = commit_obj if isinstance(commit_obj, dict) else {}
            commit_message = str(commit_meta.get("message", ""))
            normalized.append(
                {
                    "sha": commit.get("sha"),
                    "message": commit_message,
                    "co_authored_by": _extract_co_author(commit_message),
                    "files": await self.get_commit_files(owner, repo, str(commit.get("sha", ""))),
                }
            )
        return normalized

    async def get_commit_files(self, owner: str, repo: str, sha: str) -> list[JsonDict]:
        if not sha:
            return []
        data = await self.get_json(f"/repos/{owner}/{repo}/commits/{sha}")
        files = data.get("files")
        if not isinstance(files, list):
            return []
        return [item for item in files if isinstance(item, dict)]

    async def get_pull_review_comment_reactions(self, owner: str, repo: str, comment_id: int) -> list[JsonDict]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE}/repos/{owner}/{repo}/pulls/comments/{comment_id}/reactions",
                headers=self._headers,
                params={"per_page": 100},
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            return []
        normalized: list[JsonDict] = []
        for reaction in payload:
            if not isinstance(reaction, dict):
                continue
            user_obj = reaction.get("user")
            user = user_obj if isinstance(user_obj, dict) else {}
            normalized.append(
                {
                    "user": user.get("login"),
                    "content": reaction.get("content"),
                    "created_at": reaction.get("created_at"),
                }
            )
        return normalized

    async def get_pull_review_comment_replies(self, owner: str, repo: str, comment_id: int) -> list[JsonDict]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE}/repos/{owner}/{repo}/pulls/comments/{comment_id}/replies",
                headers=self._headers,
                params={"per_page": 100},
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            return []
        normalized: list[JsonDict] = []
        for reply in payload:
            if not isinstance(reply, dict):
                continue
            user_obj = reply.get("user")
            user = user_obj if isinstance(user_obj, dict) else {}
            normalized.append(
                {
                    "user": user.get("login"),
                    "body": reply.get("body"),
                    "created_at": reply.get("created_at"),
                }
            )
        return normalized

    async def is_pull_review_thread_resolved(self, owner: str, repo: str, pr_number: int, comment_id: int) -> bool:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}/threads",
                headers=self._headers,
                params={"per_page": 100},
            )
            if response.status_code >= 400:
                return False
            payload = response.json()
        if not isinstance(payload, list):
            return False
        for thread in payload:
            if not isinstance(thread, dict):
                continue
            comments = thread.get("comments")
            if not isinstance(comments, list):
                continue
            if any(isinstance(comment, dict) and comment.get("id") == comment_id for comment in comments):
                return bool(thread.get("resolved"))
        return False

    async def line_exists_in_pull_request_final_state(
        self,
        *,
        owner: str,
        repo: str,
        pr_state: JsonDict,
        file_path: str,
        line_text: str,
    ) -> bool:
        merge = pr_state.get("merge_commit_sha")
        if isinstance(merge, str) and merge:
            ref: str | None = merge
        else:
            head = pr_state.get("head")
            ref = head.get("sha") if isinstance(head, dict) else None
            ref = ref if isinstance(ref, str) else None
        if not ref:
            return True
        try:
            content = await self.get_file_content(owner, repo, file_path, ref)
        except Exception:
            return True
        return line_text in content

    async def get_pr_reviews_by_bot(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        bot_login: str | None = None,
    ) -> list[JsonDict]:
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
        bot_comments: list[JsonDict] = []
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

    async def get_json(self, path: str, params: dict[str, str | int] | None = None) -> JsonDict:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BASE}{path}", headers=self._headers, params=params)
            r.raise_for_status()
            data = r.json()
        if not isinstance(data, dict):
            return {}
        return cast(JsonDict, data)

    async def post_json(self, path: str, payload: JsonDict) -> JsonDict:
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{BASE}{path}", headers=self._headers, json=payload)
            r.raise_for_status()
            data = r.json()
        if not isinstance(data, dict):
            return {}
        return cast(JsonDict, data)


def _extract_co_author(message: str) -> str | None:
    for line in message.splitlines():
        normalized = line.strip().lower()
        if normalized.startswith("co-authored-by:"):
            return normalized.replace("co-authored-by:", "").strip()
    return None
