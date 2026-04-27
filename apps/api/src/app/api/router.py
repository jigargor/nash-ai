import asyncio
import hmac
import json
import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from dataclasses import asdict
from decimal import Decimal
from typing import TypedDict, cast

import yaml
from app.agent.profiler import profile_repo
from app.agent.provider_clients import create_openai_compatible_client, get_provider_api_key
from app.agent.review_config import (
    DEFAULT_MAX_FINDINGS_PER_PR,
    ModelProvider,
    ReviewConfig,
    _normalize_path_patterns,
    _normalize_positive_int,
    _normalize_threshold,
    _parse_budgets,
    _parse_categories,
    _parse_chunking,
    _parse_max_mode,
    _parse_model_config,
    _parse_packaging,
    _parse_severity_threshold,
)
from app.config import settings
from app.db.models import Installation, RepoConfig, Review, ReviewModelAudit
from app.db.session import AsyncSessionLocal, set_installation_context
from app.github.client import GitHubClient
from app.github.utils import safe_fetch_file, split_repo_full_name as _split_repo_full_name
from app.llm.router import resolve_model_for_role
from app.observability import create_async_anthropic_client
from app.queue.connection import require_app_redis
from app.telemetry.finding_outcomes import list_review_finding_outcomes, summarize_finding_outcomes
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def _verify_api_access(x_api_key: str | None = Header(default=None)) -> None:
    if settings.environment.lower() == "production" and not settings.api_access_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="API key auth is not configured"
        )
    if not settings.api_access_key:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_access_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Api-Key"
        )


router = APIRouter(prefix="/api/v1", dependencies=[Depends(_verify_api_access)])


class RepoAccumulator(TypedDict):
    installation_id: int
    repo_full_name: str
    review_count: int
    failed_review_count: int
    total_tokens: int
    estimated_cost_usd: Decimal
    latest_review_id: int
    latest_pr_number: int
    latest_status: str
    last_review_at: datetime


REPO_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
DEFAULT_TEMPLATE_PROMPT = """You generate .codereview.yml configuration files for a PR review agent.
Return ONLY valid YAML (no markdown fences, no explanation).
Optimize for practical defaults: medium-noise, strong correctness/security, bounded cost.
Include keys: confidence_threshold, severity_threshold, categories, review_drafts, max_findings_per_pr,
ignore_paths, model, max_mode, budgets, layered_context_enabled, partial_review_mode_enabled,
partial_review_changed_lines_threshold, summarization_enabled, max_summary_calls_per_review,
generated_paths, vendor_paths, chunking.
"""


def _validate_repo_segment(segment: str, label: str) -> str:
    normalized = segment.strip()
    if not normalized or not REPO_SEGMENT_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {label}")
    return normalized


