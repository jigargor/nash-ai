"""add fast-path threshold and provider metric tables

Revision ID: d9e0f1a2b3c4
Revises: t0u1v2w3x4y5
Create Date: 2026-04-29 00:05:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "t0u1v2w3x4y5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_CONTEXT = "nullif(current_setting('app.current_installation_id', true), '')::bigint"


def upgrade() -> None:
    op.create_table(
        "fast_path_threshold_configs",
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("current_threshold", sa.Integer(), server_default=sa.text("90"), nullable=False),
        sa.Column("minimum_threshold", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("step_down", sa.Integer(), server_default=sa.text("2"), nullable=False),
        sa.Column("target_disagreement_low", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column("target_disagreement_high", sa.Integer(), server_default=sa.text("15"), nullable=False),
        sa.Column("max_false_accept_rate", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column("max_dismiss_rate", sa.Integer(), server_default=sa.text("25"), nullable=False),
        sa.Column("min_samples", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"], ["installations.installation_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("installation_id"),
    )

    op.create_table(
        "fast_path_threshold_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("previous_threshold", sa.Integer(), nullable=False),
        sa.Column("new_threshold", sa.Integer(), nullable=False),
        sa.Column(
            "disagreement_rate", sa.Numeric(10, 6), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("dismiss_rate", sa.Numeric(10, 6), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "false_accept_rate", sa.Numeric(10, 6), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("sample_size", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("action", sa.Text(), server_default=sa.text("'hold'"), nullable=False),
        sa.Column(
            "recorded_at",
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
        "fast_path_threshold_history_installation_time",
        "fast_path_threshold_history",
        ["installation_id", "recorded_at"],
        unique=False,
    )

    op.create_table(
        "provider_metric_configs",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "redact_user_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "allowed_dimensions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("provider"),
    )

    op.execute("ALTER TABLE fast_path_threshold_configs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE fast_path_threshold_configs FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY fast_path_threshold_configs_tenant_policy
        ON fast_path_threshold_configs
        FOR ALL
        USING (installation_id = {TENANT_CONTEXT})
        WITH CHECK (installation_id = {TENANT_CONTEXT});
        """
    )

    op.execute("ALTER TABLE fast_path_threshold_history ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE fast_path_threshold_history FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY fast_path_threshold_history_tenant_policy
        ON fast_path_threshold_history
        FOR ALL
        USING (installation_id = {TENANT_CONTEXT})
        WITH CHECK (installation_id = {TENANT_CONTEXT});
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS fast_path_threshold_history_tenant_policy ON fast_path_threshold_history"
    )
    op.execute("ALTER TABLE fast_path_threshold_history NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE fast_path_threshold_history DISABLE ROW LEVEL SECURITY")

    op.execute(
        "DROP POLICY IF EXISTS fast_path_threshold_configs_tenant_policy ON fast_path_threshold_configs"
    )
    op.execute("ALTER TABLE fast_path_threshold_configs NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE fast_path_threshold_configs DISABLE ROW LEVEL SECURITY")

    op.drop_table("provider_metric_configs")
    op.drop_index(
        "fast_path_threshold_history_installation_time", table_name="fast_path_threshold_history"
    )
    op.drop_table("fast_path_threshold_history")
    op.drop_table("fast_path_threshold_configs")
