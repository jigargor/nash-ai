import asyncio
import base64
import logging
import secrets
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, cast

import httpx

from app.github.auth import get_installation_token

BASE = "https://api.github.com"
logger = logging.getLogger(__name__)

JsonDict = dict[str, Any]

_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=2.0)
_LIMITS = httpx.Limits(max_connections=30, max_keepalive_connections=15, keepalive_expiry=30.0)
_RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_MAX_PAGINATION_PAGES = 100
MAX_REVIEW_FILE_BYTES = 500_000  # 500 KB — files larger than this are skipped


def _parse_next_link(link_header: str) -> str | None:
    """Extract the URL for rel="next" from a GitHub Link header."""
    for part in link_header.split(","):
        segments = part.strip().split(";")
        if len(segments) < 2:
            continue
        url_part = segments[0].strip().lstrip("<").rstrip(">")
        if any('rel="next"' in seg for seg in segments[1:]):
            return url_part
    return None


async def _request_with_retry(
    method: str,
    url: str,
    headers: dict[str, str],
    *,
    client: httpx.AsyncClient | None = None,
    params: dict[str, Any] | None = None,
    json: JsonDict | None = None,
) -> httpx.Response:
    """Make an HTTP request with exponential backoff on retryable status codes.

    GitHub secondary rate limits return 403 with Retry-After; primary rate
    limits return 429.  Transient 5xx also deserve a retry.
    """
    if client is None:
        async with httpx.AsyncClient(timeout=_TIMEOUT, limits=_LIMITS) as ephemeral_client:
            return await _request_with_retry(
                method,
                url,
                headers,
                client=ephemeral_client,
                params=params,
                json=json,
            )
    for attempt in range(_MAX_RETRIES + 1):
        response = await client.request(method, url, headers=headers, params=params, json=json)
        if response.status_code == 403 and "Retry-After" not in response.headers:
            response.raise_for_status()
        if response.status_code not in _RETRYABLE_STATUS:
            response.raise_for_status()
            return response
        if attempt == _MAX_RETRIES:
            response.raise_for_status()
        retry_after = _parse_retry_after_seconds(response.headers.get("Retry-After", ""))
        # Use secrets for jitter to avoid weak RNG usage in retry backoff paths.
        jitter = secrets.randbelow(1_000_000) / 1_000_000
        delay = retry_after if retry_after > 0 else (2**attempt + jitter)
        await asyncio.sleep(min(delay, 60))
    raise RuntimeError("unreachable")  # pragma: no cover


def _parse_retry_after_seconds(retry_after_raw: str) -> float:
    try:
        return float(int(retry_after_raw))
    except ValueError:
        pass
    if not retry_after_raw:
        return 0.0
    try:
        retry_after_dt = parsedate_to_datetime(retry_after_raw)
    except (TypeError, ValueError, IndexError):
        return 0.0
    if retry_after_dt.tzinfo is None:
        retry_after_dt = retry_after_dt.replace(tzinfo=timezone.utc)
    return max((retry_after_dt - datetime.now(timezone.utc)).total_seconds(), 0.0)


