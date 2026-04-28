from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.agent.finalize import finalize_review
from app.agent.loop import run_agent
from app.agent.review_config import DEFAULT_MODEL_NAME, ModelProvider
from app.agent.schema import ReviewResult


def _normalize_path(raw_path: object) -> str:
    path = str(raw_path).strip().replace("\\", "/")
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise ValueError("invalid path")
    return path


def _safe_repo_from_context(context_payload: dict[str, Any]) -> tuple[str, str]:
    repo = str(context_payload.get("repo") or "offline/offline").strip()
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return owner or "offline", name or "offline"
    return "offline", repo or "offline"


def _build_offline_tool_executor(
    files: dict[str, str],
) -> Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[str]]:
    normalized_files: dict[str, str] = {
        _normalize_path(path): content for path, content in files.items() if isinstance(content, str)
    }

    async def _run(name: str, tool_input: dict[str, Any], context: dict[str, Any]) -> str:
        if name == "fetch_file_content":
            path = _normalize_path(tool_input["path"])
            content = normalized_files.get(path)
            if content is None:
                return f"Tool {name} failed: file not found: {path}"
            fetched_files = context.setdefault("fetched_files", {})
            if isinstance(fetched_files, dict):
                fetched_files[path] = content
            return content

        if name == "search_codebase":
            pattern = str(tool_input.get("pattern") or "")
            path_glob_raw = tool_input.get("path_glob")
            path_glob = str(path_glob_raw).strip().replace("\\", "/") if path_glob_raw else ""
            try:
                regex = re.compile(pattern)
            except re.error as exc:
                return json.dumps({"error": f"invalid regex pattern: {exc}"})
            results: list[dict[str, str]] = []
            for file_path, content in normalized_files.items():
                if path_glob and path_glob not in file_path:
                    continue
                if regex.search(content):
                    results.append({"path": file_path, "sha": "offline-fixture"})
            return json.dumps(results)

        if name == "get_file_history":
            return json.dumps([])

        if name == "lookup_dependency":
            return json.dumps({"warning": "lookup_dependency disabled in offline eval harness"})

        return f"Unknown tool: {name}"

    return _run


def _load_case_payload(case_dir: Path) -> dict[str, Any]:
    snapshot_path = case_dir / "snapshot.json"
    if snapshot_path.exists():
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    context_path = case_dir / "context.json"
    context_payload = {}
    if context_path.exists():
        loaded = json.loads(context_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            context_payload = loaded
    owner, repo = _safe_repo_from_context(context_payload)
    diff_path = case_dir / "diff.patch"
    diff_text = diff_path.read_text(encoding="utf-8") if diff_path.exists() else ""
    files_payload = context_payload.get("files", {})
    files = files_payload if isinstance(files_payload, dict) else {}
    prompt_dir = case_dir / "prompts"
    system_prompt_path = prompt_dir / "system.txt"
    user_prompt_path = prompt_dir / "user.txt"
    system_prompt = (
        system_prompt_path.read_text(encoding="utf-8")
        if system_prompt_path.exists()
        else (
            "You are a strict code review agent. Review the supplied repository context and "
            "return only high-signal findings."
        )
    )
    if user_prompt_path.exists():
        user_prompt = user_prompt_path.read_text(encoding="utf-8")
    else:
        file_list = "\n".join(f"- {path}" for path in list(files.keys())[:80])
        user_prompt = (
            f"Repository: {owner}/{repo}\n"
            f"Head SHA: {context_payload.get('head_sha', 'offline-sha')}\n\n"
            f"Diff:\n{diff_text}\n\n"
            f"Available files:\n{file_list}\n"
        )
    return {
        "review_id": -1,
        "pr_metadata": {
            "owner": owner,
            "repo": repo,
            "pr_number": 0,
            "head_sha": str(context_payload.get("head_sha") or "offline-sha"),
            "title": str(context_payload.get("title") or f"offline-eval-{case_dir.name}"),
        },
        "diff_text": diff_text,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "fetched_files": files,
    }


async def replay_case_directory_to_review_result(
    case_dir: Path,
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    provider: ModelProvider = "anthropic",
) -> ReviewResult:
    payload = _load_case_payload(case_dir)
    return await replay_snapshot_to_review_result(payload, model_name=model_name, provider=provider)


async def replay_snapshot_to_review_result(
    snapshot_payload: dict[str, Any],
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    provider: ModelProvider = "anthropic",
) -> ReviewResult:
    pr_metadata_raw = snapshot_payload.get("pr_metadata")
    pr_metadata = pr_metadata_raw if isinstance(pr_metadata_raw, dict) else {}
    owner = str(pr_metadata.get("owner") or "offline")
    repo = str(pr_metadata.get("repo") or "offline")
    head_sha = str(pr_metadata.get("head_sha") or "offline-sha")
    fetched_files_raw = snapshot_payload.get("fetched_files")
    fetched_files = fetched_files_raw if isinstance(fetched_files_raw, dict) else {}
    context: dict[str, Any] = {
        "run_id": f"offline-{owner}-{repo}",
        "review_id": int(snapshot_payload.get("review_id") or -1),
        "installation_id": 0,
        "owner": owner,
        "repo": repo,
        "pr_number": int(pr_metadata.get("pr_number") or 0),
        "head_sha": head_sha,
        "input_tokens": 0,
        "output_tokens": 0,
        "tokens_used": 0,
        "fetched_files": dict(
            (_normalize_path(path), str(content)) for path, content in fetched_files.items()
        ),
        "offline_tool_executor": _build_offline_tool_executor(
            {
                _normalize_path(path): str(content)
                for path, content in fetched_files.items()
                if isinstance(path, str)
            }
        ),
    }
    system_prompt = str(snapshot_payload.get("system_prompt") or "")
    user_prompt = str(snapshot_payload.get("user_prompt") or "")
    if not system_prompt.strip() or not user_prompt.strip():
        raise ValueError("snapshot payload must include non-empty system_prompt and user_prompt")
    messages = await run_agent(
        system_prompt,
        user_prompt,
        context,
        model_name=model_name,
        provider=provider,
    )
    return await finalize_review(
        system_prompt,
        messages,
        context,
        model_name=model_name,
        provider=provider,
    )
