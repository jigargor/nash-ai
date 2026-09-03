# Nash AI Architecture

> Reconciled against the codebase as of the Wave-1 overhaul. Logical ownership map over existing paths; physical moves happen only when a module is rewritten.

## System overview

```
Webhook (HMAC) → ARQ queue → review_pipeline(pr_context, config, ports)
  → context packaging → ReAct agent → validation → refine/editor → delivery
  → telemetry events → finding outcomes → dashboard / evals goldens
```

Evals call the same `review_pipeline` with dry-run `DeliverySink` and cached `GitHubReader`. They never post unless `--post` is explicit and never for held-out PRs.

## Ownership map

| Logical folder | Owned paths | Public API |
|----------------|-------------|------------|
| **ingestion** | `app/webhooks/`, `app/queue/`, `app/github/{client,auth,utils}.py`, `app/agent/diff_parser.py`, `app/ingestion/` | `load_pr_context(...) -> PRContext`; webhook enqueue |
| **context-packaging** | `app/agent/context_builder.py`, `chunking.py`, `chunked_runtime.py`, `profiler*.py`, `prompt_compaction.py`, `snapshot.py` | `build_context_bundle`, `plan_chunks`, `profile_repo` |
| **agent-core** | `app/agent/loop.py`, `tools.py`, `finalize.py`, `fast_path.py`, `provider_clients.py`, `pipeline/` | `run_agent`, `finalize_review`, `review_pipeline` |
| **validation** | `app/agent/validator.py`, `anchors.py`, `dedupe.py`, `vendor_detect.py`, `normalization.py`, policy/repair helpers | `FindingValidator.validate`, `attach_anchor_metadata`, `dedupe_findings` |
| **prompts** | `app/agent/prompts/**` | `build_system_prompt` |
| **delivery** | `app/github/comments.py` → `app/delivery/` | `render_review`, `post_review` (via `DeliverySink`) |
| **infra** | `app/llm/**`, `config.py`, `db/**`, `alembic/`, `observability/{setup,sinks}.py`, worker, docker | catalog resolve, provider adapters, settings |
| **telemetry** | `app/telemetry/**`, `observability/{events,observer}.py` | event emit, finding-outcome classify/summarize |
| **frontend** | `apps/web/**`, `packages/shared-types/**` | Next dashboard + BFF |
| **evals** | `evals/**` | harness CLI, metrics, critics, pairwise |
| **shared core** (integrator only) | `app/agent/schema.py`, `app/categories.py`, `app/llm/types.py`, event names, `review_pipeline` seam, generated shared-types | Pydantic contracts |

Builders never edit another module's folder. Shared schema/core changes go through the integrator.

## Shared data model

Canonical schemas live in `apps/api/src/app/agent/schema.py` (extend, do not fork):

- **`Finding` / `ReviewResult` / `EditedReview`** — existing contracts; optional `finding_id` for delivery markers.
- **`PRContext`** — repo, pr_number, head/base SHA, title, body, commits, files_in_diff, files_at_head, commentable lines, review config snapshot.
- **`ReviewRunReport`** — findings, drops, tool trace, usage, cost, latency, exceptions, model IDs served.
- **`Diff`** — existing `FileInDiff` / `NumberedLine` from `diff_parser.py`.
- **`DropReason`** — validator drop codes; extended with `validator_error` for exception isolation.
- **`DroppedFinding`** — stage + reason + a JSON snapshot of the finding (never a re-validated `Finding`: rejected findings are often invalid by definition).

TypeScript mirrors are generated, not hand-written: `apps/api/scripts/export_shared_schema.py` → `packages/shared-types/generated/pydantic-schema.json` → `packages/shared-types/scripts/gen-types.mjs` → `packages/shared-types/src/generated.ts` (`pnpm gen:types`; CI job `shared-types-drift` fails on drift).

External-engine `Finding` in `app/review/external/models.py` remains a separate product shape; normalize at ingestion.

## Events

One schema for production and evals (`observability/events.py` + JSONL harness sink):

