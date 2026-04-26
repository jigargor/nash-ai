"""allow installation read listing

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-26 17:30:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_CONTEXT = "nullif(current_setting('app.current_installation_id', true), '')::bigint"


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS installations_tenant_policy ON installations")
    op.execute(
        """
        CREATE POLICY installations_read_policy
        ON installations
        FOR SELECT
        USING (true);
        """
    )
    op.execute(
        f"""
        CREATE POLICY installations_write_policy
        ON installations
        FOR ALL
        USING (installation_id = {TENANT_CONTEXT})
        WITH CHECK (installation_id = {TENANT_CONTEXT});
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS installations_write_policy ON installations")
    op.execute("DROP POLICY IF EXISTS installations_read_policy ON installations")
    op.execute(
        f"""
        CREATE POLICY installations_tenant_policy
        ON installations
        FOR ALL
        USING (installation_id = {TENANT_CONTEXT})
        WITH CHECK (installation_id = {TENANT_CONTEXT});
        """
    )
