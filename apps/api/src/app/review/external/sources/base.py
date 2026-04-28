"""Protocol describing the I/O surface a ``ReviewEngine`` depends on.

The engine is pure logic over this interface, which means:

* production code plugs in ``GitHubRepoSource`` (httpx + GitHub REST),
* tests plug in ``InMemoryRepoSource`` with hand-crafted file trees,
* future adapters (GitLab, local FS, tarball snapshot) slot in with no
  changes to downstream pipeline code.
"""

from __future__ import annotations

from typing import Protocol

from app.review.external.models import FileDescriptor, RepoRef


class RepoSource(Protocol):
    """Repository I/O surface consumed by the review engine."""

    async def resolve_ref(self, owner: str, repo: str, ref: str | None) -> RepoRef:
        """Resolve ``(owner, repo, ref)`` into a concrete ``RepoRef``."""

    async def list_files(self, repo_ref: RepoRef, *, max_files: int) -> list[FileDescriptor]:
        """Return a bounded list of blob files at ``repo_ref``."""

    async def fetch_file(self, repo_ref: RepoRef, path: str, *, max_bytes: int) -> str:
        """Return UTF-8 content for ``path`` (truncated to ``max_bytes``).

        Implementations must return an empty string when the file cannot
        be read for any reason (missing, binary, quota-exhausted, etc.)
        so callers do not need to branch on error types per file.
        """

    async def aclose(self) -> None:
        """Release any owned resources (HTTP clients, caches)."""
