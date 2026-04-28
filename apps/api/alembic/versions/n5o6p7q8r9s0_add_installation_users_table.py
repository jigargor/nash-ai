"""Add installation_users table for dashboard tenant membership.

Revision ID: n5o6p7q8r9s0
Revises: m4n5o6p7q8r9
Create Date: 2026-04-27
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n5o6p7q8r9s0"
down_revision: Union[str, Sequence[str], None] = "m4n5o6p7q8r9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "installation_users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True, nullable=False),
        sa.Column(
            "installation_id",
            sa.BigInteger(),
            sa.ForeignKey("installations.installation_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False, server_default=sa.text("'member'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("installation_id", "user_id", name="uq_installation_users_installation_user"),
    )
    op.create_index(
        "ix_installation_users_user_id",
        "installation_users",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_installation_users_user_id", table_name="installation_users")
    op.drop_table("installation_users")
