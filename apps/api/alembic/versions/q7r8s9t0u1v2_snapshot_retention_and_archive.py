"""Add snapshot lifecycle columns and RLS policy.

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-04-27 17:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "q7r8s9t0u1v2"
down_revision: str | Sequence[str] | None = "p6q7r8s9t0u1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_CONTEXT = (
    "coalesce("
    "nullif(current_setting('app.current_installation_id', true), '')::bigint, "
    "installation_id"
    ")"
)


def upgrade() -> None:
    op.add_column(
        "review_context_snapshots",
        sa.Column("installation_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "review_context_snapshots",
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "review_context_snapshots",
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "review_context_snapshots",
        sa.Column("r2_object_key", sa.Text(), nullable=True),
    )
    op.alter_column("review_context_snapshots", "snapshot_gz", existing_type=sa.LargeBinary(), nullable=True)

    op.execute(
        """
        UPDATE review_context_snapshots AS s
        SET installation_id = r.installation_id
        FROM reviews AS r
        WHERE r.id = s.review_id
        """
    )

    op.alter_column("review_context_snapshots", "installation_id", existing_type=sa.BigInteger(), nullable=False)
    op.create_foreign_key(
        "review_context_snapshots_installation_fk",
        "review_context_snapshots",
        "installations",
        ["installation_id"],
        ["installation_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "review_context_snapshots_installation_idx",
        "review_context_snapshots",
        ["installation_id"],
        unique=False,
    )
    op.create_index(
        "review_context_snapshots_expires_idx",
        "review_context_snapshots",
        ["expires_at"],
        unique=False,
    )

    op.execute("ALTER TABLE review_context_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE review_context_snapshots FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY review_context_snapshots_tenant_policy
        ON review_context_snapshots
        FOR ALL
        USING (installation_id = {TENANT_CONTEXT})
        WITH CHECK (installation_id = {TENANT_CONTEXT})
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS review_context_snapshots_tenant_policy ON review_context_snapshots"
    )
    op.execute("ALTER TABLE review_context_snapshots NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE review_context_snapshots DISABLE ROW LEVEL SECURITY")
    op.drop_index("review_context_snapshots_expires_idx", table_name="review_context_snapshots")
    op.drop_index("review_context_snapshots_installation_idx", table_name="review_context_snapshots")
    op.drop_constraint(
        "review_context_snapshots_installation_fk", "review_context_snapshots", type_="foreignkey"
    )
    op.alter_column("review_context_snapshots", "snapshot_gz", existing_type=sa.LargeBinary(), nullable=False)
    op.drop_column("review_context_snapshots", "r2_object_key")
    op.drop_column("review_context_snapshots", "archived_at")
    op.drop_column("review_context_snapshots", "expires_at")
    op.drop_column("review_context_snapshots", "installation_id")
