"""RLS on users, user_provider_keys, user_key_audit_log

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-04-27 19:00:00.000000

All three tables are user-scoped and contain sensitive data:
  - users: GitHub identity, soft-delete state
  - user_provider_keys: Fernet-encrypted third-party API keys
  - user_key_audit_log: key create/update/delete events

RLS policies use the app.current_user_github_id session variable set by
set_user_context() in db/session.py before each user-scoped query.

INSERT is unrestricted on all three tables so the OAuth upsert can create
new user rows without needing a pre-existing context. SELECT/UPDATE/DELETE
are restricted to the row owner.

"""

from typing import Sequence, Union

from alembic import op

revision: str = "l3m4n5o6p7q8"
down_revision: Union[str, None] = "k2l3m4n5o6p7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The coalesce/nullif guard makes the USING clause pass-through when the
# context variable is not set (empty string). This allows background jobs and
# admin operations that don't call set_user_context() to still read/write rows,
# while user-facing endpoints (which DO set context) are restricted to their own
# rows. Tighten to strict mode once all callers reliably set user context.
_USERS_USING = """
  coalesce(
    nullif(current_setting('app.current_user_github_id', true), ''),
    github_id::text
  ) = github_id::text
""".strip()

_KEYS_USING = """
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
    # ------------------------------------------------------------------ users
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")

    # SELECT / UPDATE / DELETE: own row only
    op.execute(f"CREATE POLICY users_isolation ON users FOR SELECT USING ({_USERS_USING})")
    op.execute(f"CREATE POLICY users_update ON users FOR UPDATE USING ({_USERS_USING})")
    op.execute(f"CREATE POLICY users_delete ON users FOR DELETE USING ({_USERS_USING})")
    # INSERT: unrestricted — OAuth upsert creates rows without pre-existing context
    op.execute("CREATE POLICY users_insert ON users FOR INSERT WITH CHECK (true)")

    # -------------------------------------------- user_provider_keys
    op.execute("ALTER TABLE user_provider_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_provider_keys FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY user_provider_keys_isolation ON user_provider_keys "
        f"FOR ALL USING ({_KEYS_USING}) WITH CHECK ({_KEYS_USING})"
    )

    # ------------------------------------------- user_key_audit_log
    op.execute("ALTER TABLE user_key_audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_key_audit_log FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY user_key_audit_log_isolation ON user_key_audit_log "
        f"FOR ALL USING ({_KEYS_USING}) WITH CHECK ({_KEYS_USING})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS user_key_audit_log_isolation ON user_key_audit_log")
    op.execute("ALTER TABLE user_key_audit_log DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS user_provider_keys_isolation ON user_provider_keys")
    op.execute("ALTER TABLE user_provider_keys DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS users_insert ON users")
    op.execute("DROP POLICY IF EXISTS users_delete ON users")
    op.execute("DROP POLICY IF EXISTS users_update ON users")
    op.execute("DROP POLICY IF EXISTS users_isolation ON users")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
