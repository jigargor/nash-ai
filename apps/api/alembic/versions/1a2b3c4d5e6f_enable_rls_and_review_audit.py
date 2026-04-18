"""enable rls and review audit

Revision ID: 1a2b3c4d5e6f
Revises: 03899c5db8ed
Create Date: 2026-04-17 20:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = "03899c5db8ed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TENANT_CONTEXT = "nullif(current_setting('app.current_installation_id', true), '')::bigint"


def upgrade() -> None:
    op.create_table(
        "review_audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("old_row", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_row", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("changed_by_installation_id", sa.BigInteger(), nullable=True),
        sa.Column("changed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "review_audit_log_review_id_idx",
        "review_audit_log",
        ["review_id", "changed_at"],
        unique=False,
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION app_capture_review_audit()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                INSERT INTO review_audit_log (review_id, installation_id, operation, old_row, changed_by_installation_id)
                VALUES (OLD.id, OLD.installation_id, TG_OP, to_jsonb(OLD), {TENANT_CONTEXT});
                RETURN OLD;
            END IF;

            INSERT INTO review_audit_log (review_id, installation_id, operation, old_row, new_row, changed_by_installation_id)
            VALUES (NEW.id, NEW.installation_id, TG_OP, to_jsonb(OLD), to_jsonb(NEW), {TENANT_CONTEXT});
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER reviews_audit_trigger
        AFTER INSERT OR UPDATE OR DELETE ON reviews
        FOR EACH ROW
        EXECUTE FUNCTION app_capture_review_audit();
        """
    )

    op.execute("ALTER TABLE installations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE repo_configs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reviews ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE installations FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE repo_configs FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reviews FORCE ROW LEVEL SECURITY")

    op.execute(
        f"""
        CREATE POLICY installations_tenant_policy
        ON installations
        FOR ALL
        USING (installation_id = {TENANT_CONTEXT})
        WITH CHECK (installation_id = {TENANT_CONTEXT});
        """
    )
    op.execute(
        f"""
        CREATE POLICY repo_configs_tenant_policy
        ON repo_configs
        FOR ALL
        USING (installation_id = {TENANT_CONTEXT})
        WITH CHECK (installation_id = {TENANT_CONTEXT});
        """
    )
    op.execute(
        f"""
        CREATE POLICY reviews_tenant_policy
        ON reviews
        FOR ALL
        USING (installation_id = {TENANT_CONTEXT})
        WITH CHECK (installation_id = {TENANT_CONTEXT});
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS reviews_tenant_policy ON reviews")
    op.execute("DROP POLICY IF EXISTS repo_configs_tenant_policy ON repo_configs")
    op.execute("DROP POLICY IF EXISTS installations_tenant_policy ON installations")
    op.execute("ALTER TABLE reviews NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE repo_configs NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE installations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reviews DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE repo_configs DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE installations DISABLE ROW LEVEL SECURITY")

    op.execute("DROP TRIGGER IF EXISTS reviews_audit_trigger ON reviews")
    op.execute("DROP FUNCTION IF EXISTS app_capture_review_audit")
    op.drop_index("review_audit_log_review_id_idx", table_name="review_audit_log")
    op.drop_table("review_audit_log")
