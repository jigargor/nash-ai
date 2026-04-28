"""Compatibility shim around :mod:`app.review.external` GitHub source.

Historical callers (``orchestrator``, ``api.external_evals``, existing
tests) keep importing ``PublicRepoRef``, ``parse_public_repo_url``, and
module-level async helpers. Those now delegate to the new engine.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.review.external.errors import RepoAccessError as _RepoAccessError
from app.review.external.models import FileDescriptor, RepoRef
from app.review.external.sources.github import GitHubRepoSource


class PublicRepoError(RuntimeError):
    """Legacy error class; still raised by the shim helpers."""


@dataclass(slots=True)
class PublicRepoRef:
    owner: str
    repo: str
    ref: str
    default_branch: str

    @classmethod
    def from_model(cls, repo_ref: RepoRef) -> "PublicRepoRef":
        return cls(
            owner=repo_ref.owner,
            repo=repo_ref.repo,
            ref=repo_ref.ref,
            default_branch=repo_ref.default_branch,
        )

    def to_model(self) -> RepoRef:
        return RepoRef(
            owner=self.owner,
            repo=self.repo,
            ref=self.ref,
            default_branch=self.default_branch,
        )


def parse_public_repo_url(repo_url: str) -> tuple[str, str]:
    """Validate a public GitHub URL and return ``(owner, repo)``."""

    try:
        return RepoRef.parse_url(repo_url)
    except ValueError as exc:
        raise PublicRepoError(str(exc)) from None


async def resolve_repo_ref(owner: str, repo: str, ref: str | None) -> PublicRepoRef:
    async with GitHubRepoSource() as source:
        try:
            resolved = await source.resolve_ref(owner, repo, ref)
        except _RepoAccessError as exc:
            raise PublicRepoError(str(exc)) from None
    return PublicRepoRef.from_model(resolved)


async def list_repo_files(
    repo_ref: PublicRepoRef, *, max_files: int = 3_000
) -> list[FileDescriptor]:
    async with GitHubRepoSource() as source:
        try:
            return await source.list_files(repo_ref.to_model(), max_files=max_files)
        except _RepoAccessError as exc:
            raise PublicRepoError(str(exc)) from None


async def fetch_file_sample(
    repo_ref: PublicRepoRef, path: str, *, max_bytes: int = 5_000
) -> str:
    async with GitHubRepoSource() as source:
        return await source.fetch_file(repo_ref.to_model(), path, max_bytes=max_bytes)


__all__ = [
    "PublicRepoError",
    "PublicRepoRef",
    "fetch_file_sample",
    "list_repo_files",
    "parse_public_repo_url",
    "resolve_repo_ref",
]
