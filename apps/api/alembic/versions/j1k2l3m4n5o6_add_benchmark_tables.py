"""add benchmark_runs, benchmark_results, and stage_duration_ms on review_model_audits

Revision ID: j1k2l3m4n5o6
Revises: i0j1k2l3m4n5
Create Date: 2026-04-27 15:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "j1k2l3m4n5o6"
down_revision: Union[str, None] = "i0j1k2l3m4n5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-stage timing for existing audit table
    op.add_column(
        "review_model_audits",
        sa.Column("stage_duration_ms", sa.Integer(), nullable=True),
    )

    # Benchmark run metadata
    op.create_table(
        "benchmark_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("model_config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("dataset_path", sa.Text(), nullable=False),
        sa.Column("triggered_by", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'running'")),
        sa.Column("totals_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("benchmark_runs_started_at", "benchmark_runs", ["started_at"])

    # Per-case benchmark results
    op.create_table(
        "benchmark_results",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=True),
        sa.Column("expected_findings", sa.Integer(), nullable=False),
        sa.Column("predicted_findings", sa.Integer(), nullable=False),
        sa.Column("true_positives", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("false_positives", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("false_negatives", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("cost_per_tp_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("stage_timings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["benchmark_runs.id"]),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("benchmark_results_run_id", "benchmark_results", ["run_id"])


def downgrade() -> None:
    op.drop_index("benchmark_results_run_id", table_name="benchmark_results")
    op.drop_table("benchmark_results")
    op.drop_index("benchmark_runs_started_at", table_name="benchmark_runs")
    op.drop_table("benchmark_runs")
    op.drop_column("review_model_audits", "stage_duration_ms")
