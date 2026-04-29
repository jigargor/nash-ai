# Provider Usage Metrics and Redaction

## Endpoints

- `GET /api/v1/usage/metrics`
- `GET /api/v1/usage/scorecard`

## Metrics Endpoint

`GET /api/v1/usage/metrics?installation_id=...&provider=...&group_by=provider|model|stage&days=7`

Returns aggregate call counts and token usage by the requested dimension.

Optional:

- `include_metadata=true` returns one redacted metadata sample.

## Redaction Rules

Provider-specific redaction config is stored in `provider_metric_configs`:

- `enabled`
- `redact_user_fields`
- `allowed_dimensions`

All user-level keys are redacted before response serialization. Default redaction includes fields like `user_id`, `github_id`, `email`, and related actor keys.

## Scorecard Endpoint

`GET /api/v1/usage/scorecard?installation_id=...&days=14`

Returns:

- fast-path acceptance rate
- disagreement rate
- dismiss/ignore/useful rates
- target disagreement range used for Goldilocks calibration

## RLS Feasibility Notes

User-level redaction does not replace tenant isolation.

- Keep tenant-level RLS for operational Postgres tables.
- Use aggregated/redacted read models to avoid user-level RLS dependencies in dashboard metrics.
- If strict no-RLS is required for analytics serving, use an isolated analytics sidecar with only pre-aggregated redacted facts and strict API-level tenant scoping.
