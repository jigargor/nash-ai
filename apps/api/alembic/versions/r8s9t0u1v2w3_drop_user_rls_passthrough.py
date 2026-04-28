"""Drop users-table RLS passthrough fallback.

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-04-27 17:25:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "r8s9t0u1v2w3"
down_revision: str | Sequence[str] | None = "q7r8s9t0u1v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USERS_USING_STRICT = "github_id::text = nullif(current_setting('app.current_user_github_id', true), '')"

_KEYS_USING_STRICT = """
  user_id = (
    SELECT id FROM users
    WHERE github_id::text = nullif(current_setting('app.current_user_github_id', true), '')
    LIMIT 1
  )
""".strip()

_USERS_USING_PREVIOUS = """
  coalesce(
    nullif(current_setting('app.current_user_github_id', true), ''),
    github_id::text
  ) = github_id::text
""".strip()

_KEYS_USING_PREVIOUS = """
  user_id = (
    SELECT id FROM users
    WHERE github_id::text = coalesce(
      nullif(current_setting('app.current_user_github_id', true), ''),
      github_id::text
    )
    LIMIT 1
  )
""".strip()


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_isolation ON users")
    op.execute("DROP POLICY IF EXISTS users_update ON users")
    op.execute("DROP POLICY IF EXISTS users_delete ON users")
    op.execute(f"CREATE POLICY users_isolation ON users FOR SELECT USING ({_USERS_USING_STRICT})")
    op.execute(f"CREATE POLICY users_update ON users FOR UPDATE USING ({_USERS_USING_STRICT})")
    op.execute(f"CREATE POLICY users_delete ON users FOR DELETE USING ({_USERS_USING_STRICT})")

    op.execute("DROP POLICY IF EXISTS user_provider_keys_isolation ON user_provider_keys")
    op.execute(
        f"CREATE POLICY user_provider_keys_isolation ON user_provider_keys "
        f"FOR ALL USING ({_KEYS_USING_STRICT}) WITH CHECK ({_KEYS_USING_STRICT})"
    )

    op.execute("DROP POLICY IF EXISTS user_key_audit_log_isolation ON user_key_audit_log")
    op.execute(
        f"CREATE POLICY user_key_audit_log_isolation ON user_key_audit_log "
        f"FOR ALL USING ({_KEYS_USING_STRICT}) WITH CHECK ({_KEYS_USING_STRICT})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_isolation ON users")
    op.execute("DROP POLICY IF EXISTS users_update ON users")
    op.execute("DROP POLICY IF EXISTS users_delete ON users")
    op.execute(f"CREATE POLICY users_isolation ON users FOR SELECT USING ({_USERS_USING_PREVIOUS})")
    op.execute(f"CREATE POLICY users_update ON users FOR UPDATE USING ({_USERS_USING_PREVIOUS})")
    op.execute(f"CREATE POLICY users_delete ON users FOR DELETE USING ({_USERS_USING_PREVIOUS})")

    op.execute("DROP POLICY IF EXISTS user_provider_keys_isolation ON user_provider_keys")
    op.execute(
        f"CREATE POLICY user_provider_keys_isolation ON user_provider_keys "
        f"FOR ALL USING ({_KEYS_USING_PREVIOUS}) WITH CHECK ({_KEYS_USING_PREVIOUS})"
    )

    op.execute("DROP POLICY IF EXISTS user_key_audit_log_isolation ON user_key_audit_log")
    op.execute(
        f"CREATE POLICY user_key_audit_log_isolation ON user_key_audit_log "
        f"FOR ALL USING ({_KEYS_USING_PREVIOUS}) WITH CHECK ({_KEYS_USING_PREVIOUS})"
    )
