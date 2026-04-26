"""add model audit and provider

Revision ID: 7e8f9a0b1c2d
Revises: 4d5e6f7a8b9c
Create Date: 2026-04-26 08:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "7e8f9a0b1c2d"
down_revision: Union[str, Sequence[str], None] = "4d5e6f7a8b9c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_CONTEXT = "nullif(current_setting('app.current_installation_id', true), '')::bigint"


def upgrade() -> None:
    op.add_column("reviews", sa.Column("model_provider", sa.Text(), server_default="anthropic", nullable=False))
    op.alter_column("reviews", "model_provider", server_default=None)

    op.create_table(
        "review_model_audits",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("findings_count", sa.Integer(), nullable=True),
        sa.Column("accepted_findings_count", sa.Integer(), nullable=True),
        sa.Column("conflict_score", sa.Integer(), nullable=True),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "review_model_audits_review_stage",
        "review_model_audits",
        ["review_id", "stage"],
        unique=False,
    )
    op.create_index(
        "review_model_audits_provider_model",
        "review_model_audits",
        ["provider", "model"],
        unique=False,
    )

    op.execute("ALTER TABLE review_audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE review_audit_log FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY review_audit_log_tenant_policy
        ON review_audit_log
        FOR ALL
        USING (installation_id = {TENANT_CONTEXT})
        WITH CHECK (installation_id = {TENANT_CONTEXT});
        """
    )

    op.execute("ALTER TABLE review_model_audits ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE review_model_audits FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY review_model_audits_tenant_policy
        ON review_model_audits
        FOR ALL
        USING (installation_id = {TENANT_CONTEXT})
        WITH CHECK (installation_id = {TENANT_CONTEXT});
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS review_model_audits_tenant_policy ON review_model_audits")
    op.execute("ALTER TABLE review_model_audits NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE review_model_audits DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS review_audit_log_tenant_policy ON review_audit_log")
    op.execute("ALTER TABLE review_audit_log NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE review_audit_log DISABLE ROW LEVEL SECURITY")

    op.drop_index("review_model_audits_provider_model", table_name="review_model_audits")
    op.drop_index("review_model_audits_review_stage", table_name="review_model_audits")
    op.drop_table("review_model_audits")
    op.drop_column("reviews", "model_provider")
