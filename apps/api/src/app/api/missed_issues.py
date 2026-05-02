"""Missed-issue capture endpoints.

Records issues that the review agent failed to flag so they can be:
- linked back to the review that missed them
- exported as eval cases (expected findings) for evals/run_eval.py
- used in recall metrics and false-negative rate computation
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import CurrentDashboardUser, get_current_dashboard_user
from app.api.router import _allowed_installation_ids, _require_installation_access, _verify_api_access
from app.categories import CanonicalCategory
from app.db.models import MissedIssue, Review, User
from app.db.session import get_db, set_installation_context

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/missed-issues",
    dependencies=[Depends(_verify_api_access), Depends(get_current_dashboard_user)],
)

HowFound = Literal[
    "manual_report",
    "bug_fix",
    "static_analyzer",
    "security_scan",
    "test_failure",
    "maintainer_review",
]


class CreateMissedIssueRequest(BaseModel):
    review_id: int
    file_path: str
    line_start: Annotated[int, Field(ge=1)]
    line_end: Annotated[int | None, Field(ge=1)] = None
    description: Annotated[str, Field(max_length=1000)]
    expected_category: CanonicalCategory
    expected_severity: Literal["critical", "high", "medium", "low"]
    how_found: HowFound
    notes: str | None = None


class MissedIssueResponse(BaseModel):
    id: int
    review_id: int
    installation_id: int
    file_path: str
    line_start: int
    line_end: int | None
    description: str
    expected_category: str
    expected_severity: str
    how_found: str
    notes: str | None
    reported_by_user_id: int | None
    created_at: str


class EvalFinding(BaseModel):
    """One entry in the ``findings`` array of an eval-compatible expected.json."""

    file_path: str
    line_start: int
    category: str
    severity: str
    message: str


class MissedIssueExport(BaseModel):
    """Top-level export envelope that matches the evals/run_eval.py expected.json schema."""

    installation_id: int
    findings: list[EvalFinding]


def _to_response(row: MissedIssue) -> MissedIssueResponse:
    return MissedIssueResponse(
        id=row.id,
        review_id=row.review_id,
        installation_id=row.installation_id,
        file_path=row.file_path,
        line_start=row.line_start,
        line_end=row.line_end,
        description=row.description,
        expected_category=row.expected_category,
        expected_severity=row.expected_severity,
        how_found=row.how_found,
        notes=row.notes,
        reported_by_user_id=row.reported_by_user_id,
        created_at=row.created_at.isoformat(),
    )


async def _get_user_row_id(
    session: AsyncSession, github_id: int
) -> int | None:
    return await session.scalar(
        select(User.id).where(User.github_id == github_id).where(User.deleted_at.is_(None))
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=MissedIssueResponse)
async def create_missed_issue(
    body: CreateMissedIssueRequest,
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
    session: AsyncSession = Depends(get_db),
) -> MissedIssueResponse:
    """Record a missed issue linked to a specific review.

    Auth: requires X-Dashboard-User-Token.
    Tenant: verifies the authenticated user has access to the review's installation.
    """
    review = await session.scalar(select(Review).where(Review.id == body.review_id))
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

    allowed = await _allowed_installation_ids(session, current_user)
    _require_installation_access(allowed, review.installation_id)

    await set_installation_context(session, review.installation_id)

    reporter_id = await _get_user_row_id(session, current_user.github_id)

    row = MissedIssue(
        review_id=body.review_id,
        installation_id=review.installation_id,
        file_path=body.file_path,
        line_start=body.line_start,
        line_end=body.line_end,
        description=body.description,
        expected_category=body.expected_category,
        expected_severity=body.expected_severity,
        how_found=body.how_found,
        notes=body.notes,
        reported_by_user_id=reporter_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info(
        "missed_issue.created id=%s review_id=%s installation_id=%s",
        row.id,
        row.review_id,
        row.installation_id,
    )
    return _to_response(row)


@router.get("", response_model=list[MissedIssueResponse])
async def list_missed_issues(
    review_id: int | None = Query(default=None),
    installation_id: int | None = Query(default=None),
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
    session: AsyncSession = Depends(get_db),
) -> list[MissedIssueResponse]:
    """List missed issues, optionally filtered by review or installation.

    Auth: requires X-Dashboard-User-Token.
    Tenant: results are scoped to installations the user has access to.
    At least one of ``review_id`` or ``installation_id`` is recommended for performance.
    """
    allowed = await _allowed_installation_ids(session, current_user)

    stmt = select(MissedIssue)

    if review_id is not None:
        review = await session.scalar(select(Review).where(Review.id == review_id))
        if review is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
        _require_installation_access(allowed, review.installation_id)
        stmt = stmt.where(MissedIssue.review_id == review_id)
    elif installation_id is not None:
        _require_installation_access(allowed, installation_id)
        stmt = stmt.where(MissedIssue.installation_id == installation_id)
    else:
        stmt = stmt.where(MissedIssue.installation_id.in_(allowed))

    stmt = stmt.order_by(MissedIssue.created_at.desc())
    rows = (await session.scalars(stmt)).all()
    return [_to_response(r) for r in rows]


@router.get("/export", response_model=MissedIssueExport)
async def export_missed_issues(
    installation_id: int = Query(...),
    format: Literal["eval"] = Query(default="eval"),
    current_user: CurrentDashboardUser = Depends(get_current_dashboard_user),
    session: AsyncSession = Depends(get_db),
) -> MissedIssueExport:
    """Export missed issues as an eval-compatible expected.json payload.

    Each missed issue becomes one entry in the ``findings`` array matching
    the schema consumed by ``evals/run_eval.py`` and ``evals/metrics.py``.
    Keys: ``file_path``, ``line_start``, ``category``, ``severity``, ``message``.

    Auth: requires X-Dashboard-User-Token.
    Tenant: verifies the authenticated user has access to the requested installation.
    """
    allowed = await _allowed_installation_ids(session, current_user)
    _require_installation_access(allowed, installation_id)

    rows = (
        await session.scalars(
            select(MissedIssue)
            .where(MissedIssue.installation_id == installation_id)
            .order_by(MissedIssue.created_at.asc())
        )
    ).all()

    findings = [
        EvalFinding(
            file_path=r.file_path,
            line_start=r.line_start,
            category=r.expected_category,
            severity=r.expected_severity,
            message=r.description,
        )
        for r in rows
    ]
    return MissedIssueExport(installation_id=installation_id, findings=findings)
