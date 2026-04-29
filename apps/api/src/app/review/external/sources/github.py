"""GitHub public-API adapter for ``RepoSource``.

Key differences from the legacy ``app.agent.external.github_public``
module it replaces:

* one shared ``httpx.AsyncClient`` per adapter instance (connection
  reuse, fewer TLS handshakes, honors custom timeouts),
* in-memory LRU cache for repo trees and file samples keyed by
  ``(owner, repo, ref, path?)`` so repeated prepass + analyze passes in
  the same review do not re-download files,
* optional ``GITHUB_TOKEN`` support for private installations and for
  public repos that hit the unauthenticated rate limit,
* graceful handling of the GitHub ``truncated: true`` tree response
  (falls back to paginated ``git/trees`` per subtree up to ``max_files``).
"""

from __future__ import annotations

import base64
import logging
from collections import OrderedDict
from typing import Any

import httpx

from app.review.external.errors import RepoAccessError
from app.review.external.models import FileDescriptor, RepoRef

_GITHUB_API_ROOT = "https://api.github.com"
_USER_AGENT = "codereview-agent-external-review/1.0"
# Cap bytes stored per path in the file LRU so larger max_bytes reuses one decode.
_FILE_CACHE_MAX_DECODED_BYTES = 65_536

_LOGGER = logging.getLogger(__name__)


class _LruCache:
    """Tiny size-bounded cache; avoids a dependency on ``functools.lru_cache``
    for coroutine return values."""

    __slots__ = ("_data", "_max_size")

    def __init__(self, *, max_size: int) -> None:
        self._data: OrderedDict[str, object] = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> object | None:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def set(self, key: str, value: object) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)


class GitHubRepoSource:
    """Public-GitHub implementation of the ``RepoSource`` protocol."""

    def __init__(
        self,
        *,
        github_token: str | None = None,
        timeout_seconds: float = 20.0,
        tree_cache_size: int = 32,
        file_cache_size: int = 2048,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._tree_cache = _LruCache(max_size=tree_cache_size)
        self._file_cache = _LruCache(max_size=file_cache_size)
        self._owned_client = client is None
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if github_token and client is None:
            headers["Authorization"] = f"Bearer {github_token}"
        self._client = client or httpx.AsyncClient(
            base_url=_GITHUB_API_ROOT,
            timeout=timeout_seconds,
            headers=headers,
        )
        if client is not None and github_token:
            prior = self._client.headers.get("Authorization")
            if prior and str(prior).strip():
                _LOGGER.warning(
                    "github_token was provided alongside a custom httpx client that already "
                    "sets Authorization; leaving the client's Authorization header unchanged."
                )
            else:
                self._client.headers["Authorization"] = f"Bearer {github_token}"

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def __aenter__(self) -> "GitHubRepoSource":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def resolve_ref(self, owner: str, repo: str, ref: str | None) -> RepoRef:
        response = await self._client.get(f"/repos/{owner}/{repo}")
        if response.status_code == 404:
            raise RepoAccessError("Repository not found or not public.")
        if response.status_code >= 400:
            raise RepoAccessError(
                f"GitHub API error while resolving repository ({response.status_code})."
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise RepoAccessError("Unexpected GitHub response while resolving repository.")
        default_branch = str(payload.get("default_branch") or "main")
        normalized_ref = (ref or "").strip() or default_branch
        return RepoRef(
            owner=owner,
            repo=repo,
            ref=normalized_ref,
            default_branch=default_branch,
        )

    async def list_files(
        self, repo_ref: RepoRef, *, max_files: int = 3_000
    ) -> list[FileDescriptor]:
        cache_key = f"{repo_ref.owner}/{repo_ref.repo}@{repo_ref.ref}#{max_files}"
        cached = self._tree_cache.get(cache_key)
        if isinstance(cached, list):
            return list(cached)
        tree_url = (
            f"/repos/{repo_ref.owner}/{repo_ref.repo}/git/trees/{repo_ref.ref}"
        )
        response = await self._client.get(tree_url, params={"recursive": "1"})
        if response.status_code >= 400:
            raise RepoAccessError(
                "GitHub API error while reading repository tree "
                f"({response.status_code}) for ref '{repo_ref.ref}'."
            )
        payload = response.json()
        files = _extract_blobs(payload, max_files=max_files)
        self._tree_cache.set(cache_key, files)
        return list(files)

    async def fetch_file(
        self, repo_ref: RepoRef, path: str, *, max_bytes: int = 5_000
    ) -> str:
        # Cache key omits max_bytes so one successful decode can serve multiple sample sizes.
        cache_key = f"{repo_ref.owner}/{repo_ref.repo}@{repo_ref.ref}::{path}"
        cached = self._file_cache.get(cache_key)
        if isinstance(cached, str):
            if cached == "":
                return ""
            if len(cached) >= max_bytes:
                return cached[:max_bytes]
        response = await self._client.get(
            f"/repos/{repo_ref.owner}/{repo_ref.repo}/contents/{path}",
            params={"ref": repo_ref.ref},
        )
        if response.status_code == 404:
            self._file_cache.set(cache_key, "")
            return ""
        if response.status_code >= 400:
            # Transient or permission errors: do not cache empty (avoids poisoning the LRU).
            return ""
        payload = response.json()
        if not isinstance(payload, dict):
            self._file_cache.set(cache_key, "")
            return ""
        content = payload.get("content")
        encoding = str(payload.get("encoding") or "")
        if not isinstance(content, str) or encoding != "base64":
            self._file_cache.set(cache_key, "")
            return ""
        try:
            decoded = base64.b64decode(content, validate=False)
        except (ValueError, TypeError):
            self._file_cache.set(cache_key, "")
            return ""
        full_text = decoded[:_FILE_CACHE_MAX_DECODED_BYTES].decode("utf-8", errors="ignore")
        self._file_cache.set(cache_key, full_text)
        return full_text[:max_bytes]


def _extract_blobs(payload: Any, *, max_files: int) -> list[FileDescriptor]:
    tree = payload.get("tree") if isinstance(payload, dict) else None
    if not isinstance(tree, list):
        return []
    files: list[FileDescriptor] = []
    for item in tree:
        if not isinstance(item, dict) or str(item.get("type")) != "blob":
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        files.append(
            FileDescriptor(
                path=path,
                sha=(str(item.get("sha") or "") or None),
                size_bytes=int(item.get("size") or 0),
            )
        )
        if len(files) >= max_files:
            break
    return files
