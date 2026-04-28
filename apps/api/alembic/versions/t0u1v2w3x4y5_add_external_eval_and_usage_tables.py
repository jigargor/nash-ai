"""Add external evaluation and API usage tables.

Revision ID: t0u1v2w3x4y5
Revises: s9t0u1v2w3x4
Create Date: 2026-04-27 21:20:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "t0u1v2w3x4y5"
down_revision: str | Sequence[str] | None = "s9t0u1v2w3x4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_CONTEXT = "nullif(current_setting('app.current_installation_id', true), '')::bigint"


def upgrade() -> None:
    op.create_table(
        "api_usage_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"], ["installations.installation_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "api_usage_events_installation_service_time",
        "api_usage_events",
        ["installation_id", "service", "occurred_at"],
        unique=False,
    )

    op.create_table(
        "external_evaluations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("requested_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("repo_url", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("repo", sa.Text(), nullable=False),
        sa.Column("target_ref", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("estimated_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "estimated_cost_usd", sa.Numeric(precision=10, scale=6), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("token_budget_cap", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cost_budget_cap_usd", sa.Numeric(precision=10, scale=6), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("ack_required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("ack_confirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("findings_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_used", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), server_default=sa.text("0"), nullable=False),
        sa.Column("prepass_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["installation_id"], ["installations.installation_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "external_evaluations_installation_created",
        "external_evaluations",
        ["installation_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "external_evaluation_shards",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("external_evaluation_id", sa.BigInteger(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("shard_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("model_tier", sa.Text(), server_default=sa.text("'economy'"), nullable=False),
        sa.Column("file_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("findings_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_used", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "meta_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["external_evaluation_id"], ["external_evaluations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "external_evaluation_shards_eval_status",
        "external_evaluation_shards",
        ["external_evaluation_id", "status"],
        unique=False,
    )

    op.create_table(
        "external_evaluation_findings",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("external_evaluation_id", sa.BigInteger(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["external_evaluation_id"], ["external_evaluations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "external_evaluation_findings_eval_severity",
        "external_evaluation_findings",
        ["external_evaluation_id", "severity"],
        unique=False,
    )

    for table_name in (
        "api_usage_events",
        "external_evaluations",
        "external_evaluation_shards",
        "external_evaluation_findings",
    ):
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table_name}_tenant_policy
            ON {table_name}
            FOR ALL
            USING (installation_id = {_TENANT_CONTEXT})
            WITH CHECK (installation_id = {_TENANT_CONTEXT})
            """
        )


def downgrade() -> None:
    for table_name in (
        "external_evaluation_findings",
        "external_evaluation_shards",
        "external_evaluations",
        "api_usage_events",
    ):
        op.execute(f"DROP POLICY IF EXISTS {table_name}_tenant_policy ON {table_name}")
        op.execute(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")

    op.drop_index("external_evaluation_findings_eval_severity", table_name="external_evaluation_findings")
    op.drop_table("external_evaluation_findings")
    op.drop_index("external_evaluation_shards_eval_status", table_name="external_evaluation_shards")
    op.drop_table("external_evaluation_shards")
    op.drop_index("external_evaluations_installation_created", table_name="external_evaluations")
    op.drop_table("external_evaluations")
    op.drop_index("api_usage_events_installation_service_time", table_name="api_usage_events")
    op.drop_table("api_usage_events")
