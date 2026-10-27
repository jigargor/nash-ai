"""Worker adapter: run an ARQ ``review_pr`` job through ``review_pipeline`` (strangler fig).

Enabled by ``settings.use_review_pipeline_worker`` (default False). The adapter owns the job
lifecycle the pure pipeline deliberately does not know about: GitHub client, PR loading, the
supersede check, draft skipping, review-row persistence (via the runner's existing
``_mark_review_running`` / ``_mark_review_done`` so DB side effects stay identical), and the
submission-lock release.

Known gaps vs. ``runner.run_review`` (why the flag defaults off):
- no fast-path pre-pass, challenger/tie-break debate, or chunked review. Diffs that exceed the
  token ceiling delegate to the legacy runner so they keep working when the flag is on;
- review status reflects pipeline errors only (a rejected inline comment does not downgrade to
  ``partial`` at the DB level; rejections are in ``debug_artifacts['drops']``).

Runner symbols are imported lazily: ``runner`` imports ``app.agent.pipeline`` (shared validation
stage), so a module-level import here would be circular.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.pipeline.delivery_sinks import LiveDeliverySink
from app.agent.pipeline.ports import DeliveryResult, DeliverySink
from app.agent.pipeline.review_pipeline import review_pipeline
from app.agent.review_config import ReviewConfig
from app.agent.schema import ReviewResult

logger = logging.getLogger(__name__)


class RunnerPersistence:
    """``Persistence`` port backed by the legacy runner's DB helpers (identical row updates)."""

    def __init__(self, context: dict[str, Any]) -> None:
        self._context = context
        self._started = False
        self.review_config: ReviewConfig | None = None

    async def mark_running(self, review_id: int, installation_id: int) -> None:
        if self._started:  # adapter marks early; the pipeline's own call becomes a no-op
            return
        from app.agent.runner import _mark_review_running

        await _mark_review_running(review_id, installation_id)
        self._started = True

    async def mark_done(
        self,
        *,
        review_id: int,
        installation_id: int,
        result: ReviewResult,
        status: str,
        tokens_used: int,
        cost_usd: float | None,
        debug_artifacts: dict[str, Any] | None = None,
    ) -> None:
        from app.agent.runner import _mark_review_done

        existing = self._context.get("debug_artifacts")
        self._context["debug_artifacts"] = {
            **(existing if isinstance(existing, dict) else {}),
            **(debug_artifacts or {}),
        }
        # Token/price counters live on the shared context (seeded into the pipeline), so the
        # runner's cost estimation sees real input/output/cached token counts.
        self._context["tokens_used"] = tokens_used
        await _mark_review_done(
            session_data=result,
            context=self._context,
            status=status,
            review_config=self.review_config,
        )

    async def seed_outcomes(
        self,
        *,
        review_id: int,
        installation_id: int,
        finding_count: int,
        github_comment_ids: list[int | None],
    ) -> None:
        from app.telemetry.finding_outcomes import seed_pending_finding_outcomes

        await seed_pending_finding_outcomes(
            review_id=review_id,
            installation_id=installation_id,
            finding_count=finding_count,
            github_comment_ids=github_comment_ids,
        )


class _RecordingSink:
    """Wraps a delivery sink to capture the GitHub review node id for the review row."""

    def __init__(self, inner: DeliverySink, context: dict[str, Any]) -> None:
        self._inner = inner
        self._context = context

    async def post(
        self,
        result: ReviewResult,
        *,
        owner: str,
        repo: str,
        pr_number: int,
        commit_sha: str,
    ) -> DeliveryResult:
        from app.agent.runner import extract_review_node_id

        response = await self._inner.post(
            result, owner=owner, repo=repo, pr_number=pr_number, commit_sha=commit_sha
        )
        node_id = extract_review_node_id(dict(response))
        if node_id:
            self._context["github_review_node_id"] = node_id
        return response