| Event | When |
|-------|------|
| `review.started` / `review.failed` / `review.posted` | Lifecycle |
| `stage.started` / `stage.finished` / `stage.degraded` | Stage isolation |
| `provider.fallback` | Attempt-chain hop |
| `llm.generation` / `llm.cache_hit` | Model calls |
| `tool.called` | Tool result (`success` reflects real outcome) |
| `finding.generated` / `finding.repaired` / `finding.dropped` | Finding lifecycle |
| `validation.rejected` | Validator reject |
| `delivery.rejected` | Per-comment 422 |
| `suggestion.accepted` / `suggestion.edited` / `suggestion.dismissed` | Outcome classifier |
| `finding.resolved` / `finding.ignored` | Outcome classifier |
| `budget.exceeded` | Token/cost/time ceiling |

## Degradation table (invariant)

| Failure | Behaviour |
|---------|-----------|
| Primary provider error (any class) | Next attempt in chain |
| Challenger / tie-break error | Skip debate; post validated draft |
| Editor error | Post validated draft |
| Per-comment GitHub 422 | Drop that comment (`delivery.rejected`); post the rest |
| Validator exception | Drop that finding (`validator_error`) |
| Audit / persistence error | Log; never fail the review |
| Tool error | Return error string to the model (already true) |

Enforced by `with_isolation` around stages; tested in unit + harness (`pipeline_errors` must be 0).

Where it is wired today:

- `app/agent/pipeline/review_pipeline.py` — every stage (`primary_review[provider/model]` attempt chain, `validation`, `editor`, `delivery`, `persistence.*`) runs under `with_isolation` with per-stage deadlines (`DEFAULT_STAGE_DEADLINES_S`). A malformed diff is recorded as `ingestion.parse_diff` and the review completes empty instead of crashing.
- `app/agent/runner.py` (production worker path, not yet replaced by the pipeline) — primary attempts fall through on any exception class; challenger and tie-break failures keep the validated draft; editor attempts fall through on any error and finally post the draft; `post_review` failure persists findings without a GitHub post; batched delivery falls back per comment on 422.
- `app/agent/loop.py` — in-loop time/token guard (`stage_deadline_s`, `max_loop_tokens`) and real `tool.called.success`.

## Pipeline stages and module boundaries (as landed)

| Stage | Module | Code |
|-------|--------|------|
| Ingest PR (meta, diff, commits, files at head, Files-API cross-check) | ingestion | `app/ingestion/pr_loader.py` |
| Skip/force tags | ingestion | `should_skip_review` (webhooks delegate to it) |
| Render diff + untrusted delimiters + PR description | context-packaging | `review_pipeline._build_user_prompt`, `prompts/system.build_initial_user_prompt` |
| ReAct loop + finalize (provider-neutral tool trace) | agent-core | `loop.py`, `finalize.py`, tools `read_file_range`, `list_directory`, head-SHA `search_codebase` |
| Repair → anchors → validate → policy → dedupe → config filters | validation | `repair.py`, `anchors.py`, `validator.py`, `policy.py`, `dedupe.py` |
| Diff-aware verifier (ex-blind challenger) / tie-break / editor | agent-core | `runner._build_challenger_prompt(diff_excerpt, tool_trace)`; value still unmeasured (needs live harness) |
| Render + post (human bodies, `<!-- nash:f:<id> -->`, batching, per-comment 422 fallback, synchronize dedupe, `delivery.request_changes` policy) | delivery | `app/delivery/comments.py`, `synchronize.py`, `ids.py` |
| Outcome events (`suggestion.accepted|edited|dismissed`, `finding.resolved|ignored`) | telemetry | `app/telemetry/finding_outcomes.py` → `observer.record_outcome` |
| Dashboard: withheld-findings panel, outcomes panel, scorecard, labels, missed-issue form | frontend | `apps/web/src/components/review/*`, `components/dashboard/outcome-scorecard.tsx` |
| Labels/missed issues → harness goldens | evals | `evals/export_snapshot.py` writes `expected.json` |

## Harness and gauntlet commands

All commands run from `apps/api` with `uv run python ../../evals/harness/<script>`; nothing ever posts to GitHub.