class GitHubClient:
    def __init__(self, token: str, *, client: httpx.AsyncClient | None = None):
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        # Reuse one HTTP client per GitHubClient instance to amortize TCP/TLS setup.
        self._client = client or httpx.AsyncClient(timeout=_TIMEOUT, limits=_LIMITS)
        self._owns_client = client is None

    @classmethod
    async def for_installation(cls, installation_id: int) -> "GitHubClient":
        token = await get_installation_token(installation_id)
        return cls(token)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Pagination helper
    # ------------------------------------------------------------------

    async def _get_paginated(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> list[JsonDict]:
        """Collect all pages for a list endpoint, following Link rel="next"."""
        results: list[JsonDict] = []
        visited_urls: set[str] = set()
        next_url: str | None = f"{BASE}{path}"
        next_params: dict[str, Any] | None = {"per_page": 100, **(params or {})}
        page_count = 0
        while next_url and page_count < _MAX_PAGINATION_PAGES:
            if next_url in visited_urls:
                logger.warning("Stopping pagination due to repeated next URL path=%s url=%s", path, next_url)
                break
            visited_urls.add(next_url)
            page_count += 1
            response = await _request_with_retry(
                "GET",
                next_url,
                self._headers,
                client=self._client,
                params=next_params,
            )
            payload = response.json()
            if not isinstance(payload, list):
                logger.warning(
                    "Stopping pagination due to non-list payload path=%s page=%s payload_type=%s",
                    path,
                    page_count,
                    type(payload).__name__,
                )
                break
            results.extend(item for item in payload if isinstance(item, dict))
            next_url = _parse_next_link(response.headers.get("Link", ""))
            next_params = None  # subsequent pages use the full URL from the Link header
        if next_url and page_count >= _MAX_PAGINATION_PAGES:
            logger.warning(
                "Stopping pagination after max pages path=%s max_pages=%s",
                path,
                _MAX_PAGINATION_PAGES,
            )
        return results

    # ------------------------------------------------------------------
    # Pull request endpoints
    # ------------------------------------------------------------------

    async def get_pull_request(self, owner: str, repo: str, pr_number: int) -> JsonDict:
        return await self.get_json(f"/repos/{owner}/{repo}/pulls/{pr_number}")

    async def get_pull_request_commits(
        self, owner: str, repo: str, pr_number: int
    ) -> list[JsonDict]:
        return await self._get_paginated(f"/repos/{owner}/{repo}/pulls/{pr_number}/commits")

    async def get_pull_request_files(self, owner: str, repo: str, pr_number: int) -> list[JsonDict]:
        return await self._get_paginated(f"/repos/{owner}/{repo}/pulls/{pr_number}/files")

    async def get_pull_request_diff(self, owner: str, repo: str, pr_number: int) -> str:
        headers = {**self._headers, "Accept": "application/vnd.github.v3.diff"}
        response = await _request_with_retry(
            "GET",
            f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=headers,
            client=self._client,
        )
        return response.text

    # ------------------------------------------------------------------
    # File content
    # ------------------------------------------------------------------

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        data = await self.get_json(f"/repos/{owner}/{repo}/contents/{path}", params={"ref": ref})
        size = data.get("size", 0)
        if isinstance(size, int) and size > MAX_REVIEW_FILE_BYTES:
            return (
                f"[File skipped: {size:,} bytes exceeds the "
                f"{MAX_REVIEW_FILE_BYTES:,}-byte review limit]"
            )
        raw = data.get("content")
        if not isinstance(raw, str):
            return ""
        return base64.b64decode(raw).decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    # Search / history
    # ------------------------------------------------------------------

    async def search_code(
        self, owner: str, repo: str, pattern: str, path_glob: str | None = None
    ) -> list[JsonDict]:
        query = f"{pattern} repo:{owner}/{repo}"
        if path_glob:
            query = f"{query} path:{path_glob}"
        payload = await self.get_json("/search/code", params={"q": query, "per_page": 20})
        items = payload.get("items", [])
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    async def get_file_history(self, owner: str, repo: str, path: str) -> list[JsonDict]:
        response = await _request_with_retry(
            "GET",
            f"{BASE}/repos/{owner}/{repo}/commits",
            self._headers,
            client=self._client,
            params={"path": path, "per_page": 10},
        )
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
        response = await _request_with_retry(
            "GET",
            f"{BASE}/repos/{owner}/{repo}/commits",
            self._headers,
            client=self._client,
            params=params,
        )
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

    # ------------------------------------------------------------------
    # Review comments and reactions
    # ------------------------------------------------------------------

    async def get_pull_review_comment_reactions(
        self, owner: str, repo: str, comment_id: int
    ) -> list[JsonDict]:
        items = await self._get_paginated(
            f"/repos/{owner}/{repo}/pulls/comments/{comment_id}/reactions"
        )
        normalized: list[JsonDict] = []
        for reaction in items:
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

    async def get_pull_review_comment_replies(
        self, owner: str, repo: str, comment_id: int
    ) -> list[JsonDict]:
        items = await self._get_paginated(
            f"/repos/{owner}/{repo}/pulls/comments/{comment_id}/replies"
        )
        normalized: list[JsonDict] = []
        for reply in items:
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

    async def is_pull_review_thread_resolved(
        self, owner: str, repo: str, pr_number: int, comment_id: int
    ) -> bool:
        try:
            response = await _request_with_retry(
                "GET",
                f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}/threads",
                self._headers,
                client=self._client,
                params={"per_page": 100},
            )
        except httpx.HTTPStatusError:
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
            if any(
                isinstance(comment, dict) and comment.get("id") == comment_id
                for comment in comments
            ):
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
        items = await self._get_paginated(f"/repos/{owner}/{repo}/pulls/{pr_number}/comments")
        bot_comments: list[JsonDict] = []
        normalized_login = (
            bot_login.strip().lower() if isinstance(bot_login, str) and bot_login.strip() else None
        )
        for comment in items:
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

    async def post_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> JsonDict:
        return await self.post_json(
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            {"body": body},
        )

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    async def get_json(self, path: str, params: dict[str, str | int] | None = None) -> JsonDict:
        response = await _request_with_retry(
            "GET",
            f"{BASE}{path}",
            self._headers,
            client=self._client,
            params=params,
        )
        data = response.json()
        if not isinstance(data, dict):
            return {}
        return cast(JsonDict, data)

    async def post_json(self, path: str, payload: JsonDict) -> JsonDict:
        response = await _request_with_retry(
            "POST",
            f"{BASE}{path}",
            self._headers,
            client=self._client,
            json=payload,
        )
        data = response.json()
        if not isinstance(data, dict):
            return {}
        return cast(JsonDict, data)


def _extract_co_author(message: str) -> str | None:
    for line in message.splitlines():
        normalized = line.strip().lower()
        if normalized.startswith("co-authored-by:"):
            return normalized.replace("co-authored-by:", "").strip()
    return None
