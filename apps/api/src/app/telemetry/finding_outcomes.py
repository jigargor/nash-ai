from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from app.db.models import FindingOutcome, Review
from app.db.session import AsyncSessionLocal, set_installation_context
from app.github.client import GitHubClient
from sqlalchemy import select

BOT_COAUTHOR = "nash-ai-agent[bot]"
POSITIVE_REACTIONS = {"+1", "heart", "hooray", "rocket"}
NEGATIVE_REACTIONS = {"-1", "confused"}
NEGATIVE_REPLY_MARKERS = {"won't fix", "not a bug", "by design"}


def _coerce_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip(), 10)
        except ValueError:
            return default
    return default


class Outcome(str, Enum):
    APPLIED_DIRECTLY = "applied_directly"
    APPLIED_MODIFIED = "applied_modified"
    ACKNOWLEDGED = "acknowledged"
    DISMISSED = "dismissed"
    IGNORED = "ignored"
    ABANDONED = "abandoned"
    SUPERSEDED = "superseded"
    PENDING = "pending"


@dataclass
class OutcomeDecision:
    outcome: Outcome
    confidence: str
    signals: dict[str, object]


async def seed_pending_finding_outcomes(
    review_id: int,
    installation_id: int,
    finding_count: int,
    github_comment_ids: list[int | None],
) -> None:
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        existing_rows = await session.scalars(
            select(FindingOutcome).where(FindingOutcome.review_id == review_id)
        )
        existing_by_index = {int(row.finding_index): row for row in existing_rows}

        for index in range(finding_count):
            row = existing_by_index.get(index)
            comment_id = github_comment_ids[index] if index < len(github_comment_ids) else None
            if row is None:
                session.add(
                    FindingOutcome(
                        review_id=review_id,
                        finding_index=index,
                        github_comment_id=comment_id,
                        outcome=Outcome.PENDING.value,
                        outcome_confidence="high",
                        signals={},
                    )
                )
                continue
            if row.github_comment_id is None and comment_id is not None:
                row.github_comment_id = comment_id
        await session.commit()


async def classify_review_outcomes(
    gh: GitHubClient,
    review: Review,
    *,
    owner: str,
    repo: str,
    pr_number: int,
    pr_state: dict[str, object],
) -> None:
    findings_payload = review.findings if isinstance(review.findings, dict) else {}
    findings_list = findings_payload.get("findings")
    if not isinstance(findings_list, list) or not findings_list:
        return

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, int(review.installation_id))
        outcome_rows = await session.scalars(
            select(FindingOutcome).where(FindingOutcome.review_id == review.id)
        )
        rows_by_index = {int(row.finding_index): row for row in outcome_rows}

        for finding_index, finding in enumerate(findings_list):
            if not isinstance(finding, dict):
                continue
            row = rows_by_index.get(finding_index)
            if row is None:
                row = FindingOutcome(
                    review_id=int(review.id),
                    finding_index=finding_index,
                    github_comment_id=None,
                    outcome=Outcome.PENDING.value,
                    outcome_confidence="high",
                    signals={},
                )
                session.add(row)

            decision = await classify_finding_outcome(
                gh=gh,
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                review=review,
                finding=finding,
                comment_id=int(row.github_comment_id)
                if row.github_comment_id is not None
                else None,
                pr_state=pr_state,
            )
            row.outcome = decision.outcome.value
            row.outcome_confidence = decision.confidence
            row.signals = decision.signals

        await session.commit()


