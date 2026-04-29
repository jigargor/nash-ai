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
