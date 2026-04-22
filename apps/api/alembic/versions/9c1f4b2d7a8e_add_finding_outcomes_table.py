"""add finding outcomes table

Revision ID: 9c1f4b2d7a8e
Revises: 4d5e6f7a8b9c
Create Date: 2026-04-22 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9c1f4b2d7a8e"
down_revision: Union[str, Sequence[str], None] = "4d5e6f7a8b9c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_CONTEXT = "nullif(current_setting('app.current_installation_id', true), '')::bigint"


def upgrade() -> None:
    op.create_table(
        "finding_outcomes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=False),
        sa.Column("finding_index", sa.Integer(), nullable=False),
        sa.Column("github_comment_id", sa.BigInteger(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("outcome_confidence", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", "finding_index"),
    )
    op.create_index("finding_outcomes_review", "finding_outcomes", ["review_id"], unique=False)
    op.create_index("finding_outcomes_outcome", "finding_outcomes", ["outcome"], unique=False)

    op.execute("ALTER TABLE finding_outcomes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finding_outcomes FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY finding_outcomes_tenant_policy
        ON finding_outcomes
        FOR ALL
        USING (
            EXISTS (
                SELECT 1
                FROM reviews
                WHERE reviews.id = finding_outcomes.review_id
                  AND reviews.installation_id = {TENANT_CONTEXT}
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1
                FROM reviews
                WHERE reviews.id = finding_outcomes.review_id
                  AND reviews.installation_id = {TENANT_CONTEXT}
            )
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS finding_outcomes_tenant_policy ON finding_outcomes")
    op.execute("ALTER TABLE finding_outcomes NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE finding_outcomes DISABLE ROW LEVEL SECURITY")
    op.drop_index("finding_outcomes_outcome", table_name="finding_outcomes")
    op.drop_index("finding_outcomes_review", table_name="finding_outcomes")
    op.drop_table("finding_outcomes")
