"""db tightening — triggered_by_user_id on reviews, installation_id index on audits, deleted_at on users

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
Create Date: 2026-04-27 15:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i0j1k2l3m4n5"
down_revision: Union[str, None] = "h9i0j1k2l3m4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Track which user triggered a dashboard rerun (nullable — webhook reviews have no user)
    op.add_column(
        "reviews",
        sa.Column(
            "triggered_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )

    # Index installation_id on review_model_audits — it's a common filter but currently unindexed
    op.create_index(
        "review_model_audits_installation_id",
        "review_model_audits",
        ["installation_id"],
    )

    # GDPR soft-delete support on users
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "deleted_at")
    op.drop_index("review_model_audits_installation_id", table_name="review_model_audits")
    op.drop_column("reviews", "triggered_by_user_id")