async def classify_finding_outcome(
    *,
    gh: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    review: Review,
    finding: dict[str, object],
    comment_id: int | None,
    pr_state: dict[str, object],
) -> OutcomeDecision:
    signals: dict[str, object] = {}
    file_path = str(finding.get("file_path", ""))
    line_start = _coerce_int(finding.get("line_start"), 0)
    line_end = _coerce_int(finding.get("line_end", line_start) or line_start, line_start)
    suggestion = finding.get("suggestion")

    signals["reactions"] = (
        await gh.get_pull_review_comment_reactions(owner, repo, comment_id) if comment_id else []
    )
    signals["replies"] = (
        await gh.get_pull_review_comment_replies(owner, repo, comment_id) if comment_id else []
    )
    signals["resolved_conversation"] = (
        await gh.is_pull_review_thread_resolved(owner, repo, pr_number, comment_id)
        if comment_id
        else False
    )
    since = review.completed_at or review.created_at
    signals["subsequent_commits_touching_file"] = await gh.get_commits_touching_file(
        owner=owner,
        repo=repo,
        path=file_path,
        since=since,
    )
    signals["line_still_exists_at_merge"] = await gh.line_exists_in_pull_request_final_state(
        owner=owner,
        repo=repo,
        pr_state=pr_state,
        file_path=file_path,
        line_text=str(finding.get("target_line_content", "")),
    )

    if isinstance(suggestion, str) and suggestion.strip():
        signals["suggestion_apply_match"] = await detect_suggestion_apply(
            gh=gh,
            owner=owner,
            repo=repo,
            commits=signals["subsequent_commits_touching_file"],
            suggestion=suggestion,
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
        )
    else:
        signals["suggestion_apply_match"] = "no_suggestion"

    if pr_state.get("state") == "closed" and not pr_state.get("merged"):
        return OutcomeDecision(Outcome.ABANDONED, "high", signals)

    if signals["suggestion_apply_match"] == "exact":
        return OutcomeDecision(Outcome.APPLIED_DIRECTLY, "high", signals)

    has_bot_coauth_commit = any(
        commit.get("co_authored_by") == BOT_COAUTHOR
        for commit in _safe_commit_list(signals["subsequent_commits_touching_file"])
    )
    if has_bot_coauth_commit:
        return OutcomeDecision(Outcome.APPLIED_DIRECTLY, "high", signals)

    if signals["suggestion_apply_match"] in {"near", "modified"}:
        return OutcomeDecision(Outcome.APPLIED_MODIFIED, "medium", signals)

    line_still_exists = bool(signals["line_still_exists_at_merge"])
    if not line_still_exists:
        if commits_scoped_narrowly(
            _safe_commit_list(signals["subsequent_commits_touching_file"]), finding
        ):
            return OutcomeDecision(Outcome.APPLIED_MODIFIED, "medium", signals)
        return OutcomeDecision(Outcome.SUPERSEDED, "low", signals)

    reactions = _safe_reaction_list(signals["reactions"])
    replies = _safe_reply_list(signals["replies"])
    if any(reaction.get("content") in NEGATIVE_REACTIONS for reaction in reactions):
        return OutcomeDecision(Outcome.DISMISSED, "high", signals)

    if bool(signals["resolved_conversation"]) and line_still_exists:
        negative_reply = any(
            any(marker in str(reply.get("body", "")).lower() for marker in NEGATIVE_REPLY_MARKERS)
            for reply in replies
        )
        if negative_reply:
            return OutcomeDecision(Outcome.DISMISSED, "high", signals)
        if any(reaction.get("content") in POSITIVE_REACTIONS for reaction in reactions) or any(
            str(reply.get("body", "")).strip() for reply in replies
        ):
            return OutcomeDecision(Outcome.ACKNOWLEDGED, "medium", signals)
        return OutcomeDecision(Outcome.DISMISSED, "medium", signals)

    if pr_state.get("merged") and line_still_exists:
        if any(reaction.get("content") in POSITIVE_REACTIONS for reaction in reactions):
            return OutcomeDecision(Outcome.ACKNOWLEDGED, "low", signals)
        return OutcomeDecision(Outcome.IGNORED, "high", signals)

    if pr_state.get("state") == "open":
        posted_at = review.completed_at or review.created_at
        days_open = (datetime.now(timezone.utc) - posted_at).days
        if days_open < 14:
            return OutcomeDecision(Outcome.PENDING, "high", signals)
        return OutcomeDecision(Outcome.IGNORED, "low", signals)

    return OutcomeDecision(Outcome.IGNORED, "low", signals)


