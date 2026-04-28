"""High-level orchestrator tying every stage together.

``ReviewEngine`` is the only class external callers need to drive a
full repository review. It is I/O-bound but CPU-light: every network
call flows through an injected ``RepoSource``, every stage is a pure
function operating on Pydantic models.

Typical usage::

    async with GitHubRepoSource() as source:
        engine = ReviewEngine(source=source)
        report = await engine.review(repo_url="https://github.com/owner/repo")

The FastAPI worker and the MCP server both sit on top of the same
instance; neither owns bespoke wiring for the review logic itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from decimal import Decimal

from app.review.external.analyzer import RuleRegistry, analyze_file, default_registry
from app.review.external.errors import BudgetExceededError, RepoAccessError
from app.review.external.models import (
    EngineConfig,
    EvaluationStatus,
    FileDescriptor,
    Finding,
    PrepassPlan,
    PrepassSignals,
    RepoRef,
    ReviewReport,
    Shard,
    ShardResult,
)
from app.review.external.prepass import run_prepass
from app.review.external.sharding import build_shards
from app.review.external.sources.base import RepoSource
from app.review.external.synthesis import synthesize

CheapPassModelResolver = Callable[[], str]


class ReviewEngine:
    """Coordinate prepass -> shard -> analyze -> synthesize over a repo."""

    def __init__(
        self,
        *,
        source: RepoSource,
        config: EngineConfig | None = None,
        rules: RuleRegistry | None = None,
        cheap_pass_model_resolver: CheapPassModelResolver | None = None,
    ) -> None:
        self._source = source
        self._config = config or EngineConfig()
        self._rules = rules or default_registry()
        self._resolve_cheap_pass = cheap_pass_model_resolver or _static_cheap_pass_model

    @property
    def config(self) -> EngineConfig:
        return self._config

    @property
    def rules(self) -> RuleRegistry:
        return self._rules

    async def resolve_repo(self, repo_url: str, ref: str | None = None) -> RepoRef:
        owner, repo = RepoRef.parse_url(repo_url)
        return await self._source.resolve_ref(owner, repo, ref)

    async def list_files(self, repo_ref: RepoRef) -> list[FileDescriptor]:
        return await self._source.list_files(
            repo_ref, max_files=self._config.max_files
        )

    async def prepass(
        self,
        repo_ref: RepoRef,
        files: list[FileDescriptor],
        *,
        sample_limit: int | None = None,
    ) -> tuple[PrepassSignals, PrepassPlan]:
        return await run_prepass(
            source=self._source,
            repo_ref=repo_ref,
            files=files,
            cheap_pass_model=self._resolve_cheap_pass(),
            sample_limit=(
                self._config.prepass_sample_limit
                if sample_limit is None
                else sample_limit
            ),
            sample_bytes=self._config.prepass_sample_bytes,
            concurrency=self._config.request_concurrency,
        )

    def plan_shards(
        self,
        files: Iterable[FileDescriptor],
        plan: PrepassPlan,
        *,
        excluded_paths: set[str] | None = None,
    ) -> list[Shard]:
        return build_shards(
            files,
            shard_count=plan.shard_count,
            shard_size_target=min(
                plan.shard_size_target, self._config.max_shard_files
            ),
            excluded_paths=excluded_paths,
        )

    async def analyze_shard(self, repo_ref: RepoRef, shard: Shard) -> ShardResult:
        """Analyze every file in ``shard`` and return a ``ShardResult``."""

        semaphore = asyncio.Semaphore(max(1, self._config.request_concurrency))

        async def _analyze_one(path: str) -> list[Finding]:
            async with semaphore:
                sample = await self._source.fetch_file(
                    repo_ref, path, max_bytes=self._config.analyze_sample_bytes
                )
            if not sample:
                return []
            rule_matches = analyze_file(path, sample, registry=self._rules)
            return [Finding.from_rule_match(match) for match in rule_matches]

        paths = list(shard.paths)[: self._config.max_analyze_files_per_shard]
        results = await asyncio.gather(*[_analyze_one(path) for path in paths])
        findings: list[Finding] = []
        for batch in results:
            findings.extend(batch)

        tokens_used, cost_usd = self._estimate_shard_usage(file_count=len(paths))
        return ShardResult(
            shard_key=shard.shard_key,
            status="done",
            file_count=len(paths),
            findings=findings,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
        )

    def synthesize(self, findings: Iterable[Finding]) -> list[Finding]:
        return synthesize(findings)

    async def review(
        self,
        *,
        repo_url: str,
        ref: str | None = None,
    ) -> ReviewReport:
        """Run every stage end-to-end and return a ``ReviewReport``.

        Stops early with ``status="partial"`` and a ``skip_reason`` on
        each unrun shard when the engine's token or cost budget would be
        exceeded.
        """

        try:
            repo_ref = await self.resolve_repo(repo_url, ref)
        except (RepoAccessError, ValueError) as exc:
            return _failed_report(
                repo_ref=None,
                message=str(exc),
                repo_url=repo_url,
                ref=ref or "",
            )

        files = await self.list_files(repo_ref)
        signals, plan = await self.prepass(repo_ref, files)
        excluded = set(signals.prompt_injection_paths) | set(signals.filler_paths)
        shards = self.plan_shards(files, plan, excluded_paths=excluded)

        estimated_tokens, estimated_cost = self._estimate_total_usage(
            file_count=len(files)
        )

        shard_results: list[ShardResult] = []
        used_tokens = 0
        used_cost = Decimal("0")
        truncated = False
        for shard in shards:
            shard_tokens, shard_cost = self._estimate_shard_usage(
                file_count=shard.file_count
            )
            if (
                used_tokens + shard_tokens > self._config.token_budget_cap
                or (used_cost + Decimal(str(shard_cost)))
                > Decimal(str(self._config.cost_budget_cap_usd))
            ):
                shard_results.append(
                    ShardResult(
                        shard_key=shard.shard_key,
                        status="skipped",
                        file_count=shard.file_count,
                        findings=[],
                        tokens_used=0,
                        cost_usd=0.0,
                        skip_reason="budget_cap_reached",
                    )
                )
                truncated = True
                continue
            result = await self.analyze_shard(repo_ref, shard)
            shard_results.append(result)
            used_tokens += result.tokens_used
            used_cost += Decimal(str(result.cost_usd))

        raw_findings: list[Finding] = []
        for result in shard_results:
            raw_findings.extend(result.findings)
        synthesized = synthesize(raw_findings)

        status: EvaluationStatus = "partial" if truncated else "complete"
        summary = (
            f"Completed external evaluation with {len(synthesized)} critical findings."
            if synthesized
            else "Completed external evaluation with no critical findings."
        )
        if truncated:
            summary += " Some shards were skipped after hitting the configured budget cap."

        return ReviewReport(
            repo_ref=repo_ref,
            status=status,
            file_count=len(files),
            inspected_file_count=signals.inspected_file_count,
            signals=signals,
            plan=plan,
            shards=shard_results,
            findings=synthesized,
            tokens_used=int(used_tokens),
            cost_usd=float(used_cost),
            estimated_tokens=estimated_tokens,
            estimated_cost_usd=estimated_cost,
            summary=summary,
            truncated=truncated,
        )

    def _estimate_shard_usage(self, *, file_count: int) -> tuple[int, float]:
        estimated_tokens = max(file_count * 120, 400)
        estimated_cost = (
            Decimal(estimated_tokens) / Decimal(1_000_000)
        ) * Decimal(str(self._config.price_per_1m_tokens_usd))
        return estimated_tokens, float(estimated_cost)

    def _estimate_total_usage(self, *, file_count: int) -> tuple[int, float]:
        estimated_tokens = max(file_count * 220, 800)
        estimated_cost = (
            Decimal(estimated_tokens) / Decimal(1_000_000)
        ) * Decimal(str(self._config.price_per_1m_tokens_usd))
        return estimated_tokens, float(estimated_cost)

    def assert_within_budget(
        self, *, projected_tokens: int, projected_cost_usd: float
    ) -> None:
        """Raise ``BudgetExceededError`` if the projection exceeds caps."""

        if projected_tokens > self._config.token_budget_cap:
            raise BudgetExceededError(
                kind="tokens",
                limit=float(self._config.token_budget_cap),
                projected=float(projected_tokens),
            )
        if projected_cost_usd > self._config.cost_budget_cap_usd:
            raise BudgetExceededError(
                kind="cost_usd",
                limit=float(self._config.cost_budget_cap_usd),
                projected=float(projected_cost_usd),
            )


def _static_cheap_pass_model() -> str:
    """Default resolver used when no catalog integration is provided."""

    return "heuristic-lite-v1"


def _failed_report(
    *,
    repo_ref: RepoRef | None,
    message: str,
    repo_url: str,
    ref: str,
) -> ReviewReport:
    owner, repo = ("unknown", "unknown")
    try:
        owner, repo = RepoRef.parse_url(repo_url)
    except ValueError:
        pass
    placeholder = repo_ref or RepoRef(
        owner=owner,
        repo=repo,
        ref=ref or "unknown",
        default_branch=ref or "unknown",
    )
    return ReviewReport(
        repo_ref=placeholder,
        status="failed",
        file_count=0,
        inspected_file_count=0,
        signals=PrepassSignals(),
        plan=PrepassPlan(
            service_tier="economy",
            shard_count=1,
            shard_size_target=1,
            cheap_pass_model="heuristic-lite-v1",  # nosec B106  # model tag, not a credential
            notes=(),
        ),
        shards=[],
        findings=[],
        tokens_used=0,
        cost_usd=0.0,
        estimated_tokens=0,
        estimated_cost_usd=0.0,
        summary=message,
        truncated=False,
    )
