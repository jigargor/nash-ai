"""Add review_context_snapshots table

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
Create Date: 2026-04-27 20:00:00.000000

One row per review; stores a gzip-compressed JSON snapshot of the full LLM
input (diff, prompts, context bundle, resolved config, fetched files) for
offline eval replay and debugging.

Captured fire-and-forget in runner.py — a write failure never aborts a live
review.  Use evals/export_snapshot.py to export a row as an eval dataset dir.
"""

from alembic import op
import sqlalchemy as sa

revision = "m4n5o6p7q8r9"
down_revision = "l3m4n5o6p7q8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_context_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "captured_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("snapshot_gz", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id"),
    )
    op.create_index(
        "review_context_snapshots_review_id",
        "review_context_snapshots",
        ["review_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("review_context_snapshots_review_id", table_name="review_context_snapshots")
    op.drop_table("review_context_snapshots")