def _extract_yaml_payload(raw_text: str) -> str:
    candidate = raw_text.strip()
    fenced = re.search(r"```ya?ml\s*(.*?)```", candidate, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    return candidate


def _normalize_generated_config(raw_payload: dict[str, object]) -> ReviewConfig:
    confidence_threshold = _normalize_threshold(raw_payload.get("confidence_threshold"))
    severity_threshold = _parse_severity_threshold(raw_payload.get("severity_threshold"))
    categories = _parse_categories(raw_payload.get("categories"))
    ignore_paths = _normalize_path_patterns(raw_payload.get("ignore_paths"))
    review_drafts = bool(raw_payload.get("review_drafts", False))
    max_findings_per_pr = _normalize_positive_int(
        raw_payload.get("max_findings_per_pr"), DEFAULT_MAX_FINDINGS_PER_PR
    )
    prompt_additions_raw = raw_payload.get("prompt_additions")
    prompt_additions = (
        str(prompt_additions_raw).strip() if isinstance(prompt_additions_raw, str) else None
    )
    if prompt_additions == "":
        prompt_additions = None
    model = _parse_model_config(raw_payload.get("model"))
    max_mode = _parse_max_mode(raw_payload.get("max_mode"))
    budgets = _parse_budgets(raw_payload.get("budgets"))
    packaging = _parse_packaging(raw_payload)
    chunking = _parse_chunking(raw_payload.get("chunking"))
    return ReviewConfig(
        confidence_threshold=confidence_threshold,
        severity_threshold=severity_threshold,
        categories=categories,
        ignore_paths=ignore_paths,
        review_drafts=review_drafts,
        max_findings_per_pr=max_findings_per_pr,
        prompt_additions=prompt_additions,
        model=model,
        max_mode=max_mode,
        budgets=budgets,
        packaging=packaging,
        chunking=chunking,
    )


def _serialize_review_config_yaml(config: ReviewConfig) -> str:
    payload = asdict(config)
    payload["model"]["input_per_1m_usd"] = float(config.model.input_per_1m_usd)
    payload["model"]["output_per_1m_usd"] = float(config.model.output_per_1m_usd)
    payload["budgets"] = config.budgets.model_dump(mode="json")
    payload["chunking"] = asdict(config.chunking)
    return yaml.safe_dump(payload, sort_keys=False)


async def _resolve_repo_head_sha(gh: GitHubClient, owner: str, repo: str) -> str:
    repo_payload = await gh.get_json(f"/repos/{owner}/{repo}")
    default_branch = str(repo_payload.get("default_branch") or "main")
    branch_payload = await gh.get_json(f"/repos/{owner}/{repo}/branches/{default_branch}")
    commit_obj = branch_payload.get("commit")
    if isinstance(commit_obj, dict):
        sha = commit_obj.get("sha")
        if isinstance(sha, str) and sha.strip():
            return sha
    return default_branch


async def _generate_yaml_with_model(
    *,
    owner: str,
    repo: str,
    frameworks: list[str],
    model_provider: ModelProvider,
    model_name: str,
) -> str:
    user_prompt = (
        f"Repository: {owner}/{repo}\n"
        f"Detected frameworks: {', '.join(frameworks) if frameworks else 'unknown'}\n"
        "Generate a balanced .codereview.yml suitable for this repository."
    )
    if model_provider == "anthropic":
        client = create_async_anthropic_client(get_provider_api_key("anthropic"))
        anthropic_response = await client.messages.create(
            model=model_name,
            max_tokens=2200,
            temperature=0,
            system=[{"type": "text", "text": DEFAULT_TEMPLATE_PROMPT}],
            messages=[{"role": "user", "content": user_prompt}],
        )
        text_blocks = [
            str(getattr(block, "text", "")).strip()
            for block in anthropic_response.content
            if getattr(block, "type", "") == "text"
        ]
        raw_output = "\n".join(block for block in text_blocks if block)
        if raw_output:
            return raw_output
        raise RuntimeError("Anthropic generation returned empty output")

    if model_provider not in {"openai", "gemini"}:
        raise RuntimeError(
            f"Unsupported provider for OpenAI-compatible generation: {model_provider}"
        )
    openai_client = create_openai_compatible_client(model_provider)
    openai_response = await openai_client.chat.completions.create(
        model=model_name,
        temperature=0,
        messages=[
            {"role": "system", "content": DEFAULT_TEMPLATE_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    if not openai_response.choices:
        raise RuntimeError("OpenAI-compatible generation returned no choices")
    return str(openai_response.choices[0].message.content or "").strip()


async def _list_installation_rows(
    session: AsyncSession,
    *,
    active_only: bool = True,
    limit: int = 100,
) -> list[Installation]:
    stmt = select(Installation).order_by(Installation.installed_at.desc()).limit(limit)
    if active_only:
        stmt = stmt.where(Installation.suspended_at.is_(None))
    rows = await session.scalars(stmt)
    return list(rows)


def _review_list_item(review: Review) -> dict[str, object]:
    return {
        "id": int(review.id),
        "installation_id": int(review.installation_id),
        "repo_full_name": review.repo_full_name,
        "pr_number": int(review.pr_number),
        "status": review.status,
        "model_provider": review.model_provider,
        "model": review.model,
        "tokens_used": int(review.tokens_used) if review.tokens_used is not None else None,
        "cost_usd": str(review.cost_usd) if review.cost_usd is not None else None,
        "created_at": review.created_at.isoformat(),
        "completed_at": review.completed_at.isoformat()
        if review.completed_at is not None
        else None,
    }


@router.get("/installations")
async def list_installations(
    active_only: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict[str, object]]:
    async with AsyncSessionLocal() as session:
        installations = await _list_installation_rows(session, active_only=active_only, limit=limit)
        return [
            {
                "installation_id": int(item.installation_id),
                "account_login": item.account_login,
                "account_type": item.account_type,
                "active": item.suspended_at is None,
                "suspended_at": item.suspended_at.isoformat()
                if item.suspended_at is not None
                else None,
            }
            for item in installations
        ]


@router.get("/repos")
async def list_repos(
    installation_id: int | None = Query(default=None, ge=1),
    active_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, object]]:
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            installation_ids = [installation_id]
        else:
            installations = await _list_installation_rows(
                session, active_only=active_only, limit=100
            )
            installation_ids = [int(item.installation_id) for item in installations]

        repos: dict[tuple[int, str], RepoAccumulator] = {}
        for current_installation_id in installation_ids:
            await set_installation_context(session, current_installation_id)
            rows = await session.scalars(
                select(Review)
                .where(Review.installation_id == current_installation_id)
                .order_by(Review.created_at.desc())
                .limit(limit)
            )
            for review in rows:
                key = (int(review.installation_id), review.repo_full_name)
                repo = repos.setdefault(
                    key,
                    {
                        "installation_id": int(review.installation_id),
                        "repo_full_name": review.repo_full_name,
                        "review_count": 0,
                        "failed_review_count": 0,
                        "total_tokens": 0,
                        "estimated_cost_usd": Decimal("0"),
                        "latest_review_id": int(review.id),
                        "latest_pr_number": int(review.pr_number),
                        "latest_status": review.status,
                        "last_review_at": review.created_at,
                    },
                )
                repo["review_count"] += 1
                if review.status == "failed":
                    repo["failed_review_count"] += 1
                repo["total_tokens"] += int(review.tokens_used or 0)
                repo["estimated_cost_usd"] += Decimal(str(review.cost_usd or 0))

                if review.created_at >= repo["last_review_at"]:
                    repo["latest_review_id"] = int(review.id)
                    repo["latest_pr_number"] = int(review.pr_number)
                    repo["latest_status"] = review.status
                    repo["last_review_at"] = review.created_at

        repo_generation_state: dict[tuple[int, str], tuple[bool, str | None]] = {}
        for current_installation_id in installation_ids:
            await set_installation_context(session, current_installation_id)
            repo_rows = await session.scalars(
                select(RepoConfig).where(RepoConfig.installation_id == current_installation_id)
            )
            for row in repo_rows:
                key = (int(row.installation_id), row.repo_full_name)
                repo_generation_state[key] = (
                    row.ai_generated_at is not None,
                    row.ai_generated_at.isoformat() if row.ai_generated_at is not None else None,
                )

        sorted_repos = sorted(
            repos.values(),
            key=lambda item: item["last_review_at"],
            reverse=True,
        )
        return [
            {
                **repo,
                "ai_template_generated": repo_generation_state.get(
                    (repo["installation_id"], repo["repo_full_name"]),
                    (False, None),
                )[0],
                "ai_template_generated_at": repo_generation_state.get(
                    (repo["installation_id"], repo["repo_full_name"]),
                    (False, None),
                )[1],
                "estimated_cost_usd": str(repo["estimated_cost_usd"]),
                "last_review_at": repo["last_review_at"].isoformat(),
            }
            for repo in sorted_repos[:limit]
        ]


@router.get("/repos/{owner}/{repo}/codereview-config")
async def get_repo_codereview_config(
    owner: str,
    repo: str,
    installation_id: int = Query(..., ge=1),
) -> dict[str, object]:
    owner = _validate_repo_segment(owner, "repository owner")
    repo = _validate_repo_segment(repo, "repository name")
    gh = await GitHubClient.for_installation(installation_id)
    raw = await safe_fetch_file(gh, owner, repo, ".codereview.yml", "HEAD")
    config_json: dict[str, object] | None = None
    if raw is not None:
        try:
            parsed = yaml.safe_load(raw)
            if isinstance(parsed, dict):
                config_json = parsed
        except yaml.YAMLError:
            pass
    return {"found": raw is not None, "yaml_text": raw, "config_json": config_json}


@router.post("/repos/{owner}/{repo}/codereview-template/generate")
async def generate_repo_codereview_template(
    owner: str,
    repo: str,
    installation_id: int = Query(..., ge=1),
) -> dict[str, object]:
    if not settings.has_llm_api_key_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No LLM API key configured (ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY)",
        )
    owner_normalized = _validate_repo_segment(owner, "repository owner")
    repo_normalized = _validate_repo_segment(repo, "repository name")
    repo_full_name = f"{owner_normalized}/{repo_normalized}"

    gh = await GitHubClient.for_installation(installation_id)
    ref = await _resolve_repo_head_sha(gh, owner_normalized, repo_normalized)
    repo_profile = await profile_repo(gh, owner_normalized, repo_normalized, ref)

    resolution = resolve_model_for_role(ReviewConfig(), "config_generator")
    provider = resolution.provider
    model_name = resolution.model

    raw_yaml = await _generate_yaml_with_model(
        owner=owner_normalized,
        repo=repo_normalized,
        frameworks=repo_profile.frameworks,
        model_provider=provider,
        model_name=model_name,
    )
    payload_text = _extract_yaml_payload(raw_yaml)
    try:
        parsed_payload = yaml.safe_load(payload_text)
    except yaml.YAMLError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Generated config was malformed YAML.",
        ) from None
    if not isinstance(parsed_payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Generated config was not valid YAML object.",
        )
    normalized_config = _normalize_generated_config(parsed_payload)
    normalized_yaml = _serialize_review_config_yaml(normalized_config)

    try:
        normalized_payload = yaml.safe_load(normalized_yaml)
    except yaml.YAMLError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Normalized YAML serialization failed.",
        ) from None
    if not isinstance(normalized_payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Normalized YAML serialization failed."
        )
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        try:
            row = await session.scalar(
                select(RepoConfig)
                .where(
                    RepoConfig.installation_id == installation_id,
                    RepoConfig.repo_full_name == repo_full_name,
                )
                .with_for_update()
            )
            if row is None:
                row = RepoConfig(
                    installation_id=installation_id,
                    repo_full_name=repo_full_name,
                )
                session.add(row)
                await session.flush()
            if row.ai_generated_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="AI .codereview.yml can only be generated once per repository.",
                )
            row.config_yaml = cast(dict[str, object], normalized_payload)
            row.ai_generated_yaml = normalized_yaml
            row.ai_generated_at = now
            row.updated_at = now
            await session.commit()
        except HTTPException:
            await session.rollback()
            raise
        except IntegrityError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="AI .codereview.yml generation is already completed or in progress for this repository.",
            ) from None
    return {
        "repo_full_name": repo_full_name,
        "generated_once": True,
        "generated_at": now.isoformat(),
        "provider": provider,
        "model": model_name,
        "config_yaml_text": normalized_yaml,
    }


