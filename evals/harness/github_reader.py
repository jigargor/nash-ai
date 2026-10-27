"""Read-only GitHub client for evals — caches fixtures under evals/cache/github."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = REPO_ROOT / "evals" / "cache" / "github"


class CachedGitHubReader:
    """Public-repo reader using GITHUB_TOKEN (or anonymous) with on-disk cache."""

    def __init__(
        self,
        *,
        token: str | None = None,
        cache_dir: Path | None = None,
        use_cache: bool = True,
    ) -> None:
        self._token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self._cache_dir = cache_dir or CACHE_ROOT
        self._use_cache = use_cache
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_hits = 0
        self.network_calls = 0

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nash-ai-evals",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _cache_path(self, key: str) -> Path:
        safe = key.replace("/", "__").replace(":", "_")
        return self._cache_dir / f"{safe}.json"

    def _read_cache(self, key: str) -> Any | None:
        if not self._use_cache:
            return None
        path = self._cache_path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_cache(self, key: str, payload: Any) -> None:
        if not self._use_cache:
            return
        path = self._cache_path(key)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    async def _get_json(self, url: str, *, cache_key: str, accept: str | None = None) -> Any:
        cached = self._read_cache(cache_key)
        if cached is not None:
            self.cache_hits += 1
            return cached
        self.network_calls += 1
        headers = self._headers()
        if accept:
            headers["Accept"] = accept
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            if "diff" in (accept or ""):
                payload: Any = response.text
            else:
                payload = response.json()
        self._write_cache(cache_key, payload)
        return payload

    async def get_pull_request(self, owner: str, repo: str, pr_number: int) -> dict[str, Any]:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        data = await self._get_json(url, cache_key=f"{owner}__{repo}__pr_{pr_number}__meta")
        assert isinstance(data, dict)
        return data

    async def get_pull_request_diff(self, owner: str, repo: str, pr_number: int) -> str:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        data = await self._get_json(
            url,
            cache_key=f"{owner}__{repo}__pr_{pr_number}__diff",
            accept="application/vnd.github.v3.diff",
        )
        return str(data)

    async def get_pull_request_commits(
        self, owner: str, repo: str, pr_number: int
    ) -> list[dict[str, Any]]:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/commits"
        data = await self._get_json(url, cache_key=f"{owner}__{repo}__pr_{pr_number}__commits")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        import base64

        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        cache_key = f"{owner}__{repo}__file__{ref}__{path.replace('/', '_')}"
        data = await self._get_json(url + f"?ref={ref}", cache_key=cache_key)
        if isinstance(data, dict) and data.get("encoding") == "base64":
            return base64.b64decode(str(data.get("content") or "")).decode("utf-8", errors="replace")
        if isinstance(data, dict) and isinstance(data.get("content"), str):
            return str(data["content"])
        raise FileNotFoundError(path)

    async def get_pull_request_files(
        self, owner: str, repo: str, pr_number: int
    ) -> list[dict[str, Any]]:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files?per_page=100"
        data = await self._get_json(url, cache_key=f"{owner}__{repo}__pr_{pr_number}__files")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    async def get_pr_reviews_by_bot(
        self, owner: str, repo: str, pr_number: int
    ) -> list[dict[str, Any]]:
        return []

    async def get_pull_request_review_comments(
        self, owner: str, repo: str, pr_number: int
    ) -> list[dict[str, Any]]:
        """Human/competitor review comments already on the PR (weak goldens, pairwise B)."""
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments?per_page=100"
        data = await self._get_json(url, cache_key=f"{owner}__{repo}__pr_{pr_number}__review_comments")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    async def list_pull_requests(
        self, owner: str, repo: str, *, state: str = "all", per_page: int = 30
    ) -> list[dict[str, Any]]:
        url = (
            f"https://api.github.com/repos/{owner}/{repo}/pulls"
            f"?state={state}&per_page={per_page}&sort=updated&direction=desc"
        )
        data = await self._get_json(url, cache_key=f"{owner}__{repo}__prs_{state}_{per_page}")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []
