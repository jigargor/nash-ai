"""merge model audit and outcomes heads

Revision ID: a1b2c3d4e5f6
Revises: 7e8f9a0b1c2d, 9c1f4b2d7a8e
Create Date: 2026-04-26 08:50:00.000000

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = ("7e8f9a0b1c2d", "9c1f4b2d7a8e")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
