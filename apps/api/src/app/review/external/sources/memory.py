"""In-memory ``RepoSource`` used by tests and local demos.

Accepts a mapping of ``(ref -> {path: content})`` at construction and
reports each file's metadata from that map, avoiding any network traffic.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.review.external.errors import RepoAccessError
from app.review.external.models import FileDescriptor, RepoRef


class InMemoryRepoSource:
    """Deterministic source for offline tests."""

    def __init__(
        self,
        *,
        owner: str,
        repo: str,
        default_branch: str,
        refs: Mapping[str, Mapping[str, str]],
    ) -> None:
        if default_branch not in refs:
            raise ValueError("default_branch must be one of the provided refs")
        self._owner = owner
        self._repo = repo
        self._default_branch = default_branch
        self._refs: dict[str, dict[str, str]] = {
            ref_name: dict(files) for ref_name, files in refs.items()
        }

    async def resolve_ref(self, owner: str, repo: str, ref: str | None) -> RepoRef:
        if owner != self._owner or repo != self._repo:
            raise RepoAccessError(
                f"InMemoryRepoSource does not host {owner}/{repo}."
            )
        normalized_ref = (ref or "").strip() or self._default_branch
        if normalized_ref not in self._refs:
            raise RepoAccessError(f"Ref '{normalized_ref}' is not available.")
        return RepoRef(
            owner=owner,
            repo=repo,
            ref=normalized_ref,
            default_branch=self._default_branch,
        )

    async def list_files(
        self, repo_ref: RepoRef, *, max_files: int = 3_000
    ) -> list[FileDescriptor]:
        files = self._refs.get(repo_ref.ref, {})
        out: list[FileDescriptor] = []
        for path, content in files.items():
            out.append(
                FileDescriptor(
                    path=path,
                    sha=None,
                    size_bytes=len(content.encode("utf-8")),
                )
            )
            if len(out) >= max_files:
                break
        return out

    async def fetch_file(
        self, repo_ref: RepoRef, path: str, *, max_bytes: int = 5_000
    ) -> str:
        content = self._refs.get(repo_ref.ref, {}).get(path, "")
        return content[:max_bytes]

    async def aclose(self) -> None:
        return None