| Purpose | Command |
|---------|---------|
| Mutation-seeded goldens | `mutations.py --generate` |
| Fixtures only (stub when no API key) | `run.py --local-only --label <l>` |
| Tuning PRs (never held-out) | `run.py --limit-prs 6 --label <l>` |
| Fresh-context critic per module | `critic.py --module <m> --round N --label <l>` |
| Final gate (held-out, N=3, pairwise vs bare model) | `final_gate.py` |
| /loop driver | `loop.py --max-iterations 4` |
| Showcase | `show.py context|prompt|validate|render ...` |

`docs/STATUS.json` distinguishes `score` (LLM-backed critic over real model output) from `proxy_score` (offline plumbing evidence). Modules stay `smoke_only_blocked_no_llm_keys` until a provider key is present.

## Determinism rules

- Pinned model IDs; log `response.model` as served.
- Fixed `effort` per role on Claude 5-gen; `temperature=0` only where the provider accepts it (OpenAI/Gemini).
- Eval LLM cache: `evals/cache/llm/` keyed by sha256(provider, model, effort, system, messages, tools, schema).
- Eval GitHub fixtures: `evals/cache/github/` per `owner/repo#pr@sha`.
- Gate variance: mean ± sd over N=3 uncached runs.

## Budgets (initial)

| Tier | Changed lines | p95 latency | Input tokens | Cost (Sonnet 5) |
|------|---------------|-------------|--------------|-----------------|
| S | ≤200 | 90s | ≤200k | ≤$0.50 |
| M | ≤600 | 180s | ≤200k | ≤$0.50 |
| L | chunked | 420s | ≤600k | ≤$1.50 |

Also: ≤30k output (incl. thinking); alert at 80% of cost; ≤10 ReAct turns; ≤12 tool calls; ≤6 `fetch_file_content`; tool results truncated at 20k tokens; ARQ `job_timeout` 600s.

## Model pins (Wave 1)

| Role | Provider | Model |
|------|----------|-------|
| Primary | anthropic | `claude-sonnet-5` (`effort=medium`) |
| Fast-path / cheap | anthropic | `claude-haiku-4-5` |
| Tie-break / critic / judge | anthropic | `claude-opus-5` |
| Legacy fallback | anthropic | `claude-sonnet-4-6` |
| Balanced OpenAI | openai | `gpt-5.6-terra` |
| Frontier OpenAI | openai | `gpt-5.6-sol` |
| Economy OpenAI | openai | `gpt-5.6-luna` |
| Gemini fallback | gemini | `gemini-3.1-pro-preview` |
| Gemini economy | gemini | `gemini-3.6-flash` |

Retired/shutting down (catalog `shutdown_at`): `claude-sonnet-4-5` (2026-09-29), `gemini-2.5-*` (2026-10-16), `gpt-5-mini` dated snapshots (2026-12-11).

## Dependency policy

No new runtime dependency without a line here. Allowed core set:

- tree-sitter / tree-sitter-language-pack
- unidiff
- anthropic / openai SDKs (Gemini via OpenAI-compatible endpoint)
- langfuse (optional observability)
- FastAPI, SQLAlchemy, ARQ, Pydantic v2, httpx

## Existing components on this map

| Component | Placement |
|-----------|-----------|
| FindingValidator | validation |
| Stack profiler | context-packaging |
| Drop-reason telemetry | telemetry (+ harness JSONL) |
| max_mode challenger / tie-break | agent-core (Wave 3: measure or replace with diff-aware verifier) |
| Chunked review | context-packaging + agent-core |
| Golden evals | evals (harness replaces vacuous `run_eval` path) |
| FindingOutcome classifier | telemetry → Wave 4 dashboard |

## Ports

```python
class GitHubReader(Protocol):
    async def get_pull_request(...) -> dict: ...
    async def get_pull_request_diff(...) -> str: ...
    async def get_file_content(...) -> str: ...
    # ...

class DeliverySink(Protocol):
    async def post(self, result: ReviewResult, *, commit_sha: str) -> DeliveryResult: ...

class Persistence(Protocol):
    async def mark_running / mark_done / record_audit / seed_outcomes(...): ...
```

Worker wires live GitHub + DB. Harness wires cached reader + dry-run sink + no-op or file persistence.
