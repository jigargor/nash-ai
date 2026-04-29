---
name: snapshot-data-governance
description: "Govern review context snapshot capture, redaction, retention, and export safety when touching snapshot schema/storage, debug artifacts, eval export, or privacy/compliance paths."
---

# snapshot-data-governance

## When to use

- Modify snapshot capture/storage/retrieval logic for review context.
- Add fields to snapshot payloads, debug artifacts, or eval export paths.
- Change retention, deletion, or privacy behavior for stored review context.
- Review data-handling risk for logs, payload dumps, and export endpoints.

## When not to use

- Routine UI changes unrelated to snapshot/debug/eval data.
- Pure LLM prompt tuning with no snapshot structure or storage changes.
- Infra changes that do not touch review context persistence/export.

## Preconditions

- Classify each new field as safe metadata vs potentially sensitive source content.
- Confirm snapshot writes remain fire-and-forget and cannot block live review completion.
- Identify where exported data can leave primary storage and who can access it.
- Ensure privacy/retention expectations remain consistent with project docs/rules.

## Step-by-step workflow

1. **Define data minimization boundary**
   - Keep only data required for replay/debugging/eval reproducibility.
   - Exclude secrets/tokens and avoid storing unnecessary raw sensitive content.
2. **Evolve schema safely**
   - Version snapshot schema explicitly and keep decode compatibility checks.
   - Use Alembic migrations for table/index changes, preserving one-row-per-review behavior.
3. **Keep capture non-blocking**
   - Ensure snapshot persistence failures do not fail active review execution.
   - Log failures without leaking payload contents.
4. **Harden retrieval/export paths**
   - Restrict snapshot read endpoints to authorized contexts.
   - Validate export destinations/paths and avoid traversal or unintended disclosure.
5. **Apply retention/deletion rules**
   - Confirm account deletion and review retention paths cover snapshot-like artifacts.
   - Keep governance decisions documented in privacy/GDPR docs.
6. **Verify with targeted tests**
   - Validate round-trip encode/decode, schema mismatch handling, and endpoint authorization.

## Anti-patterns

- Storing plaintext credentials, secrets, or tokens in snapshot/debug payloads.
- Blocking review completion on snapshot write success.
- Returning raw snapshot payloads from broadly accessible endpoints.
- Unversioned payload changes that break `from_bytes` decoding.
- Retaining snapshots indefinitely without documented retention policy.

## Concrete file anchors

- `apps/api/src/app/agent/snapshot.py`
- `apps/api/src/app/agent/runner.py`
- `apps/api/src/app/admin/router.py`
- `apps/api/src/app/db/models.py`
- `apps/api/alembic/versions/m4n5o6p7q8r9_add_review_context_snapshots.py`
- `apps/api/alembic/versions/4d5e6f7a8b9c_add_review_debug_artifacts.py`
- `apps/api/tests/test_snapshot.py`
- `apps/api/tests/test_agent_runner.py`
- `evals/export_snapshot.py`
- `docs/PRIVACY-GDPR.md`

## Minimal verification checklist

- [ ] Snapshot encode/decode tests pass, including schema mismatch handling.
- [ ] Review execution still succeeds if snapshot persistence fails.
- [ ] Snapshot read/export paths are access-controlled.
- [ ] No secrets are logged or persisted in added snapshot fields.
- [ ] Retention/deletion implications are reflected in docs/tests where needed.