async def run_review_via_pipeline(
    review_id: int,
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    *,
    user_github_id: int | None = None,
    redis: Any | None = None,
) -> None:
    """Drop-in replacement for ``runner.run_review`` backed by ``review_pipeline``."""
    from app.agent.context_builder import is_diff_too_large
    from app.agent.runner import (
        ReviewSupersededError,
        _available_provider_ids,
        _load_review_config_cached,
        _load_user_provider_keys,
        _set_runtime_model_context,
        run_review,
    )
    from app.github.client import GitHubClient
    from app.ingestion.pr_loader import load_pr_context
    from app.llm.circuit_breaker import record_provider_success
    from app.llm.router import resolve_model_attempt_chain
    from app.queue.idempotency import release_review_submission_lock

    user_provider_keys: dict[str, str] = {}
    if user_github_id is not None:
        user_provider_keys = await _load_user_provider_keys(user_github_id)
    context: dict[str, Any] = {
        "review_id": review_id,
        "installation_id": installation_id,
        "user_provider_keys": user_provider_keys,
        "user_github_id": user_github_id,
        "_redis": redis,
        "debug_artifacts": {"pipeline_path": "review_pipeline"},
    }
    persistence = RunnerPersistence(context)
    gh = await GitHubClient.for_installation(installation_id)
    delegated_to_legacy = False
    try:
        try:
            live_pr = await gh.get_pull_request(owner, repo, pr_number)
            live_head_raw = (live_pr.get("head") or {}).get("sha") if isinstance(live_pr, dict) else None
            live_head = live_head_raw.strip() if isinstance(live_head_raw, str) else ""
            if live_head and live_head != head_sha:
                raise ReviewSupersededError(head_sha, live_head)

            pr_context = await load_pr_context(
                gh,
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                head_sha=head_sha,
                installation_id=installation_id,
                review_id=review_id,
            )
            config_ref = (pr_context.base_sha or "").strip() or head_sha
            context["config_ref"] = config_ref
            review_config = await _load_review_config_cached(gh, owner, repo, config_ref)
            persistence.review_config = review_config

            if is_diff_too_large(pr_context.diff_text) or review_config.chunking.enabled:
                # Chunked / oversized review is not implemented in the pipeline yet.
                logger.info("Pipeline adapter delegating to legacy runner review_id=%s", review_id)
                delegated_to_legacy = True
                await run_review(
                    review_id,
                    installation_id,
                    owner,
                    repo,
                    pr_number,
                    head_sha,
                    user_github_id=user_github_id,
                    redis=redis,
                )
                return

            await persistence.mark_running(review_id, installation_id)
            if pr_context.draft and not review_config.review_drafts:
                await persistence.mark_done(
                    review_id=review_id,
                    installation_id=installation_id,
                    result=ReviewResult(
                        findings=[],
                        summary="Skipped automated review because this pull request is a draft.",
                    ),
                    status="skipped",
                    tokens_used=0,
                    cost_usd=0.0,
                )
                return

            attempts = resolve_model_attempt_chain(
                review_config,
                "primary_review",
                available_providers=_available_provider_ids(context),
            )
            if not attempts:
                raise RuntimeError("No provider candidates available for primary review")
            _set_runtime_model_context(context, attempts[0])

            report = await review_pipeline(
                pr_context,
                review_config,
                delivery=_RecordingSink(
                    LiveDeliverySink(
                        gh,
                        request_changes_policy=review_config.request_changes_policy,
                        review_id=review_id,
                        installation_id=installation_id,
                    ),
                    context,
                ),
                github=gh,
                persistence=persistence,
                attempts=[(a.provider, a.model) for a in attempts],
                dry_run=False,
                run_editor_stage=True,
                context_seed=context,
            )
            if redis is not None and report.providers_served and not report.pipeline_errors:
                try:
                    await record_provider_success(redis, report.providers_served[-1])
                except Exception:
                    logger.debug("Circuit breaker success record failed", exc_info=True)
        except ReviewSupersededError as exc:
            logger.warning(
                "Review superseded before posting review_id=%s job_head_sha=%s live_head_sha=%s",
                review_id,
                exc.job_head_sha,
                exc.live_head_sha,
            )
            await persistence.mark_done(
                review_id=review_id,
                installation_id=installation_id,
                result=ReviewResult(
                    findings=[],
                    summary=(
                        f"Superseded by a newer push (head {exc.live_head_sha[:7]}); "
                        f"this review of {exc.job_head_sha[:7]} was not posted."
                    ),
                ),
                status="superseded",
                tokens_used=0,
                cost_usd=0.0,
                debug_artifacts={"superseded_by_head_sha": exc.live_head_sha},
            )
        except Exception as exc:
            logger.exception("Pipeline review job failed review_id=%s", review_id)
            await persistence.mark_done(
                review_id=review_id,
                installation_id=installation_id,
                result=ReviewResult(findings=[], summary=f"Review failed: {exc}"),
                status="failed",
                tokens_used=int(context.get("tokens_used") or 0),
                cost_usd=None,
                debug_artifacts={"terminal_error": {"exception_type": exc.__class__.__name__}},
            )
            raise
    finally:
        try:
            await gh.aclose()
        except Exception:
            logger.debug("GitHub client close failed review_id=%s", review_id, exc_info=True)
        # The legacy runner releases the lock itself in its own ``finally``.
        if redis is not None and not delegated_to_legacy:
            try:
                await release_review_submission_lock(
                    redis,
                    installation_id=installation_id,
                    repo_full_name=f"{owner}/{repo}",
                    pr_number=pr_number,
                    head_sha=head_sha,
                )
            except Exception:
                logger.warning(
                    "Failed to release review submission lock review_id=%s",
                    review_id,
                    exc_info=True,
                )
