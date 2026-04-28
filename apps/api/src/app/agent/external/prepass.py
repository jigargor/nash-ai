"""Compatibility shim for the legacy prepass entry point.

Previously this module bundled the cheap-pass model selection (backed
by the LLM catalog) together with the prepass itself. The review engine
in :mod:`app.review.external` keeps those concerns separate, but tests
and other callers still monkeypatch this module's ``fetch_file_sample``
and ``_fast_pass_model`` symbols, so we preserve them here.
"""

from __future__ import annotations

from app.agent.external.github_public import PublicRepoRef, fetch_file_sample  # noqa: F401
from app.config import settings
from app.llm.catalog.loader import load_baseline_catalog
from app.llm.types import ModelRecord
from app.review.external.models import FileDescriptor, PrepassPlan, PrepassSignals
from app.review.external.prepass import run_prepass as _run_prepass_core
from app.review.external.sources.base import RepoSource
from app.review.external.sources.github import GitHubRepoSource


def _provider_is_configured(provider: str) -> bool:
    if provider == "gemini":
        return bool((settings.gemini_api_key or "").strip())
    if provider == "openai":
        return bool((settings.openai_api_key or "").strip())
    if provider == "anthropic":
        return bool((settings.anthropic_api_key or "").strip())
    return False


def _fast_pass_model() -> str:
    """Pick the cheapest active economy model across configured providers."""

    catalog = load_baseline_catalog()
    active_models: list[ModelRecord] = [
        record
        for record in catalog.models
        if record.status == "active"
        and record.tier == "economy"
        and _provider_is_configured(record.provider)
    ]
    if not active_models:
        return "heuristic-lite-v1"
    fallback_input_price_by_model = {"gemini-2.5-flash": 0.20}
    fallback_output_price_by_model = {"gemini-2.5-flash": 0.80}

    def sort_key(record: ModelRecord) -> tuple[float, float, int, str]:
        pricing = record.pricing
        input_per_1m = getattr(pricing, "input_per_1m", None)
        output_per_1m = getattr(pricing, "output_per_1m", None)
        input_price = (
            float(input_per_1m)
            if input_per_1m is not None
            else fallback_input_price_by_model.get(record.model, 10_000.0)
        )
        output_price = (
            float(output_per_1m)
            if output_per_1m is not None
            else fallback_output_price_by_model.get(record.model, 10_000.0)
        )
        return (input_price, output_price, -record.score, record.model)

    fastest = sorted(active_models, key=sort_key)[0]
    return f"{fastest.provider}:{fastest.model}"


class _ShimFetchSource:
    """Bridges legacy ``fetch_file_sample`` monkeypatch hooks to ``RepoSource``.

    Tests monkeypatch ``app.agent.external.prepass.fetch_file_sample`` to
    replace the fetch behaviour; this adapter re-routes that function
    through the engine's source protocol so ``run_prepass`` keeps using
    the current symbol without the tests needing to change.
    """

    async def resolve_ref(self, owner, repo, ref):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def list_files(self, repo_ref, *, max_files=3_000):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def fetch_file(self, repo_ref, path, *, max_bytes=5_000):  # type: ignore[no-untyped-def]
        return await fetch_file_sample(
            PublicRepoRef.from_model(repo_ref), path, max_bytes=max_bytes
        )

    async def aclose(self) -> None:
        return None


async def run_prepass(
    *,
    repo_ref_owner: str,
    repo_ref_repo: str,
    repo_ref_ref: str,
    files: list[FileDescriptor],
    fetch_samples_limit: int = 80,
    source: RepoSource | None = None,
) -> tuple[PrepassSignals, PrepassPlan]:
    """Legacy entry point used by the ARQ orchestrator.

    Uses the new core engine internally and, when no explicit source is
    provided, routes through the monkeypatchable module-level
    ``fetch_file_sample`` hook so existing tests keep working.
    """

    from app.review.external.models import RepoRef

    repo_ref = RepoRef(
        owner=repo_ref_owner,
        repo=repo_ref_repo,
        ref=repo_ref_ref,
        default_branch=repo_ref_ref,
    )
    active_source: RepoSource = source or _ShimFetchSource()
    return await _run_prepass_core(
        source=active_source,
        repo_ref=repo_ref,
        files=files,
        cheap_pass_model=_fast_pass_model(),
        sample_limit=fetch_samples_limit,
    )


async def run_prepass_with_github_source(
    *,
    repo_ref_owner: str,
    repo_ref_repo: str,
    repo_ref_ref: str,
    files: list[FileDescriptor],
    fetch_samples_limit: int = 80,
) -> tuple[PrepassSignals, PrepassPlan]:
    """Run the prepass against the live GitHub API."""

    async with GitHubRepoSource() as source:
        return await run_prepass(
            repo_ref_owner=repo_ref_owner,
            repo_ref_repo=repo_ref_repo,
            repo_ref_ref=repo_ref_ref,
            files=files,
            fetch_samples_limit=fetch_samples_limit,
            source=source,
        )


__all__ = [
    "PublicRepoRef",
    "fetch_file_sample",
    "load_baseline_catalog",
    "run_prepass",
    "run_prepass_with_github_source",
]
