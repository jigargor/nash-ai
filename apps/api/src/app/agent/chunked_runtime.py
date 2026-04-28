import json
from hashlib import sha256
from typing import Any, cast

from pydantic import ValidationError

from app.agent.chunking import ChunkPlan, PlannedChunk
from app.agent.schema import Finding
from app.db.models import Review
from app.db.session import AsyncSessionLocal, set_installation_context


def chunk_repo_segments(chunk_plan: ChunkPlan, chunk: PlannedChunk) -> list[str]:
    files = [entry.path for entry in chunk.files]
    chunk_packages = sorted({entry.touched_package for entry in chunk.files})
    chunk_dep_hints = sorted(
        {hint for entry in chunk.files if (hint := entry.dependency_hint) is not None}
    )
    return [
        "Full changed-file manifest:\n" + "\n".join(chunk_plan.full_manifest),
        "Touched packages: "
        + (", ".join(chunk_plan.touched_packages) if chunk_plan.touched_packages else "none"),
        "Dependency hints: "
        + (", ".join(chunk_plan.dependency_hints) if chunk_plan.dependency_hints else "none"),
        f"Active chunk files ({len(files)}):\n" + "\n".join(files),
        "Active chunk package scope: " + (", ".join(chunk_packages) if chunk_packages else "none"),
        "Active chunk dependency hints: "
        + (", ".join(chunk_dep_hints) if chunk_dep_hints else "none"),
    ]


def render_chunk_diff(files_in_diff: list[Any]) -> str:
    rendered: list[str] = []
    for file in files_in_diff:
        rendered.append(f"diff -- {file.path}")
        for line in file.numbered_lines:
            marker = {"add": "+", "del": "-", "ctx": " "}[line.kind]
            rendered.append(f"{marker}{line.content}")
    return "\n".join(rendered)


def chunk_state_key(context: dict[str, Any]) -> str:
    payload = {
        "repo": context["repo"],
        "pr_number": context["pr_number"],
        "head_sha": context["head_sha"],
        "config_hash": context.get("chunking_config_hash", "default"),
    }
    digest = sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"chunking:{digest}"


async def load_chunk_state(context: dict[str, Any]) -> dict[str, dict[str, object]]:
    installation_id = cast(int, context["installation_id"])
    review_id = cast(int, context["review_id"])
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None or not review.debug_artifacts:
            return {}
        chunking_state = review.debug_artifacts.get("chunking_state")
        if not isinstance(chunking_state, dict):
            return {}
        state = chunking_state.get(chunk_state_key(context))
        if not isinstance(state, dict):
            return {}
        return cast(dict[str, dict[str, object]], state)


def merge_chunk_state_with_plan(
    existing: dict[str, dict[str, object]], plan: ChunkPlan
) -> dict[str, dict[str, object]]:
    merged = dict(existing)
    for chunk in plan.chunks:
        if chunk.chunk_id not in merged:
            merged[chunk.chunk_id] = {"status": "pending", "findings": [], "summary": ""}
    return merged


def chunk_status(state: dict[str, dict[str, object]], chunk_id: str) -> str:
    chunk_state = state.get(chunk_id, {})
    status = chunk_state.get("status")
    return str(status) if isinstance(status, str) else "pending"


def chunk_findings_from_state(state: dict[str, dict[str, object]], chunk_id: str) -> list[Finding]:
    chunk_state = state.get(chunk_id, {})
    findings_raw = chunk_state.get("findings")
    if not isinstance(findings_raw, list):
        return []
    findings: list[Finding] = []
    for entry in findings_raw:
        if not isinstance(entry, dict):
            continue
        try:
            findings.append(Finding.model_validate(entry))
        except ValidationError:
            continue
    return findings


def chunk_summary_from_state(state: dict[str, dict[str, object]], chunk_id: str) -> str:
    summary = state.get(chunk_id, {}).get("summary")
    return str(summary) if isinstance(summary, str) else ""


def set_chunk_state(
    state: dict[str, dict[str, object]],
    chunk_id: str,
    *,
    status: str,
    findings: list[dict[str, object]] | None = None,
    summary: str | None = None,
    estimated_prompt_tokens: int | None = None,
    error: str | None = None,
) -> None:
    chunk_state = state.setdefault(chunk_id, {})
    chunk_state["status"] = status
    if findings is not None:
        chunk_state["findings"] = findings
    if summary is not None:
        chunk_state["summary"] = summary
    if estimated_prompt_tokens is not None:
        chunk_state["estimated_prompt_tokens"] = estimated_prompt_tokens
    if error is not None:
        chunk_state["error"] = error


async def persist_chunk_state(
    context: dict[str, Any], chunk_state: dict[str, dict[str, object]]
) -> None:
    installation_id = cast(int, context["installation_id"])
    review_id = cast(int, context["review_id"])
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            return
        debug_artifacts = dict(review.debug_artifacts or {})
        chunking_state = dict(debug_artifacts.get("chunking_state") or {})
        chunking_state[chunk_state_key(context)] = chunk_state
        debug_artifacts["chunking_state"] = chunking_state
        review.debug_artifacts = debug_artifacts
        await session.commit()