async def detect_suggestion_apply(
    *,
    gh: GitHubClient,
    owner: str,
    repo: str,
    commits: object,
    suggestion: str,
    file_path: str,
    line_start: int,
    line_end: int,
) -> str:
    normalized_suggestion_lines = [line.strip() for line in suggestion.splitlines() if line.strip()]
    if not normalized_suggestion_lines:
        return "none"

    for commit in _safe_commit_list(commits):
        sha = commit.get("sha")
        if not isinstance(sha, str) or not sha:
            continue
        commit_files = await gh.get_commit_files(owner, repo, sha)
        target_file = next(
            (item for item in commit_files if item.get("filename") == file_path), None
        )
        if target_file is None:
            continue
        patch = str(target_file.get("patch", "") or "")
        if not patch:
            continue
        added_lines = [
            line[1:].strip()
            for line in patch.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
        if all(line in added_lines for line in normalized_suggestion_lines):
            if _has_bot_coauthor(commit):
                return "exact"
            return "near"
        if _looks_like_modified_apply(added_lines, normalized_suggestion_lines):
            return "modified"
    return "none"


def commits_scoped_narrowly(commits: list[dict[str, object]], finding: dict[str, object]) -> bool:
    target_file = str(finding.get("file_path", ""))
    touched_target = False
    touched_others = False
    for commit in commits:
        files = commit.get("files")
        if not isinstance(files, list):
            continue
        for file_entry in files:
            if not isinstance(file_entry, dict):
                continue
            filename = str(file_entry.get("filename", ""))
            if filename == target_file:
                touched_target = True
            else:
                touched_others = True
    return touched_target and not touched_others


async def classify_pr_outcomes_for_closed_pr(
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
) -> None:
    gh = await GitHubClient.for_installation(installation_id)
    pr_state = await gh.get_pull_request(owner, repo, pr_number)
    repo_full_name = f"{owner}/{repo}"

    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        rows = await session.scalars(
            select(Review)
            .where(Review.installation_id == installation_id)
            .where(Review.repo_full_name == repo_full_name)
            .where(Review.pr_number == pr_number)
            .where(Review.findings.is_not(None))
        )
        reviews = list(rows)

    for review in reviews:
        await classify_review_outcomes(
            gh=gh,
            review=review,
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            pr_state=pr_state,
        )


async def classify_pending_outcomes_nightly(max_open_days: int = 14) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_open_days)
    grouped: dict[tuple[int, str, int], list[Review]] = {}
    async with AsyncSessionLocal() as session:
        installation_rows = await session.scalars(select(Review.installation_id).distinct())
        installation_ids = [int(item) for item in installation_rows]
        for installation_id in installation_ids:
            await set_installation_context(session, installation_id)
            pending_rows = await session.execute(
                select(FindingOutcome, Review)
                .join(Review, Review.id == FindingOutcome.review_id)
                .where(Review.installation_id == installation_id)
                .where(FindingOutcome.outcome == Outcome.PENDING.value)
                .where(Review.created_at <= cutoff)
            )
            for _, review in pending_rows.all():
                key = (int(review.installation_id), review.repo_full_name, int(review.pr_number))
                grouped.setdefault(key, []).append(review)

    for (installation_id, repo_full_name, pr_number), reviews in grouped.items():
        owner, repo = repo_full_name.split("/", 1)
        gh = await GitHubClient.for_installation(installation_id)
        pr_state = await gh.get_pull_request(owner, repo, pr_number)
        for review in reviews:
            await classify_review_outcomes(
                gh=gh,
                review=review,
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                pr_state=pr_state,
            )


