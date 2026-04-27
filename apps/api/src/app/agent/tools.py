import json
import re
from typing import Any

import httpx

from app.agent.normalization import normalize_file_content
from app.github.client import GitHubClient

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


def _normalize_repo_path(raw_path: object) -> str:
    path = str(raw_path).strip().replace("\\", "/")
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise ValueError("invalid path")
    return path


async def execute_tool(name: str, tool_input: dict[str, Any], context: dict[str, Any]) -> str:
    try:
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
            return normalized_content

        if name == "search_codebase":
            pattern = tool_input["pattern"]
            path_glob = tool_input.get("path_glob")
            items = await gh.search_code(owner, repo, pattern, path_glob)
            normalized = [{"path": item.get("path"), "sha": item.get("sha")} for item in items]
            return json.dumps(normalized)

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
            return json.dumps(normalized)

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
                return response.text

        return f"Unknown tool: {name}"
    except Exception as exc:
        return f"Tool {name} failed: {exc}"
