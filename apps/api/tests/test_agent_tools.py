import json

import pytest

from app.agent import tools


class _FakeGitHubClient:
    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        assert owner == "acme"
        assert repo == "demo"
        assert ref == "deadbeef"
        return f"content:{path}"

    async def search_code(
        self, _owner: str, _repo: str, pattern: str, _path_glob: str | None = None
    ) -> list[dict]:
        return [{"path": "a.py", "sha": "123"}, {"path": f"{pattern}.py", "sha": "456"}]

    async def get_file_history(self, _owner: str, _repo: str, _path: str) -> list[dict]:
        return [
            {"sha": "123", "commit": {"message": "feat: update"}},
            {"sha": "456", "commit": {"message": "fix: bug"}},
        ]


def _context() -> dict[str, object]:
    return {
        "github_client": _FakeGitHubClient(),
        "owner": "acme",
        "repo": "demo",
        "head_sha": "deadbeef",
    }


@pytest.mark.anyio
async def test_execute_tool_fetch_file_content_returns_text() -> None:
    output = await tools.execute_tool("fetch_file_content", {"path": "app.py"}, _context())
    assert output == "content:app.py"


@pytest.mark.anyio
async def test_execute_tool_search_codebase_normalizes_items() -> None:
    output = await tools.execute_tool("search_codebase", {"pattern": "jwt.decode"}, _context())
    data = json.loads(output)
    assert data[0] == {"path": "a.py", "sha": "123"}


@pytest.mark.anyio
async def test_execute_tool_get_file_history_normalizes_commits() -> None:
    output = await tools.execute_tool("get_file_history", {"path": "app.py"}, _context())
    data = json.loads(output)
    assert data[0]["sha"] == "123"
    assert data[0]["message"] == "feat: update"


@pytest.mark.anyio
async def test_execute_tool_unknown_name_returns_error_string() -> None:
    output = await tools.execute_tool("unknown", {}, _context())
    assert output == "Unknown tool: unknown"


@pytest.mark.anyio
async def test_execute_tool_returns_failure_string_on_tool_exception() -> None:
    context = _context()
    context["github_client"] = object()
    output = await tools.execute_tool("fetch_file_content", {"path": "app.py"}, context)
    assert output.startswith("Tool fetch_file_content failed:")
