"""Labeling endpoints for Phase 3: Human Labeling.

Auth boundary: all routes require a valid X-Dashboard-User-Token JWT
(enforced by the router-level Depends(get_current_dashboard_user)).

Tenant isolation: every write/read resolves the review's installation_id,
verifies the current user is a member of that installation, then calls
set_installation_context() so RLS applies before any DML.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.auth import CurrentDashboardUser, get_current_dashboard_user
from app.config import settings
from app.db.models import FindingLabel, InstallationUser, Review, User
from app.db.session import AsyncSessionLocal, set_installation_context


FindingLabelValue = Literal[
    "true_positive",
    "false_positive",
    "severity_wrong",
    "category_wrong",
    "duplicate",
    "not_actionable",
    "correct_but_too_minor",
    "accepted",
    "accepted_with_modification",
]


class LabelFindingRequest(BaseModel):
    label: FindingLabelValue = Field(..., description="Quality label for this finding")
    notes: str | None = Field(default=None, max_length=4096, description="Optional labeler notes")


class FindingLabelResponse(BaseModel):
    review_id: int
    finding_index: int
    installation_id: int
    label: str
    notes: str | None
    labeled_by_user_id: int | None
    labeled_at: str
    updated_at: str


class FindingLabelsExportItem(BaseModel):
    review_id: int
    finding_index: int
    installation_id: int
    repo_full_name: str
    pr_number: int
    label: str
    notes: str | None
    finding: dict[str, Any] | None
    labeled_by_user_id: int | None
    labeled_at: str


def _verify_api_access(x_api_key: str | None = Header(default=None)) -> None:
    if settings.environment.lower() == "production" and not settings.api_access_key:
        raise HTTPException(  # pragma: no cover
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="API key auth is not configured"
        )
    if not settings.api_access_key:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_access_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Api-Key"
        )


router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(_verify_api_access), Depends(get_current_dashboard_user)],
)


async def _get_allowed_installation_ids(current_user: CurrentDashboardUser) -> set[int]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(InstallationUser.installation_id)
                .join(User, User.id == InstallationUser.user_id)
                .where(User.github_id == current_user.github_id)
                .where(User.deleted_at.is_(None))
            )
        ).scalars()
        return {int(iid) for iid in rows}


async def _resolve_review_installation(
    review_id: int,
    current_user: CurrentDashboardUser,
) -> tuple[Review, int]:
    """Return (review, installation_id) after verifying user access."""
    allowed = await _get_allowed_installation_ids(current_user)
    async with AsyncSessionLocal() as session:
        review = await session.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    installation_id = int(review.installation_id)
    if installation_id not in allowed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    return review, installation_id


async def _get_labeler_user_id(current_user: CurrentDashboardUser) -> int | None:
    async with AsyncSessionLocal() as session:
        row = await session.scalar(
            select(User.id)
            .where(User.github_id == current_user.github_id)
            .where(User.deleted_at.is_(None))
            .limit(1)
        )
    return int(row) if row is not None else None


def _finding_at_index(review: Review, finding_index: int) -> dict[str, Any] | None:
    raw = review.findings
    if not isinstance(raw, dict):
        return None
    findings_list = raw.get("findings")
    if not isinstance(findings_list, list):
        return None
    if 0 <= finding_index < len(findings_list):
        item = findings_list[finding_index]
        return item if isinstance(item, dict) else None
    return None


@router.post(
    "/findings/{review_id}/{finding_index}/label",
    response_model=FindingLabelResponse,
    status_code=status.HTTP_200_OK,
)
async def label_finding(
    review_id: int,
    finding_index: int,
    payload: LabelFindingRequest,
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> FindingLabelResponse:
    """Create or update the human label for a single finding.

    Auth: requires authenticated dashboard user.
    Tenant isolation: user must belong to the installation that owns the review.
    """
    review, installation_id = await _resolve_review_installation(review_id, current_user)

    finding = _finding_at_index(review, finding_index)
    if finding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding index {finding_index} not found in review {review_id}",
        )

    labeler_user_id = await _get_labeler_user_id(current_user)
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)

        stmt = (
            pg_insert(FindingLabel)
            .values(
                review_id=review_id,
                finding_index=finding_index,
                installation_id=installation_id,
                label=payload.label,
                labeled_by_user_id=labeler_user_id,
                notes=payload.notes,
                labeled_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["review_id", "finding_index"],
                set_={
                    "label": payload.label,
                    "notes": payload.notes,
                    "labeled_by_user_id": labeler_user_id,
                    "updated_at": now,
                },
            )
            .returning(FindingLabel)
        )
        result = await session.execute(stmt)
        row = result.scalar_one()
        await session.commit()

    return FindingLabelResponse(
        review_id=int(row.review_id),
        finding_index=int(row.finding_index),
        installation_id=int(row.installation_id),
        label=row.label,
        notes=row.notes,
        labeled_by_user_id=int(row.labeled_by_user_id) if row.labeled_by_user_id is not None else None,
        labeled_at=row.labeled_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.get(
    "/findings/{review_id}/labels",
    response_model=list[FindingLabelResponse],
)
async def list_finding_labels(
    review_id: int,
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> list[FindingLabelResponse]:
    """Return all human labels for every finding in a review.

    Auth: requires authenticated dashboard user.
    Tenant isolation: user must belong to the installation that owns the review.
    """
    _, installation_id = await _resolve_review_installation(review_id, current_user)

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        rows = await session.scalars(
            select(FindingLabel)
            .where(FindingLabel.review_id == review_id)
            .order_by(FindingLabel.finding_index.asc())
        )
        return [
            FindingLabelResponse(
                review_id=int(row.review_id),
                finding_index=int(row.finding_index),
                installation_id=int(row.installation_id),
                label=row.label,
                notes=row.notes,
                labeled_by_user_id=int(row.labeled_by_user_id) if row.labeled_by_user_id is not None else None,
                labeled_at=row.labeled_at.isoformat(),
                updated_at=row.updated_at.isoformat(),
            )
            for row in rows
        ]


@router.get(
    "/labels/export",
    response_model=list[FindingLabelsExportItem],
)
async def export_labels(
    installation_id: int = Query(..., ge=1, description="Installation to export labels for"),
    repo_full_name: str | None = Query(default=None, description="Optional repo filter"),
    format: Literal["eval"] = Query(default="eval"),  # noqa: A002
    limit: int = Query(default=1000, ge=1, le=10000),
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
) -> list[FindingLabelsExportItem]:
    """Export labeled findings as eval-compatible JSON.

    The returned shape matches what evals/run_eval.py expects in expected.json:
    each item includes the review context (repo, PR) plus the finding dict and
    the human label.

    Auth: requires authenticated dashboard user.
    Tenant isolation: user must belong to the requested installation.
    """
    allowed = await _get_allowed_installation_ids(current_user)
    if installation_id not in allowed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Installation not found")

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)

        stmt = (
            select(FindingLabel, Review)
            .join(Review, Review.id == FindingLabel.review_id)
            .where(FindingLabel.installation_id == installation_id)
        )
        if repo_full_name is not None:
            stmt = stmt.where(Review.repo_full_name == repo_full_name)
        stmt = stmt.order_by(FindingLabel.review_id.asc(), FindingLabel.finding_index.asc()).limit(limit)

        result = await session.execute(stmt)
        pairs = result.all()

    items: list[FindingLabelsExportItem] = []
    for label_row, review_row in pairs:
        finding = _finding_at_index(review_row, int(label_row.finding_index))
        items.append(
            FindingLabelsExportItem(
                review_id=int(label_row.review_id),
                finding_index=int(label_row.finding_index),
                installation_id=int(label_row.installation_id),
                repo_full_name=review_row.repo_full_name,
                pr_number=int(review_row.pr_number),
                label=label_row.label,
                notes=label_row.notes,
                finding=finding,
                labeled_by_user_id=int(label_row.labeled_by_user_id) if label_row.labeled_by_user_id is not None else None,
                labeled_at=label_row.labeled_at.isoformat(),
            )
        )
    return items
