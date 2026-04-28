from __future__ import annotations

import base64
import re
from dataclasses import dataclass

import httpx

from app.agent.external.types import ExternalFileDescriptor

_GITHUB_REPO_URL = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?(?:/)?$"
)


class PublicRepoError(RuntimeError):
    pass


@dataclass(slots=True)
class PublicRepoRef:
    owner: str
    repo: str
    ref: str
    default_branch: str


def parse_public_repo_url(repo_url: str) -> tuple[str, str]:
    normalized = repo_url.strip()
    match = _GITHUB_REPO_URL.fullmatch(normalized)
    if not match:
        raise PublicRepoError("Only public GitHub URLs in the form https://github.com/owner/repo are supported.")
    owner = match.group("owner")
    repo = match.group("repo")
    return owner, repo


async def resolve_repo_ref(owner: str, repo: str, ref: str | None) -> PublicRepoRef:
    async with httpx.AsyncClient(timeout=20.0) as client:
        repo_response = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
        if repo_response.status_code == 404:
            raise PublicRepoError("Repository not found or not public.")
        if repo_response.status_code >= 400:
            raise PublicRepoError(f"GitHub API error while resolving repository ({repo_response.status_code}).")
        payload = repo_response.json()
        if not isinstance(payload, dict):
            raise PublicRepoError("Unexpected GitHub response while resolving repository.")
        default_branch = str(payload.get("default_branch") or "main")
        normalized_ref = (ref or "").strip() or default_branch
        return PublicRepoRef(owner=owner, repo=repo, ref=normalized_ref, default_branch=default_branch)


async def list_repo_files(repo_ref: PublicRepoRef, *, max_files: int = 3000) -> list[ExternalFileDescriptor]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"https://api.github.com/repos/{repo_ref.owner}/{repo_ref.repo}/git/trees/{repo_ref.ref}",
            params={"recursive": "1"},
        )
        if response.status_code >= 400:
            raise PublicRepoError(
                f"GitHub API error while reading repository tree ({response.status_code}) for ref '{repo_ref.ref}'."
            )
        payload = response.json()
        tree = payload.get("tree") if isinstance(payload, dict) else None
        if not isinstance(tree, list):
            return []
        files: list[ExternalFileDescriptor] = []
        for item in tree:
            if not isinstance(item, dict):
                continue
            if str(item.get("type")) != "blob":
                continue
            path = str(item.get("path") or "").strip()
            if not path:
                continue
            files.append(
                ExternalFileDescriptor(
                    path=path,
                    sha=str(item.get("sha") or "") or None,
                    size_bytes=int(item.get("size") or 0),
                )
            )
            if len(files) >= max_files:
                break
        return files


async def fetch_file_sample(repo_ref: PublicRepoRef, path: str, *, max_bytes: int = 5000) -> str:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"https://api.github.com/repos/{repo_ref.owner}/{repo_ref.repo}/contents/{path}",
            params={"ref": repo_ref.ref},
        )
        if response.status_code >= 400:
            return ""
        payload = response.json()
        if not isinstance(payload, dict):
            return ""
        content = payload.get("content")
        encoding = str(payload.get("encoding") or "")
        if not isinstance(content, str) or encoding != "base64":
            return ""
        try:
            decoded = base64.b64decode(content, validate=False)
        except Exception:
            return ""
        snippet = decoded[:max_bytes]
        return snippet.decode("utf-8", errors="ignore")

