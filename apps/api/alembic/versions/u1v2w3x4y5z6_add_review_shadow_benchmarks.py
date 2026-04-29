"""Add review_shadow_benchmarks table for parallel control-vs-candidate telemetry.

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-04-28 21:35:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "u1v2w3x4y5z6"
down_revision: str | Sequence[str] | None = "t0u1v2w3x4y5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_CONTEXT = "nullif(current_setting('app.current_installation_id', true), '')::bigint"


def upgrade() -> None:
    op.create_table(
        "review_shadow_benchmarks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("control_run_id", sa.Text(), nullable=False),
        sa.Column("candidate_run_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("candidate_provider", sa.Text(), nullable=True),
        sa.Column("candidate_model", sa.Text(), nullable=True),
        sa.Column("control_findings", sa.Integer(), nullable=True),
        sa.Column("candidate_findings", sa.Integer(), nullable=True),
        sa.Column("finding_overlap", sa.Numeric(6, 4), nullable=True),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
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
        sa.ForeignKeyConstraint(["installation_id"], ["installations.installation_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id"),
    )
    op.create_index(
        "review_shadow_benchmarks_installation_created",
        "review_shadow_benchmarks",
        ["installation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "review_shadow_benchmarks_status",
        "review_shadow_benchmarks",
        ["status"],
        unique=False,
    )

    op.execute("ALTER TABLE review_shadow_benchmarks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE review_shadow_benchmarks FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY review_shadow_benchmarks_tenant_policy
        ON review_shadow_benchmarks
        FOR ALL
        USING (installation_id = {_TENANT_CONTEXT})
        WITH CHECK (installation_id = {_TENANT_CONTEXT})
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS review_shadow_benchmarks_tenant_policy ON review_shadow_benchmarks")
    op.execute("ALTER TABLE review_shadow_benchmarks NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE review_shadow_benchmarks DISABLE ROW LEVEL SECURITY")
    op.drop_index("review_shadow_benchmarks_status", table_name="review_shadow_benchmarks")
    op.drop_index(
        "review_shadow_benchmarks_installation_created",
        table_name="review_shadow_benchmarks",
    )
    op.drop_table("review_shadow_benchmarks")
