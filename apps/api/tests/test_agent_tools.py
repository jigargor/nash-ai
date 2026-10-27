from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from app.agent import tools

OSV_QUERY_URL = "https://api.osv.dev/v1/query"


class _FakeGitHubClient:
    def __init__(
        self,
        *,
        files: dict[str, str] | None = None,
        tree: list[object] | None = None,
    ) -> None:
        self.files = files or {}
        self.tree = tree
        self.calls: list[tuple[object, ...]] = []

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        assert owner == "acme"
        assert repo == "demo"
        assert ref == "deadbeef"
        self.calls.append(("get_file_content", path))
        return self.files.get(path, f"content:{path}")

    async def get_json(self, path: str, params: dict[str, str] | None = None) -> dict:
        self.calls.append(("get_json", path, params))
        return {"sha": "deadbeef", "tree": self.tree}

    async def search_code(
        self, _owner: str, _repo: str, pattern: str, _path_glob: str | None = None
    ) -> list[dict]:
        self.calls.append(("search_code", pattern, _path_glob))
        return [{"path": "a.py", "sha": "123"}, {"path": f"{pattern}.py", "sha": "456"}]

    async def get_file_history(self, _owner: str, _repo: str, _path: str) -> list[dict]:
        self.calls.append(("get_file_history", _path))
        return [
            {"sha": "123", "commit": {"message": "feat: update"}},
            {"sha": "456", "commit": {"message": "fix: bug"}},
            {"sha": "789", "commit": None},
        ]


def _context(gh: _FakeGitHubClient | None = None, **extra: object) -> dict[str, object]:
    context: dict[str, object] = {
        "github_client": gh or _FakeGitHubClient(),
        "owner": "acme",
        "repo": "demo",
        "head_sha": "deadbeef",
    }
    context.update(extra)
    return context


