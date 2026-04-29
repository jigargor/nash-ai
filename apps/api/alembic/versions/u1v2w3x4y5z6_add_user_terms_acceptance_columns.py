"""add user terms acceptance columns

Revision ID: u1v2w3x4y5z6
Revises: e1f2a3b4c5d6
Create Date: 2026-04-29 00:45:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "u1v2w3x4y5z6"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("accepted_terms_version", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("accepted_terms_at", sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "accepted_terms_at")
    op.drop_column("users", "accepted_terms_version")
