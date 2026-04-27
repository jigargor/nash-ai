"""add llm model catalog

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-04-27 12:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_model_catalog_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("version_hash", sa.Text(), nullable=False),
        sa.Column("catalog_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "source_hashes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("generated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("promoted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "llm_model_catalog_snapshots_version_hash",
        "llm_model_catalog_snapshots",
        ["version_hash"],
        unique=True,
    )
    op.create_index(
        "llm_model_catalog_snapshots_promoted_at",
        "llm_model_catalog_snapshots",
        ["promoted_at"],
        unique=False,
    )

    op.create_table(
        "llm_model_health",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("provider_status", sa.Text(), server_default="active", nullable=False),
        sa.Column("circuit_open", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("failure_class", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("last_success_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "model"),
    )
    op.create_index(
        "llm_model_health_provider_status",
        "llm_model_health",
        ["provider", "provider_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("llm_model_health_provider_status", table_name="llm_model_health")
    op.drop_table("llm_model_health")
    op.drop_index("llm_model_catalog_snapshots_promoted_at", table_name="llm_model_catalog_snapshots")
    op.drop_index("llm_model_catalog_snapshots_version_hash", table_name="llm_model_catalog_snapshots")
    op.drop_table("llm_model_catalog_snapshots")
