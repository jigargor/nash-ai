---
name: backend-authz-tenant-isolation
description: "Enforce API auth + tenant/user isolation for FastAPI routes when touching headers, session context, installation_id/user_id filters, webhook/BFF identity flow, or cross-tenant 404/401 behavior."
---

# backend-authz-tenant-isolation

## When to use

- Add or modify FastAPI endpoints that read/write tenant-scoped or user-scoped data.
- Change identity propagation between web BFF and API (`X-Api-Key`, `X-User-Github-Id`).
- Diagnose cross-tenant data exposure, incorrect 401/404 behavior, or missing context guards.
- Update webhook or worker entry points that must run under an installation context.

## When not to use

- Pure UI-only styling/content changes with no API calls or auth/session implications.
- Non-sensitive telemetry/view rendering that never touches tenant/user-scoped records.
- One-off local scripts that do not run in server or worker runtime paths.

## Preconditions

- Confirm request identity source: GitHub App installation context and/or signed user session.
- Identify all touched tables and whether they are installation-scoped or user-scoped.
- Ensure route-level authentication remains enabled (`_verify_api_access` or equivalent guard).
- Verify you can run backend tests in `apps/api/tests`.

## Step-by-step workflow

1. **Map trust boundaries**
   - Define where identity is created (BFF session/webhook headers) and where it is consumed.
   - Keep secrets server-side only; do not expose installation/user tokens to frontend clients.
2. **Enforce API caller authentication**
   - Keep/extend API key verification and constant-time compare for shared API access keys.
   - Return `401` for invalid/missing auth material, not permissive fallbacks.
3. **Set tenant/user DB context before queries**
   - Call installation/user context setters before querying tenant/user RLS tables.
   - Scope selects/updates/deletes with explicit installation/user predicates where applicable.
4. **Preserve cross-tenant behavior**
   - Prevent existence leaks across tenants; prefer `404` for inaccessible tenant-owned records.
   - Ensure installation mismatch checks fail closed and do not silently coerce context.
5. **Check async side paths**
   - In webhook handlers and worker queue paths, set context before touching tenant rows.
   - Keep webhook acknowledgment fast; enqueue work rather than doing heavy inline processing.
6. **Add/adjust tests**
   - Add route-level tests for unauthorized access, mismatched installation/user context, and happy path.
   - Add regression tests for duplicate or stale context reuse if relevant.

## Anti-patterns

- Trusting client-provided installation IDs without validating against authenticated identity.
- Querying RLS-protected tables before calling `set_installation_context` / `set_user_context`.
- Returning `400` or `403` for webhook signature failure (must be `401`).
- Logging secrets, tokens, or raw key material.
- Exposing backend tokens or internal authorization headers to browser code.

## Concrete file anchors

- `apps/api/src/app/api/router.py`
- `apps/api/src/app/api/users.py`
- `apps/api/src/app/db/session.py`
- `apps/api/src/app/db/models.py`
- `apps/api/src/app/webhooks/router.py`
- `apps/api/src/app/webhooks/handlers.py`
- `apps/api/src/app/github/client.py`
- `apps/web/src/app/api/v1/[...path]/route.ts`
- `apps/web/src/lib/auth/session.ts`
- `apps/web/src/middleware.ts`

## Minimal verification checklist

- [ ] Unauthorized API requests return `401`.
- [ ] Cross-tenant fetch/update attempts do not return another tenant's data.
- [ ] User-scoped key endpoints only operate on the authenticated user context.
- [ ] Webhook signature validation still happens before payload processing.
- [ ] Relevant backend tests pass (authz + tenant/user isolation paths).