def _patch_osv_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> list[httpx.Request]:
    """Route every httpx.AsyncClient created by the tools module through a MockTransport."""
    seen: list[httpx.Request] = []
    real_client = httpx.AsyncClient

    def _recording_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def _factory(**kwargs: object) -> httpx.AsyncClient:
        transport = httpx.MockTransport(_recording_handler)
        return real_client(transport=transport, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(tools.httpx, "AsyncClient", _factory)
    return seen


# ---------------------------------------------------------------------------
# fetch_file_content
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_execute_tool_fetch_file_content_returns_text() -> None:
    output = await tools.execute_tool("fetch_file_content", {"path": "app.py"}, _context())
    assert output == "content:app.py"


@pytest.mark.anyio
async def test_execute_tool_fetch_file_content_populates_fetched_files_normalized() -> None:
    gh = _FakeGitHubClient(files={"app.py": "line one\r\nline two\rline three"})
    context = _context(gh)

    output = await tools.execute_tool("fetch_file_content", {"path": "app.py"}, context)

    assert output == "line one\nline two\nline three"
    assert context["fetched_files"] == {"app.py": "line one\nline two\nline three"}


@pytest.mark.anyio
async def test_execute_tool_fetch_file_content_normalizes_backslash_paths() -> None:
    context = _context()

    output = await tools.execute_tool("fetch_file_content", {"path": "src\\app.py"}, context)

    assert output == "content:src/app.py"
    assert context["fetched_files"] == {"src/app.py": "content:src/app.py"}


@pytest.mark.anyio
async def test_execute_tool_fetch_file_content_truncates_oversized_output() -> None:
    huge = "x" * (tools.MAX_TOOL_RESULT_CHARS + 500)
    gh = _FakeGitHubClient(files={"big.py": huge})

    output = await tools.execute_tool("fetch_file_content", {"path": "big.py"}, _context(gh))

    assert output.endswith("\n...truncated")
    assert len(output) == tools.MAX_TOOL_RESULT_CHARS + len("\n...truncated")
    assert output[: tools.MAX_TOOL_RESULT_CHARS] == "x" * tools.MAX_TOOL_RESULT_CHARS


# ---------------------------------------------------------------------------
# read_file_range
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_execute_tool_read_file_range_returns_numbered_lines_from_cache() -> None:
    gh = _FakeGitHubClient()
    context = _context(gh, fetched_files={"app.py": "alpha\nbeta\ngamma\ndelta"})

    output = await tools.execute_tool(
        "read_file_range", {"path": "app.py", "start_line": 2, "end_line": 3}, context
    )

    assert output == "2|beta\n3|gamma"
    assert gh.calls == []


@pytest.mark.anyio
async def test_execute_tool_read_file_range_clamps_out_of_bounds_range() -> None:
    context = _context(fetched_files={"app.py": "alpha\nbeta\ngamma"})

    output = await tools.execute_tool(
        "read_file_range", {"path": "app.py", "start_line": -5, "end_line": 999}, context
    )

    assert output == "1|alpha\n2|beta\n3|gamma"


@pytest.mark.anyio
async def test_execute_tool_read_file_range_inverted_range_returns_empty() -> None:
    context = _context(fetched_files={"app.py": "alpha\nbeta\ngamma"})

    output = await tools.execute_tool(
        "read_file_range", {"path": "app.py", "start_line": 3, "end_line": 1}, context
    )

    assert output == ""


@pytest.mark.anyio
async def test_execute_tool_read_file_range_fetches_and_caches_uncached_file() -> None:
    gh = _FakeGitHubClient(files={"app.py": "one\r\ntwo\r\nthree"})
    context = _context(gh)

    output = await tools.execute_tool(
        "read_file_range", {"path": "app.py", "start_line": 1, "end_line": 2}, context
    )

    assert output == "1|one\n2|two"
    assert gh.calls == [("get_file_content", "app.py")]
    assert context["fetched_files"] == {"app.py": "one\ntwo\nthree"}


@pytest.mark.anyio
async def test_execute_tool_read_file_range_rejects_non_integer_lines() -> None:
    context = _context(fetched_files={"app.py": "alpha"})

    output = await tools.execute_tool(
        "read_file_range", {"path": "app.py", "start_line": "x", "end_line": 1}, context
    )

    assert output.startswith("Tool read_file_range failed:")


# ---------------------------------------------------------------------------
# list_directory
# ---------------------------------------------------------------------------


_TREE: list[object] = [
    {"path": "README.md", "type": "blob"},
    {"path": "src", "type": "tree"},
    {"path": "src/app", "type": "tree"},
    {"path": "src/app/main.py", "type": "blob"},
    {"path": "src/app/nested/util.py", "type": "blob"},
    {"path": "src/apple.py", "type": "blob"},
    {"type": "blob"},
    "not-a-dict",
]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/app", ["src/app", "src/app/main.py", "src/app/nested/util.py"]),
        ("src/app/", ["src/app/main.py", "src/app/nested/util.py"]),
        ("src", ["src", "src/app", "src/app/main.py", "src/app/nested/util.py", "src/apple.py"]),
        ("README.md", ["README.md"]),
        ("docs", []),
    ],
)
@pytest.mark.anyio
async def test_execute_tool_list_directory_filters_tree_by_prefix(
    path: str, expected: list[str]
) -> None:
    gh = _FakeGitHubClient(tree=_TREE)

    output = await tools.execute_tool("list_directory", {"path": path}, _context(gh))

    assert json.loads(output) == expected
    assert gh.calls == [
        ("get_json", "/repos/acme/demo/git/trees/deadbeef", {"recursive": "1"}),
    ]


@pytest.mark.parametrize("tool_input", [{"path": "."}, {}])
@pytest.mark.anyio
async def test_execute_tool_list_directory_root_returns_every_tree_path(
    tool_input: dict[str, object],
) -> None:
    gh = _FakeGitHubClient(tree=_TREE)

    output = await tools.execute_tool("list_directory", tool_input, _context(gh))

    assert json.loads(output) == [
        "README.md",
        "src",
        "src/app",
        "src/app/main.py",
        "src/app/nested/util.py",
        "src/apple.py",
        "",
    ]


@pytest.mark.anyio
async def test_execute_tool_list_directory_without_tree_entries_returns_empty_list() -> None:
    gh = _FakeGitHubClient(tree=None)

    output = await tools.execute_tool("list_directory", {"path": "src"}, _context(gh))

    assert json.loads(output) == []


@pytest.mark.anyio
async def test_execute_tool_list_directory_caps_results_at_400_paths() -> None:
    gh = _FakeGitHubClient(tree=[{"path": f"src/f{i}.py"} for i in range(450)])

    output = await tools.execute_tool("list_directory", {"path": "src"}, _context(gh))

    paths = json.loads(output)
    assert len(paths) == 400
    assert paths[0] == "src/f0.py"
    assert paths[-1] == "src/f399.py"


