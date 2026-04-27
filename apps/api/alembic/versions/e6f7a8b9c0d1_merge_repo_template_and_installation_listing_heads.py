"""merge repo template and installation listing heads

Revision ID: e6f7a8b9c0d1
Revises: b2c3d4e5f6a7, d4e5f6a7b8c9
Create Date: 2026-04-27 02:05:00.000000

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = ("b2c3d4e5f6a7", "d4e5f6a7b8c9")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
