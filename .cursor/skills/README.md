# Skill Index: Hardening Plan Phases

This index maps project skills in `.cursor/skills` to the hardening phases so agents can pick the right guidance quickly.

## Phase Mapping

### P0: Security And Tenant Boundaries

- `backend-authz-tenant-isolation`
  - Primary for user identity binding, installation/repo scoping, and cross-tenant behavior.
- `rls-and-migrations-safety`
  - Primary for policy-tightening order, RLS migration safety, and caller-context correctness.
- `snapshot-data-governance`
  - Primary for snapshot redaction, retention, archival, and export access control.
- `worker-reliability-and-idempotency`
  - Secondary in P0 when retries/idempotency can cause duplicate side effects or stale states.

### P1: CI Hygiene And Web Security Stabilization

- `ci-security-hygiene`
  - Primary for quality gates, scanner wiring, conflict-marker checks, and workflow safety.
- `nextjs-bff-security`
  - Primary for auth/proxy hardening, trusted header model, middleware/proxy behavior, and session boundaries.
- `worker-reliability-and-idempotency`
  - Secondary for webhook dedup parity and operational reliability checks.

### P2: Performance And Refactor Work

- `worker-reliability-and-idempotency`
  - Primary when changing queue/worker throughput behavior and retry economics.
- `backend-authz-tenant-isolation`
  - Secondary guard to avoid reintroducing tenant leaks during refactors.
- `ci-security-hygiene`
  - Secondary to keep performance/refactor changes gated by the same safety baseline.

## Recommended Execution Order

1. `backend-authz-tenant-isolation`
2. `rls-and-migrations-safety`
3. `snapshot-data-governance`
4. `worker-reliability-and-idempotency`
5. `nextjs-bff-security`
6. `ci-security-hygiene`

## PR automation

- **fast-pr** — Quick PR title, body, checklist, and risks (~40 lines).
- **fastr-pr** — Same workflow as fast-pr; compact output for tooling and agents.
- **pr-closer** — Sweep PRs by branch patterns or branch pairs; merge when green, fix in Agent mode when not; optional `[skip-nash-review]` footer; ask when scope is ambiguous.
- **babysit** / **finishugh** — Single-PR merge readiness; finishugh adds merge-when-green.
- **bugfix-batch** (`.cursor/agents/bugfix-batch.md`) — Triage a list of fixes, parallel **bugfix/** worktrees (`bugfix/short-slug`), conservative model routing, then **gophrr** for allowlisted heads into `develop`.

## Quick Skill Selection

- Working in `apps/api/src/app/api/*` auth or tenant routes:
  - Start with `backend-authz-tenant-isolation`.
- Working in `apps/api/alembic/*` or `apps/api/src/app/db/*`:
  - Start with `rls-and-migrations-safety`.
- Working in `apps/api/src/app/agent/snapshot.py` or snapshot exports:
  - Start with `snapshot-data-governance`.
- Working in `apps/api/src/app/webhooks/*`, `apps/api/src/app/queue/*`, or runner reliability:
  - Start with `worker-reliability-and-idempotency`.
- Working in `apps/web/src/app/api/*`, `apps/web/src/middleware.ts`, session/proxy code:
  - Start with `nextjs-bff-security`.
- Working in `.github/workflows/*`, lockfiles, audits, or gate policy:
  - Start with `ci-security-hygiene`.
