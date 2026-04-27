"""security constraints: CHECK on provider/action, FK ON DELETE SET NULL for triggered_by_user_id

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-04-27 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "k2l3m4n5o6p7"
down_revision: Union[str, None] = "j1k2l3m4n5o6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VALID_PROVIDERS = "('anthropic', 'openai', 'gemini')"
_VALID_ACTIONS = "('created', 'updated', 'deleted')"


def upgrade() -> None:
    # Enforce allowed values at the DB level — app already validates these,
    # but CHECK constraints prevent silent data corruption via direct SQL.
    op.create_check_constraint(
        "user_provider_keys_provider_check",
        "user_provider_keys",
        f"provider IN {_VALID_PROVIDERS}",
    )
    op.create_check_constraint(
        "user_key_audit_log_provider_check",
        "user_key_audit_log",
        f"provider IN {_VALID_PROVIDERS}",
    )
    op.create_check_constraint(
        "user_key_audit_log_action_check",
        "user_key_audit_log",
        f"action IN {_VALID_ACTIONS}",
    )

    # Fix triggered_by_user_id FK: original migration omitted ON DELETE, so
    # deleting a user would fail referential integrity. SET NULL preserves the
    # review record while clearing the attribution.
    op.drop_constraint(
        "reviews_triggered_by_user_id_fkey",
        "reviews",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "reviews_triggered_by_user_id_fkey",
        "reviews",
        "users",
        ["triggered_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("reviews_triggered_by_user_id_fkey", "reviews", type_="foreignkey")
    op.create_foreign_key(
        "reviews_triggered_by_user_id_fkey",
        "reviews",
        "users",
        ["triggered_by_user_id"],
        ["id"],
    )
    op.drop_constraint("user_key_audit_log_action_check", "user_key_audit_log", type_="check")
    op.drop_constraint("user_key_audit_log_provider_check", "user_key_audit_log", type_="check")
    op.drop_constraint("user_provider_keys_provider_check", "user_provider_keys", type_="check")