@router.get("/reviews")
async def list_reviews(
    installation_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, object]]:
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
            reviews = await session.scalars(
                select(Review)
                .where(Review.installation_id == installation_id)
                .order_by(Review.created_at.desc())
                .limit(limit)
            )
            return [_review_list_item(review) for review in reviews]

        installations = await _list_installation_rows(session, active_only=True, limit=100)
        all_reviews: list[Review] = []
        for installation in installations:
            await set_installation_context(session, int(installation.installation_id))
            reviews = await session.scalars(
                select(Review)
                .where(Review.installation_id == int(installation.installation_id))
                .order_by(Review.created_at.desc())
                .limit(limit)
            )
            all_reviews.extend(reviews)

        all_reviews.sort(key=lambda review: review.created_at, reverse=True)
        return [_review_list_item(review) for review in all_reviews[:limit]]


@router.get("/reviews/{review_id}")
async def get_review(
    review_id: int, installation_id: int | None = Query(default=None, ge=1)
) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
        if installation_id is None:
            installation_id = int(review.installation_id)
            await set_installation_context(session, installation_id)
        elif int(review.installation_id) != installation_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="installation_id mismatch"
            )

        return {
            "id": int(review.id),
            "installation_id": int(review.installation_id),
            "repo_full_name": review.repo_full_name,
            "pr_number": int(review.pr_number),
            "pr_head_sha": review.pr_head_sha,
            "status": review.status,
            "model_provider": review.model_provider,
            "model": review.model,
            "findings": review.findings,
            "tokens_used": int(review.tokens_used) if review.tokens_used is not None else None,
            "cost_usd": str(review.cost_usd) if review.cost_usd is not None else None,
            "created_at": review.created_at.isoformat(),
            "completed_at": review.completed_at.isoformat()
            if review.completed_at is not None
            else None,
            "finding_outcomes": await list_review_finding_outcomes(
                int(review.id), int(review.installation_id)
            ),
            "debug_artifacts": review.debug_artifacts,
        }


