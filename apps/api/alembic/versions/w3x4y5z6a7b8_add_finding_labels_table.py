"""Add finding_labels table for human labeling (Phase 3).

Forward assumptions:
- The `reviews` table already exists with an `installation_id` column.
- The `users` table already exists.
- RLS is already globally active on this database (established in 1a2b3c4d5e6f).
- The `app.current_installation_id` session variable is set by the application
  before every DML query via `set_installation_context()`.

Rollback assumptions:
- Dropping the table cleanly removes the policy and indexes.
- No other table has a FK referencing `finding_labels`.
- The rollback is safe to run even if no rows have ever been labeled.

Revision ID: w3x4y5z6a7b8
Revises: v2w3x4y5z6a7
Create Date: 2026-05-02 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "w3x4y5z6a7b8"
down_revision: str | Sequence[str] | None = "v2w3x4y5z6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_CONTEXT = "nullif(current_setting('app.current_installation_id', true), '')::bigint"


def upgrade() -> None:
    op.create_table(
        "finding_labels",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=False),
        sa.Column("finding_index", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("labeled_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "labeled_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"]),
        sa.ForeignKeyConstraint(["labeled_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", "finding_index"),
    )
    op.create_index("finding_labels_review", "finding_labels", ["review_id"], unique=False)
    op.create_index("finding_labels_label", "finding_labels", ["label"], unique=False)

    # Enable RLS — tenant isolation mirrors the finding_outcomes pattern.
    # The policy checks installation_id directly (denormalized onto the row for
    # fast policy evaluation without a join).
    op.execute("ALTER TABLE finding_labels ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finding_labels FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY finding_labels_tenant_policy
        ON finding_labels
        FOR ALL
        USING (
            installation_id = {_TENANT_CONTEXT}
        )
        WITH CHECK (
            installation_id = {_TENANT_CONTEXT}
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS finding_labels_tenant_policy ON finding_labels")
    op.execute("ALTER TABLE finding_labels NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finding_labels DISABLE ROW LEVEL SECURITY")
    op.drop_index("finding_labels_label", table_name="finding_labels")
    op.drop_index("finding_labels_review", table_name="finding_labels")
    op.drop_table("finding_labels")