# ---------------------------------------------------------------------------
# search_codebase
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_execute_tool_search_codebase_normalizes_items() -> None:
    output = await tools.execute_tool("search_codebase", {"pattern": "jwt.decode"}, _context())
    data = json.loads(output)
    assert data[0] == {"path": "a.py", "sha": "123"}


@pytest.mark.anyio
async def test_execute_tool_search_codebase_merges_fetched_files_and_github_search() -> None:
    gh = _FakeGitHubClient()
    fetched = {
        "app.py": "import jwt\ntoken = jwt.decode(raw)\nother = jwt.encode(x)",
        "lib/auth.py": "jwt.decode(token, verify=False)",
        "README.md": "no matches here",
    }
    context = _context(gh, fetched_files=fetched)

    output = await tools.execute_tool("search_codebase", {"pattern": r"jwt\.decode\("}, context)

    assert json.loads(output) == [
        {"path": "app.py", "line": 2, "text": "token = jwt.decode(raw)"},
        {"path": "lib/auth.py", "line": 1, "text": "jwt.decode(token, verify=False)"},
        # Repo-wide hits for files the model has not fetched are not suppressed by local hits.
        {"path": "a.py", "sha": "123"},
        {"path": r"jwt\.decode\(.py", "sha": "456"},
    ]
    assert gh.calls == [("search_code", r"jwt\.decode\(", None)]


@pytest.mark.anyio
async def test_execute_tool_search_codebase_dedupes_remote_hits_already_found_locally() -> None:
    gh = _FakeGitHubClient()
    context = _context(gh, fetched_files={"a.py": "needle here"})

    output = await tools.execute_tool("search_codebase", {"pattern": "needle"}, context)

    assert json.loads(output) == [
        {"path": "a.py", "line": 1, "text": "needle here"},
        {"path": "needle.py", "sha": "456"},
    ]


@pytest.mark.anyio
async def test_execute_tool_search_codebase_keeps_local_hits_when_github_search_fails() -> None:
    class _FailingSearchClient(_FakeGitHubClient):
        async def search_code(
            self, _owner: str, _repo: str, pattern: str, _path_glob: str | None = None
        ) -> list[dict]:
            raise RuntimeError("rate limited")

    context = _context(_FailingSearchClient(), fetched_files={"app.py": "needle"})

    output = await tools.execute_tool("search_codebase", {"pattern": "needle"}, context)

    hits = json.loads(output)
    assert hits[0] == {"path": "app.py", "line": 1, "text": "needle"}
    assert "rate limited" in hits[1]["warning"]


@pytest.mark.anyio
async def test_execute_tool_search_codebase_path_glob_filters_fetched_files() -> None:
    fetched = {"app.py": "jwt.decode(a)", "lib/auth.py": "jwt.decode(b)"}
    context = _context(fetched_files=fetched)

    output = await tools.execute_tool(
        "search_codebase", {"pattern": "jwt", "path_glob": "lib/"}, context
    )

    local_hits = [hit for hit in json.loads(output) if "line" in hit]
    assert local_hits == [{"path": "lib/auth.py", "line": 1, "text": "jwt.decode(b)"}]


@pytest.mark.anyio
async def test_execute_tool_search_codebase_truncates_long_matching_lines() -> None:
    context = _context(fetched_files={"app.py": "needle " + "y" * 500})

    output = await tools.execute_tool("search_codebase", {"pattern": "needle"}, context)

    hits = [hit for hit in json.loads(output) if "line" in hit]
    assert len(hits) == 1
    assert len(hits[0]["text"]) == 200


@pytest.mark.anyio
async def test_execute_tool_search_codebase_caps_hits_at_fifty() -> None:
    fetched = {
        "a.py": "\n".join("hit" for _ in range(40)),
        "b.py": "\n".join("hit" for _ in range(40)),
        "c.py": "hit",
    }
    context = _context(fetched_files=fetched)

    output = await tools.execute_tool("search_codebase", {"pattern": "hit"}, context)

    hits = [hit for hit in json.loads(output) if "line" in hit]
    assert len(hits) == 50
    assert {hit["path"] for hit in hits} == {"a.py", "b.py"}


@pytest.mark.anyio
async def test_execute_tool_search_codebase_invalid_regex_returns_error_json() -> None:
    context = _context(fetched_files={"app.py": "content"})

    output = await tools.execute_tool("search_codebase", {"pattern": "(unclosed"}, context)

    data = json.loads(output)
    assert set(data) == {"error"}
    assert data["error"].startswith("invalid regex:")
    assert tools.tool_result_succeeded(output) is True


