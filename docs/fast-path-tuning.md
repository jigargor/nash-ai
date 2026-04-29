# Fast-Path Threshold Tuning

This document describes the adaptive fast-path threshold policy and guardrails.

## Policy

- Start at `0.90` (stored as `90`).
- Lower gradually with `step_down` (default `2` points) only when:
  - disagreement rate is below target low bound (`5%`), and
  - false-accept proxy and dismiss-rate guardrails are healthy.
- Hold or raise when:
  - disagreement rate exceeds target high bound (`15%`), or
  - false-accept/dismiss guardrails are exceeded.
- Emergency rollback/raise guardrail:
  - disagreement near `40%` or greater raises threshold immediately.

## Data Sources

- Fast-path decisions and stage audits: `review_model_audits`
- Outcome quality telemetry: `finding_outcomes` summary API logic
- Threshold configs and history:
  - `fast_path_threshold_configs`
  - `fast_path_threshold_history`

## Result Metadata Contract (v1)

Fast-path is a routing stage, not a findings-producing stage. Its audit metadata
must keep file-surface fields separate from risk labels and file-class counters.

- `decision`: `skip_review | light_review | full_review | high_risk_review`
- `risk_labels`: routing reasons such as `missing_confidence`
- `confidence_source`: `model` or `recovered` (alias/heuristic rescue path)
- `review_surface_paths`: explicit list of paths considered by fast-path
- `review_surface_count`: count derived from `review_surface_paths`
- `file_classes`: class histogram from diff classification (for example `config_only: 1`)
- `produces_findings`: always `false` for `fast_path`

Backward compatibility:

- Legacy `review_surface` remains populated for older UI readers.
- New readers should prefer `review_surface_paths` and `review_surface_count`.

## Missing-Confidence Guardrail

When providers omit confidence repeatedly, fast-path now attempts recovery before
escalating:

- alias-based recovery (`confidence_score`, `score`, `probability`, etc.)
- conservative heuristic from diff/file-class profile

If routing still lands on `full_review` with `missing_confidence`, runtime applies
an economy+tighter-budget guardrail to reduce avoidable cost/latency spikes while
preserving safety.

## Confidence Bug Guard

Fast-path confidence anomaly protection tracks repeated `0` confidence per:

- `installation_id`
- provider
- model

If repeated zero-confidence hits the configured limit (`zero_confidence_limit`, default `5`), routing escalates to full review to prevent rubber-stamping.

## Rollback

Admin rollback endpoint:

- `POST /admin/thresholds/rollback/{installation_id}`

This resets the threshold to the previous value from history and refreshes threshold cache.