def _safe_commit_list(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _safe_reaction_list(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _safe_reply_list(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _has_bot_coauthor(commit: dict[str, object]) -> bool:
    trailer = str(commit.get("co_authored_by", "")).strip().lower()
    return trailer == BOT_COAUTHOR


def _looks_like_modified_apply(added_lines: list[str], suggestion_lines: list[str]) -> bool:
    if not added_lines or not suggestion_lines:
        return False
    suggestion_tokens = {
        token for token in re.split(r"\W+", " ".join(suggestion_lines).lower()) if token
    }
    added_tokens = {token for token in re.split(r"\W+", " ".join(added_lines).lower()) if token}
    if not suggestion_tokens or not added_tokens:
        return False
    overlap = len(suggestion_tokens.intersection(added_tokens))
    return overlap >= max(2, len(suggestion_tokens) // 3)


async def list_review_finding_outcomes(
    review_id: int,
    installation_id: int,
) -> list[dict[str, object]]:
    async with AsyncSessionLocal() as session:
        await set_installation_context(session, installation_id)
        rows = await session.scalars(
            select(FindingOutcome)
            .where(FindingOutcome.review_id == review_id)
            .order_by(FindingOutcome.finding_index.asc())
        )
        return [
            {
                "finding_index": int(row.finding_index),
                "github_comment_id": int(row.github_comment_id)
                if row.github_comment_id is not None
                else None,
                "outcome": row.outcome,
                "outcome_confidence": row.outcome_confidence,
                "detected_at": row.detected_at.isoformat() if row.detected_at else None,
                "signals": row.signals,
            }
            for row in rows
        ]


async def summarize_finding_outcomes(
    *,
    installation_id: int | None = None,
    repo_full_name: str | None = None,
) -> dict[str, object]:
    rows: list[tuple[FindingOutcome, Review]] = []
    async with AsyncSessionLocal() as session:
        if installation_id is not None:
            await set_installation_context(session, installation_id)
            stmt = select(FindingOutcome, Review).join(Review, Review.id == FindingOutcome.review_id)
            stmt = stmt.where(Review.installation_id == installation_id)
            if repo_full_name:
                stmt = stmt.where(Review.repo_full_name == repo_full_name)
            rows = list((await session.execute(stmt)).tuples().all())
        else:
            installation_rows = await session.scalars(select(Review.installation_id).distinct())
            installation_ids = [int(item) for item in installation_rows]
            for scoped_installation_id in installation_ids:
                await set_installation_context(session, scoped_installation_id)
                stmt = select(FindingOutcome, Review).join(Review, Review.id == FindingOutcome.review_id)
                stmt = stmt.where(Review.installation_id == scoped_installation_id)
                if repo_full_name:
                    stmt = stmt.where(Review.repo_full_name == repo_full_name)
                rows.extend((await session.execute(stmt)).tuples().all())

    total_classified = 0
    outcome_counts: dict[str, int] = {}
    severity_breakdown: dict[str, dict[str, int]] = {}
    category_breakdown: dict[str, dict[str, int]] = {}
    evidence_breakdown: dict[str, dict[str, int]] = {}
    confidence_bucket_breakdown: dict[str, dict[str, int]] = {}
    vendor_claim_breakdown: dict[str, dict[str, int]] = {}
    model_breakdown: dict[str, dict[str, int]] = {}
    provider_breakdown: dict[str, dict[str, int]] = {}
    repo_breakdown: dict[str, dict[str, int]] = {}
    prompt_version_breakdown: dict[str, dict[str, int]] = {}

    for outcome_row, review in rows:
        if outcome_row.outcome == Outcome.PENDING.value:
            continue
        total_classified += 1
        outcome_counts[outcome_row.outcome] = outcome_counts.get(outcome_row.outcome, 0) + 1

        finding = _extract_finding(review, int(outcome_row.finding_index))
        severity = str(finding.get("severity", "unknown"))
        category = str(finding.get("category", "unknown"))
        evidence = str(finding.get("evidence", "unknown"))
        confidence = _coerce_int(finding.get("confidence"), 0)
        is_vendor_claim = bool(finding.get("is_vendor_claim", False))
        prompt_version = str((review.debug_artifacts or {}).get("prompt_version", "unknown"))

        _increment_breakdown(severity_breakdown, severity, outcome_row.outcome)
        _increment_breakdown(category_breakdown, category, outcome_row.outcome)
        _increment_breakdown(evidence_breakdown, evidence, outcome_row.outcome)
        _increment_breakdown(
            confidence_bucket_breakdown, _confidence_bucket(confidence), outcome_row.outcome
        )
        _increment_breakdown(
            vendor_claim_breakdown,
            "vendor" if is_vendor_claim else "non_vendor",
            outcome_row.outcome,
        )
        _increment_breakdown(model_breakdown, review.model, outcome_row.outcome)
        _increment_breakdown(provider_breakdown, str(review.model_provider), outcome_row.outcome)
        _increment_breakdown(repo_breakdown, review.repo_full_name, outcome_row.outcome)
        _increment_breakdown(prompt_version_breakdown, prompt_version, outcome_row.outcome)

    applied = outcome_counts.get(Outcome.APPLIED_DIRECTLY.value, 0) + outcome_counts.get(
        Outcome.APPLIED_MODIFIED.value, 0
    )
    acknowledged = outcome_counts.get(Outcome.ACKNOWLEDGED.value, 0)
    dismissed = outcome_counts.get(Outcome.DISMISSED.value, 0)
    ignored = outcome_counts.get(Outcome.IGNORED.value, 0)
    denominator = total_classified or 1

    return {
        "total_classified": total_classified,
        "outcomes": outcome_counts,
        "global_metrics": {
            "applied_rate": applied / denominator,
            "dismiss_rate": dismissed / denominator,
            "ignore_rate": ignored / denominator,
            "positive_rate": (applied + acknowledged) / denominator,
            "useful_rate": (applied + acknowledged) / denominator,
        },
        "breakdowns": {
            "severity": severity_breakdown,
            "category": category_breakdown,
            "evidence": evidence_breakdown,
            "confidence_bucket": confidence_bucket_breakdown,
            "is_vendor_claim": vendor_claim_breakdown,
            "model": model_breakdown,
            "provider": provider_breakdown,
            "repo": repo_breakdown,
            "prompt_version": prompt_version_breakdown,
        },
    }


def _extract_finding(review: Review, finding_index: int) -> dict[str, object]:
    findings_payload = review.findings if isinstance(review.findings, dict) else {}
    findings = findings_payload.get("findings")
    if not isinstance(findings, list) or finding_index < 0 or finding_index >= len(findings):
        return {}
    finding = findings[finding_index]
    if not isinstance(finding, dict):
        return {}
    return finding


def _increment_breakdown(store: dict[str, dict[str, int]], key: str, outcome: str) -> None:
    bucket = store.setdefault(key, {})
    bucket[outcome] = bucket.get(outcome, 0) + 1


def _confidence_bucket(value: int) -> str:
    if value >= 95:
        return "95-100"
    if value >= 80:
        return "80-94"
    if value >= 60:
        return "60-79"
    if value >= 40:
        return "40-59"
    return "0-39"