@pytest.mark.anyio
async def test_execute_tool_search_codebase_falls_back_to_github_when_no_fetched_files() -> None:
    gh = _FakeGitHubClient()
    context = _context(gh, fetched_files={})

    output = await tools.execute_tool(
        "search_codebase", {"pattern": "jwt", "path_glob": "src/"}, context
    )

    assert json.loads(output) == [
        {"path": "a.py", "sha": "123"},
        {"path": "jwt.py", "sha": "456"},
    ]
    assert gh.calls == [("search_code", "jwt", "src/")]


# ---------------------------------------------------------------------------
# get_file_history
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_execute_tool_get_file_history_normalizes_commits() -> None:
    output = await tools.execute_tool("get_file_history", {"path": "app.py"}, _context())
    data = json.loads(output)
    assert data[0]["sha"] == "123"
    assert data[0]["message"] == "feat: update"


@pytest.mark.anyio
async def test_execute_tool_get_file_history_tolerates_missing_commit_payload() -> None:
    gh = _FakeGitHubClient()

    output = await tools.execute_tool("get_file_history", {"path": "src/app.py"}, _context(gh))

    assert json.loads(output) == [
        {"sha": "123", "message": "feat: update"},
        {"sha": "456", "message": "fix: bug"},
        {"sha": "789", "message": None},
    ]
    assert gh.calls == [("get_file_history", "src/app.py")]


# ---------------------------------------------------------------------------
# lookup_dependency
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_execute_tool_lookup_dependency_posts_osv_query_and_returns_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"vulns": [{"id": "GHSA-xxxx", "summary": "Prototype pollution"}]}
    seen = _patch_osv_transport(monkeypatch, lambda _request: httpx.Response(200, json=body))

    output = await tools.execute_tool(
        "lookup_dependency",
        {"ecosystem": "npm", "package": "lodash", "version": "4.17.20"},
        _context(),
    )

    assert json.loads(output) == body
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert str(seen[0].url) == OSV_QUERY_URL
    assert json.loads(seen[0].content) == {
        "package": {"name": "lodash", "ecosystem": "npm"},
        "version": "4.17.20",
    }


@pytest.mark.anyio
async def test_execute_tool_lookup_dependency_maps_ecosystem_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch_osv_transport(monkeypatch, lambda _request: httpx.Response(200, json={}))

    output = await tools.execute_tool(
        "lookup_dependency",
        {"ecosystem": "crates.io", "package": "serde_json", "version": "1.0.0+build.1"},
        _context(),
    )

    assert output == "{}"
    assert json.loads(seen[0].content)["package"]["ecosystem"] == "crates.io"


@pytest.mark.parametrize(
    ("tool_input", "expected_error"),
    [
        ({"ecosystem": "npm", "package": "bad name!", "version": "1.0.0"}, "invalid package name"),
        ({"ecosystem": "npm", "package": "../etc", "version": "1.0.0"}, "invalid package name"),
        ({"ecosystem": "PyPI", "package": "", "version": "1.0.0"}, "invalid package name"),
        ({"ecosystem": "PyPI", "package": "requests", "version": "1.0 || 2"}, "invalid version"),
        ({"ecosystem": "PyPI", "package": "requests", "version": "9" * 51}, "invalid version"),
    ],
)
@pytest.mark.anyio
async def test_execute_tool_lookup_dependency_rejects_invalid_input_without_network(
    monkeypatch: pytest.MonkeyPatch,
    tool_input: dict[str, object],
    expected_error: str,
) -> None:
    seen = _patch_osv_transport(monkeypatch, lambda _request: httpx.Response(200, json={}))

    output = await tools.execute_tool("lookup_dependency", tool_input, _context())

    assert json.loads(output) == {"error": expected_error}
    assert seen == []


@pytest.mark.anyio
async def test_execute_tool_lookup_dependency_unknown_ecosystem_returns_failure_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch_osv_transport(monkeypatch, lambda _request: httpx.Response(200, json={}))

    output = await tools.execute_tool(
        "lookup_dependency",
        {"ecosystem": "RubyGems", "package": "rails", "version": "7.0.0"},
        _context(),
    )

    assert output.startswith("Tool lookup_dependency failed:")
    assert seen == []


