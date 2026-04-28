"""Add unique review constraint for installation, PR number, and head SHA.

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-04-27 17:48:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "s9t0u1v2w3x4"
down_revision: str | Sequence[str] | None = "r8s9t0u1v2w3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the latest row and remove historical duplicates before adding the constraint.
    op.execute(
        """
        WITH ranked_reviews AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY installation_id, pr_number, pr_head_sha
                    ORDER BY id DESC
                ) AS row_rank
            FROM reviews
        )
        DELETE FROM reviews AS review_row
        USING ranked_reviews
        WHERE review_row.id = ranked_reviews.id
          AND ranked_reviews.row_rank > 1
        """
    )
    op.create_unique_constraint(
        "reviews_installation_pr_head_unique",
        "reviews",
        ["installation_id", "pr_number", "pr_head_sha"],
    )


def downgrade() -> None:
    op.drop_constraint("reviews_installation_pr_head_unique", "reviews", type_="unique")
