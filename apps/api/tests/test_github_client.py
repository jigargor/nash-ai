"""Tests for app.github.client — all GitHub API calls are monkeypatched."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.github.client import (
    GitHubClient,
    _parse_next_link,
    _extract_co_author,
    _request_with_retry,
    MAX_REVIEW_FILE_BYTES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_FAKE_REQUEST = httpx.Request("GET", "https://api.github.com/test")


def _json_response(body: dict | list, *, status: int = 200, link: str = "") -> httpx.Response:
    headers = {"content-type": "application/json"}
    if link:
        headers["link"] = link
    return httpx.Response(
        status, content=json.dumps(body).encode(), headers=headers, request=_FAKE_REQUEST
    )


def _text_response(text: str, *, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        content=text.encode(),
        headers={"content-type": "text/plain"},
        request=_FAKE_REQUEST,
    )


def _fake_client(token: str = "test-token") -> GitHubClient:
    return GitHubClient(token=token)


# ---------------------------------------------------------------------------
# _parse_next_link
# ---------------------------------------------------------------------------


def test_parse_next_link_returns_url_when_present() -> None:
    header = '<https://api.github.com/repos/foo/bar/pulls?page=2>; rel="next", <https://api.github.com/repos/foo/bar/pulls?page=5>; rel="last"'
    url = _parse_next_link(header)
    assert url == "https://api.github.com/repos/foo/bar/pulls?page=2"


def test_parse_next_link_returns_none_when_absent() -> None:
    header = '<https://api.github.com/repos/foo/bar/pulls?page=1>; rel="prev"'
    assert _parse_next_link(header) is None


def test_parse_next_link_empty_header_returns_none() -> None:
    assert _parse_next_link("") is None


def test_parse_next_link_malformed_returns_none() -> None:
    assert _parse_next_link("not-a-link-header") is None


# ---------------------------------------------------------------------------
# _extract_co_author
# ---------------------------------------------------------------------------


def test_extract_co_author_finds_trailer() -> None:
    msg = "Fix bug\n\nCo-authored-by: alice@example.com"
    assert _extract_co_author(msg) == "alice@example.com"


def test_extract_co_author_returns_none_when_absent() -> None:
    assert _extract_co_author("Just a commit message") is None


def test_extract_co_author_case_insensitive() -> None:
    msg = "feat: add thing\nCO-AUTHORED-BY: Bob <bob@example.com>"
    result = _extract_co_author(msg)
    assert result is not None and "bob" in result


# ---------------------------------------------------------------------------
# GitHubClient.__init__ and for_installation
# ---------------------------------------------------------------------------


def test_github_client_init_sets_headers() -> None:
    client = GitHubClient(token="my-token")
    assert "Bearer my-token" in client._headers["Authorization"]
    assert "application/vnd.github+json" in client._headers["Accept"]


@pytest.mark.anyio
async def test_github_client_for_installation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.github.client.get_installation_token",
        AsyncMock(return_value="install-token"),
    )
    client = await GitHubClient.for_installation(12345)
    assert "Bearer install-token" in client._headers["Authorization"]


# ---------------------------------------------------------------------------
# _request_with_retry — retry logic
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_request_with_retry_returns_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch at module level to avoid httpx transport machinery
    async def _fake_retry(method: str, url: str, headers: dict, **_kw: object) -> httpx.Response:
        return _json_response({"id": 1})

    monkeypatch.setattr("app.github.client._request_with_retry", _fake_retry)
    client = _fake_client()
    result = await client.get_json("/repos/acme/repo/pulls/1")
    assert result["id"] == 1


@pytest.mark.anyio
async def test_request_with_retry_retries_on_429_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0

    async def _fake_request(*_args: object, **_kwargs: object) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                429, content=b"{}", request=_FAKE_REQUEST,
                headers={"content-type": "application/json"}
            )
        return _json_response({"ok": True})

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.request = _fake_request

    with patch("app.github.client.httpx.AsyncClient", return_value=mock_client):
        with patch("app.github.client.asyncio.sleep", new=AsyncMock()):
            resp = await _request_with_retry("GET", "https://api.github.com/test", {})

    assert resp.status_code == 200
    assert call_count == 2


@pytest.mark.anyio
async def test_request_with_retry_respects_retry_after_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0

    async def _fake_request(*_args: object, **_kwargs: object) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                429, content=b"{}",
                headers={"content-type": "application/json", "Retry-After": "5"},
                request=_FAKE_REQUEST,
            )
        return _json_response({"ok": True})

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.request = _fake_request

    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    with patch("app.github.client.httpx.AsyncClient", return_value=mock_client):
        with patch("app.github.client.asyncio.sleep", side_effect=_fake_sleep):
            await _request_with_retry("GET", "https://api.github.com/test", {})

    assert sleep_calls[0] == 5.0  # exact Retry-After value


# ---------------------------------------------------------------------------
# get_json and get_pull_request
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_json_returns_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response({"number": 42, "state": "open"})),
    )
    result = await client.get_json("/repos/acme/repo/pulls/42")
    assert result["number"] == 42


@pytest.mark.anyio
async def test_get_json_returns_empty_dict_for_non_dict_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _fake_client()
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response([{"item": 1}])),
    )
    result = await client.get_json("/some/list/endpoint")
    assert result == {}


@pytest.mark.anyio
async def test_get_pull_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    pr_data = {"number": 7, "state": "open", "title": "test PR"}
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response(pr_data)),
    )
    result = await client.get_pull_request("acme", "repo", 7)
    assert result["number"] == 7


# ---------------------------------------------------------------------------
# _get_paginated
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_paginated_single_page(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    items = [{"id": 1}, {"id": 2}]
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response(items)),
    )
    result = await client._get_paginated("/repos/a/b/pulls/1/files")
    assert result == items


@pytest.mark.anyio
async def test_get_paginated_follows_link_header(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    page1 = _json_response(
        [{"id": 1}],
        link='<https://api.github.com/repos/a/b/pulls/1/files?page=2>; rel="next"',
    )
    page2 = _json_response([{"id": 2}])

    call_count = 0

    async def _fake_retry(*_args: object, **_kwargs: object) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return page1 if call_count == 1 else page2

    monkeypatch.setattr("app.github.client._request_with_retry", _fake_retry)
    result = await client._get_paginated("/repos/a/b/pulls/1/files")
    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[1]["id"] == 2


@pytest.mark.anyio
async def test_get_pull_request_files_uses_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    files = [{"filename": f"file{i}.py"} for i in range(5)]
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response(files)),
    )
    result = await client.get_pull_request_files("acme", "repo", 1)
    assert len(result) == 5


@pytest.mark.anyio
async def test_get_pull_request_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    commits = [{"sha": "abc123", "commit": {"message": "fix: bug"}}]
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response(commits)),
    )
    result = await client.get_pull_request_commits("acme", "repo", 1)
    assert result[0]["sha"] == "abc123"


# ---------------------------------------------------------------------------
# get_file_content — size cap and normal path
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_file_content_skips_large_file(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    big_size = MAX_REVIEW_FILE_BYTES + 1
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response({"size": big_size, "content": "aGVsbG8="})),
    )
    result = await client.get_file_content("acme", "repo", "big.py", "main")
    assert "skipped" in result.lower()
    assert str(big_size) in result.replace(",", "")


@pytest.mark.anyio
async def test_get_file_content_decodes_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    client = _fake_client()
    content = "print('hello')"
    encoded = base64.b64encode(content.encode()).decode()
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response({"size": 14, "content": encoded})),
    )
    result = await client.get_file_content("acme", "repo", "hello.py", "main")
    assert result == content


@pytest.mark.anyio
async def test_get_file_content_returns_empty_for_missing_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _fake_client()
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response({"size": 0})),
    )
    result = await client.get_file_content("acme", "repo", "empty.py", "main")
    assert result == ""


# ---------------------------------------------------------------------------
# get_pull_request_diff
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_pull_request_diff_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    diff = "diff --git a/foo.py b/foo.py\n+print('hello')"
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_text_response(diff)),
    )
    result = await client.get_pull_request_diff("acme", "repo", 1)
    assert result == diff


# ---------------------------------------------------------------------------
# search_code
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_code_returns_items(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    items = [{"path": "src/auth.py", "sha": "abc"}]
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response({"items": items})),
    )
    result = await client.search_code("acme", "repo", "API_KEY")
    assert len(result) == 1
    assert result[0]["path"] == "src/auth.py"


@pytest.mark.anyio
async def test_search_code_with_path_glob(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response({"items": []})),
    )
    result = await client.search_code("acme", "repo", "secret", path_glob="src/**/*.py")
    assert result == []


# ---------------------------------------------------------------------------
# get_commit_files
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_commit_files_returns_files(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    files = [{"filename": "src/main.py", "status": "modified"}]
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response({"files": files})),
    )
    result = await client.get_commit_files("acme", "repo", "abc123")
    assert result[0]["filename"] == "src/main.py"


@pytest.mark.anyio
async def test_get_commit_files_empty_sha_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _fake_client()
    result = await client.get_commit_files("acme", "repo", "")
    assert result == []


# ---------------------------------------------------------------------------
# get_pr_reviews_by_bot
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_pr_reviews_by_bot_filters_by_type(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    comments = [
        {"id": 1, "user": {"login": "humanuser", "type": "User"}, "body": "comment"},
        {"id": 2, "user": {"login": "mybot[bot]", "type": "Bot"}, "body": "bot comment"},
    ]
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response(comments)),
    )
    result = await client.get_pr_reviews_by_bot("acme", "repo", 1)
    assert len(result) == 1
    assert result[0]["id"] == 2


@pytest.mark.anyio
async def test_get_pr_reviews_by_bot_filters_by_login(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    comments = [
        {"id": 1, "user": {"login": "nash-ai[bot]", "type": "Bot"}, "body": "nash comment"},
        {"id": 2, "user": {"login": "other-bot[bot]", "type": "Bot"}, "body": "other comment"},
    ]
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response(comments)),
    )
    result = await client.get_pr_reviews_by_bot("acme", "repo", 1, bot_login="Nash-AI[bot]")
    assert len(result) == 1
    assert result[0]["id"] == 1


# ---------------------------------------------------------------------------
# post_issue_comment
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_post_issue_comment_returns_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    created = {"id": 999, "body": "hello"}
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response(created, status=201)),
    )
    result = await client.post_issue_comment("acme", "repo", 7, "hello")
    assert result["id"] == 999


# ---------------------------------------------------------------------------
# get_pull_review_comment_reactions / replies
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_pull_review_comment_reactions_normalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _fake_client()
    raw = [{"user": {"login": "alice"}, "content": "+1", "created_at": "2026-01-01T00:00:00Z"}]
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response(raw)),
    )
    result = await client.get_pull_review_comment_reactions("acme", "repo", 101)
    assert result[0]["user"] == "alice"
    assert result[0]["content"] == "+1"


@pytest.mark.anyio
async def test_get_pull_review_comment_replies_normalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _fake_client()
    raw = [{"user": {"login": "bob"}, "body": "LGTM", "created_at": "2026-01-01T00:00:00Z"}]
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response(raw)),
    )
    result = await client.get_pull_review_comment_replies("acme", "repo", 101)
    assert result[0]["user"] == "bob"
    assert result[0]["body"] == "LGTM"


# ---------------------------------------------------------------------------
# is_pull_review_thread_resolved
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_is_pull_review_thread_resolved_returns_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _fake_client()
    threads = [
        {
            "resolved": True,
            "comments": [{"id": 42}, {"id": 43}],
        }
    ]
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response(threads)),
    )
    result = await client.is_pull_review_thread_resolved("acme", "repo", 1, 42)
    assert result is True


@pytest.mark.anyio
async def test_is_pull_review_thread_resolved_returns_false_when_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _fake_client()
    threads = [{"resolved": True, "comments": [{"id": 99}]}]
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response(threads)),
    )
    result = await client.is_pull_review_thread_resolved("acme", "repo", 1, 42)
    assert result is False


@pytest.mark.anyio
async def test_is_pull_review_thread_resolved_returns_false_on_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _fake_client()
    error = httpx.HTTPStatusError(
        "404",
        request=_FAKE_REQUEST,
        response=httpx.Response(404, content=b"{}", request=_FAKE_REQUEST),
    )
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(side_effect=error),
    )
    result = await client.is_pull_review_thread_resolved("acme", "repo", 1, 42)
    assert result is False


# ---------------------------------------------------------------------------
# line_exists_in_pull_request_final_state
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_line_exists_in_pr_final_state_uses_merge_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _fake_client()
    import base64

    content = "API_KEY = 'secret'"
    encoded = base64.b64encode(content.encode()).decode()
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response({"size": len(content), "content": encoded})),
    )
    result = await client.line_exists_in_pull_request_final_state(
        owner="acme",
        repo="repo",
        pr_state={"merge_commit_sha": "abc123"},
        file_path="src/config.py",
        line_text="API_KEY",
    )
    assert result is True


@pytest.mark.anyio
async def test_line_exists_in_pr_final_state_returns_true_on_fetch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _fake_client()
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(side_effect=Exception("not found")),
    )
    result = await client.line_exists_in_pull_request_final_state(
        owner="acme",
        repo="repo",
        pr_state={"merge_commit_sha": "abc123"},
        file_path="gone.py",
        line_text="anything",
    )
    assert result is True


@pytest.mark.anyio
async def test_line_exists_in_pr_final_state_returns_true_when_no_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _fake_client()
    result = await client.line_exists_in_pull_request_final_state(
        owner="acme",
        repo="repo",
        pr_state={"merge_commit_sha": None, "head": {}},
        file_path="src/main.py",
        line_text="anything",
    )
    assert result is True


# ---------------------------------------------------------------------------
# post_json
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_post_json_returns_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response({"id": 1}, status=201)),
    )
    result = await client.post_json("/repos/a/b/issues/1/comments", {"body": "hi"})
    assert result["id"] == 1


# ---------------------------------------------------------------------------
# get_file_history
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_file_history_returns_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client()
    commits = [{"sha": "abc", "commit": {"message": "update"}}]
    monkeypatch.setattr(
        "app.github.client._request_with_retry",
        AsyncMock(return_value=_json_response(commits)),
    )
    result = await client.get_file_history("acme", "repo", "src/main.py")
    assert result[0]["sha"] == "abc"


# ---------------------------------------------------------------------------
# smoke_check helpers
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_resolve_installation_id_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.github.smoke_check import resolve_installation_id

    monkeypatch.setenv("GITHUB_INSTALLATION_ID", "98765")
    result = await resolve_installation_id()
    assert result == 98765


@pytest.mark.anyio
async def test_resolve_installation_id_from_api(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.github.smoke_check import resolve_installation_id

    monkeypatch.delenv("GITHUB_INSTALLATION_ID", raising=False)
    monkeypatch.setattr("app.github.smoke_check.create_jwt", lambda: "fake-jwt")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [{"id": 11111}]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.github.smoke_check.httpx.AsyncClient", return_value=mock_client):
        result = await resolve_installation_id()

    assert result == 11111


@pytest.mark.anyio
async def test_resolve_installation_id_raises_when_no_installations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.github.smoke_check import resolve_installation_id

    monkeypatch.delenv("GITHUB_INSTALLATION_ID", raising=False)
    monkeypatch.setattr("app.github.smoke_check.create_jwt", lambda: "fake-jwt")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = []

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.github.smoke_check.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="No GitHub App installations"):
            await resolve_installation_id()