@pytest.mark.anyio
async def test_execute_tool_lookup_dependency_http_error_returns_failure_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_osv_transport(monkeypatch, lambda _request: httpx.Response(503, text="unavailable"))

    output = await tools.execute_tool(
        "lookup_dependency",
        {"ecosystem": "PyPI", "package": "requests", "version": "2.31.0"},
        _context(),
    )

    assert output.startswith("Tool lookup_dependency failed:")
    assert "503" in output
    assert tools.tool_result_succeeded(output) is False


# ---------------------------------------------------------------------------
# path validation / error contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_name",
    ["fetch_file_content", "read_file_range", "list_directory", "get_file_history"],
)
@pytest.mark.parametrize(
    "bad_path", ["../x", "src/../../etc/passwd", "/etc/passwd", "..\\x", "   "]
)
@pytest.mark.anyio
async def test_execute_tool_rejects_unsafe_paths(tool_name: str, bad_path: str) -> None:
    gh = _FakeGitHubClient(tree=_TREE)
    tool_input: dict[str, object] = {"path": bad_path, "start_line": 1, "end_line": 1}

    output = await tools.execute_tool(tool_name, tool_input, _context(gh))

    assert output == f"Tool {tool_name} failed: invalid path"
    assert gh.calls == []


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


@pytest.mark.anyio
async def test_execute_tool_missing_required_input_returns_failure_string() -> None:
    output = await tools.execute_tool("fetch_file_content", {}, _context())

    assert output.startswith("Tool fetch_file_content failed:")
    assert tools.tool_result_succeeded(output) is False


# ---------------------------------------------------------------------------
# offline_tool_executor short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_execute_tool_offline_executor_short_circuits_github_access() -> None:
    recorded: list[tuple[str, dict[str, object]]] = []

    async def _offline(name: str, tool_input: dict[str, object], ctx: dict[str, object]) -> str:
        recorded.append((name, tool_input))
        assert ctx["owner"] == "acme"
        return f"offline:{name}"

    context: dict[str, object] = {
        "owner": "acme",
        "repo": "demo",
        "head_sha": "deadbeef",
        "offline_tool_executor": _offline,
    }

    output = await tools.execute_tool("fetch_file_content", {"path": "../escape"}, context)

    assert output == "offline:fetch_file_content"
    assert recorded == [("fetch_file_content", {"path": "../escape"})]
    assert "fetched_files" not in context


@pytest.mark.anyio
async def test_execute_tool_offline_executor_output_is_truncated() -> None:
    async def _offline(_name: str, _tool_input: dict[str, object], _ctx: dict[str, object]) -> str:
        return "z" * (tools.MAX_TOOL_RESULT_CHARS * 2)

    context: dict[str, object] = {"offline_tool_executor": _offline}

    output = await tools.execute_tool("search_codebase", {"pattern": "z"}, context)

    assert output.endswith("\n...truncated")
    assert len(output) == tools.MAX_TOOL_RESULT_CHARS + len("\n...truncated")


@pytest.mark.anyio
async def test_execute_tool_ignores_non_callable_offline_executor() -> None:
    context = _context(offline_tool_executor="not callable")

    output = await tools.execute_tool("fetch_file_content", {"path": "app.py"}, context)

    assert output == "content:app.py"


# ---------------------------------------------------------------------------
# tool_result_succeeded / result truncation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ("content:app.py", True),
        ("[]", True),
        ('{"error": "invalid regex: missing )"}', True),
        ("Tool output: " + "a" * 100 + " failed: later", True),
        ("", False),
        ("   \n", False),
        ("Unknown tool: nope", False),
        ("Tool fetch_file_content failed: boom", False),
        ("  Tool read_file_range failed: invalid path", False),
    ],
)
def test_tool_result_succeeded_classifies_outputs(result: str, expected: bool) -> None:
    assert tools.tool_result_succeeded(result) is expected


def test_truncate_tool_result_leaves_short_output_untouched() -> None:
    text = "x" * tools.MAX_TOOL_RESULT_CHARS

    assert tools._truncate_tool_result(text) is text
    assert tools._truncate_tool_result("") == ""


def test_truncate_tool_result_appends_marker_beyond_cap() -> None:
    text = "x" * (tools.MAX_TOOL_RESULT_CHARS + 1)

    truncated = tools._truncate_tool_result(text)

    assert truncated == "x" * tools.MAX_TOOL_RESULT_CHARS + "\n...truncated"