@router.get("/reviews/{review_id}/outcomes")
async def get_review_outcomes(
    review_id: int,
    installation_id: int | None = Query(default=None, ge=1),
) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
        if installation_id is None:
            installation_id = int(review.installation_id)
            await set_installation_context(session, installation_id)
        elif int(review.installation_id) != installation_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="installation_id mismatch"
            )

        return {
            "review_id": int(review.id),
            "finding_outcomes": await list_review_finding_outcomes(
                int(review.id), int(review.installation_id)
            ),
        }


@router.get("/reviews/{review_id}/model-audits")
async def get_review_model_audits(
    review_id: int,
    installation_id: int | None = Query(default=None, ge=1),
) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
        if installation_id is None:
            installation_id = int(review.installation_id)
            await set_installation_context(session, installation_id)
        elif int(review.installation_id) != installation_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="installation_id mismatch"
            )
        rows = await session.scalars(
            select(ReviewModelAudit)
            .where(ReviewModelAudit.review_id == review_id)
            .order_by(ReviewModelAudit.created_at.asc())
        )
        audits = [
            {
                "id": int(row.id),
                "run_id": row.run_id,
                "stage": row.stage,
                "provider": row.provider,
                "model": row.model,
                "prompt_version": row.prompt_version,
                "input_tokens": int(row.input_tokens),
                "output_tokens": int(row.output_tokens),
                "total_tokens": int(row.total_tokens),
                "findings_count": int(row.findings_count)
                if row.findings_count is not None
                else None,
                "accepted_findings_count": (
                    int(row.accepted_findings_count)
                    if row.accepted_findings_count is not None
                    else None
                ),
                "conflict_score": int(row.conflict_score)
                if row.conflict_score is not None
                else None,
                "decision": row.decision,
                "stage_duration_ms": int(row.stage_duration_ms)
                if row.stage_duration_ms is not None
                else None,
                "metadata_json": row.metadata_json,
                "created_at": row.created_at.isoformat() if row.created_at is not None else None,
            }
            for row in rows
        ]
    return {"review_id": review_id, "model_audits": audits}


