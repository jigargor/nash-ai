# Stale Review Recovery Runbook

This runbook covers operator handling for reviews that remain `queued` or `running` longer than expected.

## Automatic Recovery

- The worker now reconciles stale reviews at startup and on a recurring cron interval.
- `running` reviews older than the configured threshold are marked `failed`.
- Optional `queued` recovery can mark long-stuck queued reviews as `failed`.

Relevant settings:

- `STALE_REVIEW_RECOVERY_ENABLED`
- `STALE_REVIEW_RECOVERY_RUNNING_MAX_AGE_MINUTES`
- `STALE_REVIEW_RECOVERY_QUEUED_ENABLED`
- `STALE_REVIEW_RECOVERY_QUEUED_MAX_AGE_MINUTES`
- `STALE_REVIEW_RECOVERY_CRON_MINUTES`
- `REVIEW_FORCE_ACTIONS_ENABLED`

## Manual Recovery (Dashboard)

When `REVIEW_FORCE_ACTIONS_ENABLED=true`, installation admins can use:

- `Mark failed`: force terminal state for stale in-flight jobs.
- `Force requeue`: enqueue a new worker job for the review.

Normal `Re-run review` remains available for terminal states.

## Lock Collision Behavior

If a recovery action returns conflict:

- The response indicates submission lock contention for the PR head.
- Retry after the lock window (15 minutes), or mark the stale run failed first.

## Verification Checklist

1. Confirm review status transitions to `failed` or `queued` after action.
2. Confirm `debug_artifacts.recovery` or `debug_artifacts.manual_recovery` is present.
3. Confirm the review eventually reaches a terminal state (`done`, `failed`, or `skipped`).
4. If queue health is suspect, inspect `/health/queue`.
