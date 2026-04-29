---
name: worker-reliability-and-idempotency
description: "Strengthen ARQ webhook-to-worker reliability and idempotency when changing enqueue logic, duplicate suppression, retry/recovery semantics, or review status transitions."
---

# worker-reliability-and-idempotency

## When to use

- Change webhook enqueue behavior for review or outcome classification jobs.
- Modify worker job handlers, retry behavior, or stale-running recovery.
- Fix duplicate review posts/comments caused by retries, races, or redelivery.
- Tune circuit breaker/rate-limit interactions around queue admission.

## When not to use

- Non-worker frontend UX changes.
- Static docs updates with no queueing/runtime behavior impact.
- Pure query/read-only reporting that does not alter job lifecycle.

## Preconditions

- Identify idempotency keys (delivery ID, installation/repo/PR/head SHA, review status).
- Define expected behavior for retry, replay, and crash recovery.
- Confirm enqueue-time and execute-time duplicate guards remain in place.
- Ensure observability signals exist for queued/running/failed/recovered states.

## Step-by-step workflow

1. **Map lifecycle states**
   - Trace `webhook -> enqueue -> worker start -> running -> completed/failed`.
   - Record where failures can duplicate work (network retry, worker crash, race conditions).
2. **Protect ingestion path**
   - Deduplicate webhook deliveries using delivery ID with bounded TTL.
   - Keep webhook processing fast and enqueue-only for long work.
3. **Protect execution path**
   - Check DB for existing non-failed review for same head SHA before creating new work.
   - Ensure status transitions are monotonic and persisted in short transactions.
4. **Define retry semantics**
   - Retries should be safe replays, not duplicate side effects.
   - Make side effects (posting comments/status) conditional on persisted idempotent state.
5. **Handle crash recovery**
   - Mark stale `running` reviews as failed after timeout window.
   - Emit recovery logs/metrics to track reliability regressions.
6. **Test failure modes explicitly**
   - Add tests for duplicate webhook delivery, race conditions, and worker restart recovery.

## Anti-patterns

- Posting GitHub side effects before idempotency state is committed.
- Long transactions that mix network I/O and DB writes.
- No stale-running cleanup, leaving reviews permanently `running`.
- Using unbounded retry loops without circuit-breaker/rate-limit checks.
- Treating webhook redelivery as a new review request without deduplication.

## Concrete file anchors

- `apps/api/src/app/webhooks/router.py`
- `apps/api/src/app/webhooks/handlers.py`
- `apps/api/src/app/queue/worker.py`
- `apps/api/src/app/queue/recovery.py`
- `apps/api/src/app/agent/runner.py`
- `apps/api/src/app/ratelimit.py`
- `apps/api/src/app/llm/circuit_breaker.py`
- `apps/api/tests/test_integration_review_flow.py`
- `apps/api/tests/test_agent_runner.py`
- `apps/api/tests/test_api_router.py`

## Minimal verification checklist

- [ ] Duplicate webhook delivery does not create duplicate active reviews.
- [ ] Retries/replays remain side-effect safe (no duplicate comments for same review state).
- [ ] Stale running recovery marks old jobs failed as expected.
- [ ] Circuit breaker/rate limiting gates still apply before expensive work.
- [ ] Worker startup and queue paths pass relevant tests.