@router.get("/telemetry/outcomes/summary")
async def get_outcome_summary(
    installation_id: int | None = Query(default=None, ge=1),
    repo_full_name: str | None = Query(default=None),
) -> dict[str, object]:
    summary = await summarize_finding_outcomes(
        installation_id=installation_id,
        repo_full_name=repo_full_name,
    )
    return {
        "installation_id": installation_id,
        "repo_full_name": repo_full_name,
        **summary,
    }


@router.post("/reviews/{review_id}/rerun")
async def rerun_review(
    request: Request,
    review_id: int,
    installation_id: int | None = Query(default=None, ge=1),
    x_user_github_id: int | None = Header(default=None),
) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
        if installation_id is None:
            installation_id = int(review.installation_id)
            await set_installation_context(session, installation_id)
        elif int(review.installation_id) != installation_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="installation_id mismatch"
            )

        if not settings.has_llm_api_key_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No LLM API key configured (ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY)",
            )

        owner, repo = _split_repo_full_name(review.repo_full_name)
        redis = require_app_redis(request)
        job = await redis.enqueue_job(
            "review_pr",
            int(review.id),
            int(review.installation_id),
            owner,
            repo,
            int(review.pr_number),
            review.pr_head_sha,
            user_github_id=x_user_github_id,
        )
        review.status = "queued"
        review.started_at = None
        review.completed_at = None
        if x_user_github_id is not None:
            review.triggered_by_user_id = x_user_github_id
        await session.commit()

    return {"ok": True, "review_id": review_id, "job_id": job.job_id if job else None}


@router.post("/reviews/{review_id}/findings/{finding_index}/dismiss")
async def dismiss_finding(
    review_id: int,
    finding_index: int,
    installation_id: int | None = Query(default=None, ge=1),
) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
        review = await session.get(Review, review_id)
        if review is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
        if installation_id is None:
            installation_id = int(review.installation_id)
            await set_installation_context(session, installation_id)
        elif int(review.installation_id) != installation_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="installation_id mismatch"
            )

        debug_artifacts = review.debug_artifacts or {}
        dismissed = list(debug_artifacts.get("dismissed_findings", []))
        if finding_index not in dismissed:
            dismissed.append(finding_index)
        debug_artifacts["dismissed_findings"] = dismissed
        review.debug_artifacts = debug_artifacts
        await session.commit()

    return {"ok": True, "review_id": review_id, "dismissed_finding_index": finding_index}


@router.get("/reviews/{review_id}/stream")
async def stream_review_events(
    review_id: int,
    installation_id: int | None = Query(default=None, ge=1),
) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        previous_status: str | None = None
        for _ in range(120):
            async with AsyncSessionLocal() as session:
                if installation_id is not None:
                    await set_installation_context(session, installation_id)
                review = await session.get(Review, review_id)
                if review is None:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Review not found'})}\n\n"
                    return
                if installation_id is None:
                    await set_installation_context(session, int(review.installation_id))
                elif int(review.installation_id) != installation_id:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'installation_id mismatch'})}\n\n"
                    return

                if previous_status is None:
                    yield f"data: {json.dumps({'type': 'started', 'status': review.status})}\n\n"
                    previous_status = review.status
                elif review.status != previous_status:
                    yield f"data: {json.dumps({'type': 'status', 'status': review.status})}\n\n"
                    previous_status = review.status

                if review.status in {"done", "failed"}:
                    yield f"data: {json.dumps({'type': 'complete', 'status': review.status})}\n\n"
                    return

            await asyncio.sleep(2)

        yield f"data: {json.dumps({'type': 'error', 'message': 'Stream timeout'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
