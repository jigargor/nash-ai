import logging
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


class _FileReader(Protocol):
    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str: ...


async def safe_fetch_file(
    gh: _FileReader,
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> str | None:
    """Fetch a file, returning None if absent or on any fetch error.

    404 is expected (file doesn't exist in this repo/ref) and is silent.
    Non-404 HTTP errors and network errors are logged at WARNING level before
    returning None so callers get resilient best-effort reads without swallowing
    bugs silently.
    """
    try:
        return await gh.get_file_content(owner, repo, path, ref)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            logger.warning(
                "fetch %s/%s/%s ref=%s failed status=%s",
                owner,
                repo,
                path,
                ref,
                exc.response.status_code,
            )
        return None
    except Exception as exc:
        logger.warning("fetch %s/%s/%s ref=%s failed err=%r", owner, repo, path, ref, exc)
        return None


def split_repo_full_name(repo_full_name: str) -> tuple[str, str]:
    parts = repo_full_name.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid repo_full_name: {repo_full_name}")
    return parts[0], parts[1]
