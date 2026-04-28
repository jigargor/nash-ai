"""Add github_review_node_id column on reviews.

Revision ID: p6q7r8s9t0u1
Revises: n5o6p7q8r9s0
Create Date: 2026-04-27 16:54:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p6q7r8s9t0u1"
down_revision: str | Sequence[str] | None = "n5o6p7q8r9s0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column("github_review_node_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("reviews", "github_review_node_id")
