"""restore reviews.model_provider database default

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-04-26 16:00:00.000000

7e8f9a0b1c2d added model_provider with a temporary server default, then cleared it.
ORM inserts that omit the column then hit NOT NULL with no DB default. Restore
the PostgreSQL default so omitted columns and raw INSERTs stay valid.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "reviews",
        "model_provider",
        server_default=sa.text("'anthropic'"),
        existing_type=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "reviews",
        "model_provider",
        server_default=None,
        existing_type=sa.Text(),
        existing_nullable=False,
    )
