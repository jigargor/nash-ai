import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.agent.normalization import normalize_file_content
from app.github.client import GitHubClient
from app.observability.deepeval_tracing import observe_span

TOOLS = [
    {
        "name": "fetch_file_content",
        "description": "Fetch the full content of a file at the PR's head commit.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "read_file_range",
        "description": "Read a line range from a file at the PR's head commit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path", "start_line", "end_line"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files under a directory using GitHub git trees at the PR head SHA.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_codebase",
        "description": "Search for a pattern across the codebase. Returns file paths and matching lines.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path_glob": {"type": "string"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "get_file_history",
        "description": "Get the last 10 commit messages that modified a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "lookup_dependency",
        "description": "Check a package@version for known vulnerabilities via OSV.dev.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ecosystem": {
                    "type": "string",
                    "enum": ["npm", "PyPI", "Go", "Maven", "crates.io"],
                },
                "package": {"type": "string"},
                "version": {"type": "string"},
            },
            "required": ["ecosystem", "package", "version"],
        },
    },
]

OSV_ECOSYSTEM_MAP = {
    "npm": "npm",
    "PyPI": "PyPI",
    "Go": "Go",
    "Maven": "Maven",
    "crates.io": "crates.io",
}

OfflineToolExecutor = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[str]]


def _normalize_repo_path(raw_path: object) -> str:
    path = str(raw_path).strip().replace("\\", "/")
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise ValueError("invalid path")
    return path


MAX_TOOL_RESULT_CHARS = 20_000 * 4  # ~20k tokens, conservative char cap


def tool_result_succeeded(result: str) -> bool:
    text = (result or "").strip()
    if not text:
        return False
    if text.startswith("Unknown tool:"):
        return False
    if text.startswith("Tool ") and " failed:" in text[:80]:
        return False
    return True


def _truncate_tool_result(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + "\n...truncated"


@observe_span("tool")
async def execute_tool(name: str, tool_input: dict[str, Any], context: dict[str, Any]) -> str:
    try:
        maybe_offline_executor = context.get("offline_tool_executor")
        if callable(maybe_offline_executor):
            offline_executor = maybe_offline_executor
            return _truncate_tool_result(await offline_executor(name, tool_input, context))

        gh: GitHubClient = context["github_client"]
        owner: str = context["owner"]
        repo: str = context["repo"]
        head_sha: str = context["head_sha"]

        if name == "fetch_file_content":
            path = _normalize_repo_path(tool_input["path"])
            normalized_content = normalize_file_content(
                await gh.get_file_content(owner, repo, path, head_sha)
            )
            fetched_files = context.setdefault("fetched_files", {})
            if isinstance(fetched_files, dict):
                fetched_files[path] = normalized_content
            return _truncate_tool_result(normalized_content)

        if name == "read_file_range":
            path = _normalize_repo_path(tool_input["path"])
            start_line = int(tool_input["start_line"])
            end_line = int(tool_input["end_line"])
            fetched_files = context.setdefault("fetched_files", {})
            if isinstance(fetched_files, dict) and path in fetched_files:
                content = str(fetched_files[path])
            else:
                content = normalize_file_content(
                    await gh.get_file_content(owner, repo, path, head_sha)
                )
                if isinstance(fetched_files, dict):
                    fetched_files[path] = content
            lines = content.split("\n")
            start = max(1, start_line)
            end = min(len(lines), end_line)
            numbered = "\n".join(f"{idx}|{lines[idx - 1]}" for idx in range(start, end + 1))
            return _truncate_tool_result(numbered)

        if name == "list_directory":
            prefix = _normalize_repo_path(tool_input.get("path") or ".")
            if prefix in {".", ""}:
                prefix = ""
            tree = await gh.get_json(
                f"/repos/{owner}/{repo}/git/trees/{head_sha}",
                params={"recursive": "1"},
            )
            entries = tree.get("tree") if isinstance(tree, dict) else None
            paths: list[str] = []
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    path = str(entry.get("path") or "")
                    if prefix and not (path == prefix or path.startswith(prefix.rstrip("/") + "/")):
                        continue
                    paths.append(path)
            return _truncate_tool_result(json.dumps(paths[:400]))

        if name == "search_codebase":
            pattern = tool_input["pattern"]
            path_glob = tool_input.get("path_glob")
            fetched_files = context.get("fetched_files")
            if isinstance(fetched_files, dict) and fetched_files:
                import re as _re

                try:
                    regex = _re.compile(str(pattern))
                except _re.error as exc:
                    return json.dumps({"error": f"invalid regex: {exc}"})
                hits: list[dict[str, object]] = []
                for file_path, content in fetched_files.items():
                    if path_glob and str(path_glob) not in str(file_path):
                        continue
                    for idx, line in enumerate(str(content).split("\n"), start=1):
                        if regex.search(line):
                            hits.append({"path": file_path, "line": idx, "text": line[:200]})
                            if len(hits) >= 50:
                                break
                    if len(hits) >= 50:
                        break
                return _truncate_tool_result(json.dumps(hits))
            items = await gh.search_code(owner, repo, pattern, path_glob)
            normalized = [{"path": item.get("path"), "sha": item.get("sha")} for item in items]
            return _truncate_tool_result(json.dumps(normalized))

        if name == "get_file_history":
            path = _normalize_repo_path(tool_input["path"])
            commits = await gh.get_file_history(owner, repo, path)
            normalized = [
                {
                    "sha": commit.get("sha"),
                    "message": (commit.get("commit") or {}).get("message"),
                }
                for commit in commits
            ]
            return _truncate_tool_result(json.dumps(normalized))

        if name == "lookup_dependency":
            ecosystem = OSV_ECOSYSTEM_MAP[tool_input["ecosystem"]]
            package = tool_input["package"]
            version = tool_input["version"]
            if not re.match(r"^[a-zA-Z0-9._\-]{1,200}$", package):
                return json.dumps({"error": "invalid package name"})
            if not re.match(r"^[a-zA-Z0-9._\-+]{1,50}$", version):
                return json.dumps({"error": "invalid version"})
            payload = {
                "package": {"name": package, "ecosystem": ecosystem},
                "version": version,
            }
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post("https://api.osv.dev/v1/query", json=payload)
                response.raise_for_status()
                return _truncate_tool_result(response.text)

        return f"Unknown tool: {name}"
    except Exception as exc:
        return f"Tool {name} failed: {exc}"
