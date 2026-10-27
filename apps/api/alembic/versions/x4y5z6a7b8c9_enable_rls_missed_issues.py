"""Enable FORCE ROW LEVEL SECURITY on missed_issues (Phase 5 tenant isolation).

Forward assumptions:
- `missed_issues` exists (v2w3x4y5z6a7) with a NOT NULL, denormalized `installation_id`.
- The application sets `app.current_installation_id` (transaction-local) via
  `set_installation_context()` before every DML on this table.
- Rows with no matching tenant context become invisible (fail-closed): an unset or empty
  setting evaluates to NULL, so the predicate is never true.
- Enforcement only applies to roles WITHOUT `BYPASSRLS` and that are not superusers. See
  `apps/api/scripts/create_app_db_role.sql` for the least-privilege application role.

Rollback assumptions:
- Dropping the four policies and disabling RLS restores the pre-migration (unprotected)
  behaviour exactly; no data is modified in either direction.
- Safe to run when the table is empty or populated.

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-05-03 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "x4y5z6a7b8c9"
down_revision: str | Sequence[str] | None = "w3x4y5z6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_CONTEXT = "nullif(current_setting('app.current_installation_id', true), '')::bigint"
_TABLE = "missed_issues"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")

    # Idempotent re-create so a partially applied upgrade can be re-run safely.
    for command in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {_TABLE}_tenant_{command} ON {_TABLE}")

    op.execute(
        f"""
        CREATE POLICY {_TABLE}_tenant_select
        ON {_TABLE}
        FOR SELECT
        USING (installation_id = {_TENANT_CONTEXT});
        """
    )
    op.execute(
        f"""
        CREATE POLICY {_TABLE}_tenant_insert
        ON {_TABLE}
        FOR INSERT
        WITH CHECK (installation_id = {_TENANT_CONTEXT});
        """
    )
    op.execute(
        f"""
        CREATE POLICY {_TABLE}_tenant_update
        ON {_TABLE}
        FOR UPDATE
        USING (installation_id = {_TENANT_CONTEXT})
        WITH CHECK (installation_id = {_TENANT_CONTEXT});
        """
    )
    op.execute(
        f"""
        CREATE POLICY {_TABLE}_tenant_delete
        ON {_TABLE}
        FOR DELETE
        USING (installation_id = {_TENANT_CONTEXT});
        """
    )


def downgrade() -> None:
    for command in ("delete", "update", "insert", "select"):
        op.execute(f"DROP POLICY IF EXISTS {_TABLE}_tenant_{command} ON {_TABLE}")
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY")
