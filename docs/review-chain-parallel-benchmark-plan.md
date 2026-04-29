# Parallel Benchmark Plan: Legacy vs LangChain Review Paths

## Goal

Run both review approaches in parallel on successful reviews, measure quality/cost/latency, and decide when the LangChain path is safe to promote.

## Scope

- **Control path:** current `run_review` behavior (legacy runner path).
- **Candidate path:** LangChain/LangGraph path behind feature flags.
- **Mode:** shadow evaluation first (candidate does not post GitHub comments), then optional sampled dual-post experiments.

## Rollout Phases

1. **Phase 0 - Instrument only**
   - Keep production behavior unchanged.
   - Add shared experiment identifiers and metric collection.

2. **Phase 1 - Shadow on successful control reviews**
   - Trigger candidate run only after control review reaches `status=done`.
   - Candidate reads same review context snapshot and config hash.
   - Candidate output is persisted, never posted.

3. **Phase 2 - Sampled parallel live run**
   - Enable for low-risk repos/PRs with allowlist.
   - Candidate may post to a hidden sink (or draft-only comments) to verify end-to-end behavior.

4. **Phase 3 - Promotion gate**
   - Promote candidate for selected tenants only if SLOs pass for N days.

## Trigger Strategy

- Add a worker job, e.g. `benchmark_shadow_review`, enqueued by control path only when:
  - review completed successfully (`done`);
  - not rate-limited/circuit-open;
  - experiment flag enabled for installation/repo.
- The shadow job consumes:
  - `review_id`, `installation_id`, `owner/repo/pr/head_sha`;
  - control `run_id`;
  - context snapshot pointer (or compact payload id);
  - config/model resolution metadata.

## Data Model

Add a benchmark table to keep side-by-side results:

- `review_benchmark_runs`
  - `id`, `review_id`, `installation_id`, `control_run_id`, `candidate_run_id`
  - `experiment_key`, `status`
  - `started_at`, `completed_at`
  - `control_provider/model`, `candidate_provider/model`
  - `control_tokens`, `candidate_tokens`, `control_cost_usd`, `candidate_cost_usd`
  - `control_latency_ms`, `candidate_latency_ms`
  - `finding_overlap_score`, `precision_proxy`, `recall_proxy`
  - `notes_json`

Quality labels:
- use existing finding outcomes when available;
- reuse DeepEval overlap metric offline on snapshots for deterministic replay.

## Metric Set

Primary:
- latency p50/p95
- token and cost deltas
- finding overlap vs control
- downstream outcome delta (applied/dismissed/ignored)

Guardrails:
- schema validation failure rate
- anchor validation/drop rate
- rate-limit/quota fallback rate
- error rate by stage/provider

## Evaluation Protocol

1. For each eligible completed review, run candidate in shadow.
2. Compute:
   - overlap metric (`tp/fp/fn` at finding key level),
   - severity-weighted agreement,
   - confidence distribution drift.
3. Aggregate daily and by repo profile (language/framework/risk class).

## Security and Data Governance

- No token/secret values in benchmark records.
- Candidate run uses same tenant context rules as control.
- Snapshots used for replay remain redacted and retention-bound.
- No candidate GitHub writes in shadow mode.

## Operational Controls

- New flags:
  - `REVIEW_BENCHMARK_SHADOW_ENABLED`
  - `REVIEW_BENCHMARK_SAMPLE_RATE`
  - `REVIEW_BENCHMARK_ALLOWLIST`
- Backpressure:
  - benchmark jobs use dedicated ARQ queue or lower priority.
  - stop shadow runs when queue depth or provider errors exceed threshold.

## Success Criteria for Promotion

- Candidate p95 latency <= control p95 * 1.15
- Candidate cost <= control cost * 1.10
- No increase in severe false positives beyond agreed threshold
- Equal or better applied-outcome rate over a statistically meaningful window

## Immediate Implementation Tasks

1. Add benchmark DB migration/table.
2. Add worker job + enqueue hook after successful control review completion.
3. Add candidate runner entrypoint using existing snapshot replay path.
4. Add comparison utilities (finding key normalization + overlap score).
5. Add admin/API endpoint to view benchmark aggregates.
6. Add daily report cron summarizing control vs candidate.
