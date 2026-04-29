---
name: rls-and-migrations-safety
description: "Safely change Alembic schema/RLS policies when modifying tenant or user tables, session context variables, policy SQL, or migration order/rollback behavior."
---

# rls-and-migrations-safety

## When to use

- Add/modify tables, columns, constraints, indexes, or foreign keys in `apps/api`.
- Enable or alter Row Level Security for installation-scoped or user-scoped tables.
- Change session context variables (`app.current_installation_id`, `app.current_user_github_id`) usage.
- Review migration chains that may affect worker/admin/background access paths.

## When not to use

- No-database frontend changes.
- Pure business-logic refactors that do not touch schema, policy SQL, or query scoping.
- Non-persistent runtime flags/config updates outside DB behavior.

## Preconditions

- Identify target tables and expected access actors (API request, webhook, worker, admin endpoint).
- Confirm which context setter is expected per actor (`set_installation_context` / `set_user_context`).
- Ensure Alembic revision ordering is correct and merge-head conflicts are resolved.
- Be ready to run migrations and tests locally/CI-like.

## Step-by-step workflow

1. **Design policy intent first**
   - Define who can `SELECT`, `INSERT`, `UPDATE`, `DELETE` per table.
   - Decide strict vs pass-through behavior when context variables are absent.
2. **Author migration with explicit SQL**
   - Use Alembic for schema and policy changes; avoid manual DB drift.
   - Include `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` where required.
   - Create/drop policies explicitly with clear names tied to table scope.
3. **Preserve worker/admin paths safely**
   - Verify background workflows that do not set user context still function as intended.
   - For temporary compatibility behavior, document why and where to tighten later.
4. **Align runtime context setters**
   - Ensure code paths touching protected tables call the correct context setter before queries.
   - Add explicit installation/user mismatch checks in API handlers where applicable.
5. **Validate rollback and head state**
   - Confirm downgrade statements remove policies/triggers in safe reverse order.
   - Verify migration head consistency and no accidental branch divergence.
6. **Test both allow and deny cases**
   - Test tenant A cannot read/write tenant B rows.
   - Test owner-only access for user key tables and audit logs.

## Anti-patterns

- Adding tenant/user tables without RLS while assuming application code alone is enough.
- Relying on implicit context propagation across sessions/transactions.
- Creating permissive policies (`USING (true)`) on sensitive tables without strict justification.
- Editing production schema manually without Alembic migration.
- Ignoring downgrade safety for policy and trigger changes.

## Concrete file anchors

- `apps/api/src/app/db/session.py`
- `apps/api/src/app/db/models.py`
- `apps/api/alembic/env.py`
- `apps/api/alembic/versions/1a2b3c4d5e6f_enable_rls_and_review_audit.py`
- `apps/api/alembic/versions/l3m4n5o6p7q8_user_table_rls.py`
- `apps/api/alembic/versions/7e8f9a0b1c2d_add_model_audit_and_provider.py`
- `apps/api/src/app/api/router.py`
- `apps/api/src/app/api/users.py`
- `.github/workflows/api-db-security.yml`

## Minimal verification checklist

- [ ] `uv run alembic upgrade head` succeeds.
- [ ] `uv run alembic current` shows expected head.
- [ ] Tenant/user deny-path tests fail closed (no cross-scope reads/writes).
- [ ] Worker/admin flows still operate with intended policy behavior.
- [ ] Migration downgrade path is syntactically valid and ordered safely.
