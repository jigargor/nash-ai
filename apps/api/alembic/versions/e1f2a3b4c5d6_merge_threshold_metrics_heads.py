"""compatibility head after threshold metrics

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-04-29 00:25:00.000000
"""

from typing import Sequence, Union


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    return None


def downgrade() -> None:
    return None
"""merge threshold and external-eval heads

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4, t0u1v2w3x4y5
Create Date: 2026-04-29 00:20:00.000000
"""

from typing import Sequence, Union


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = ("d9e0f1a2b3c4", "t0u1v2w3x4y5")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    return None


def downgrade() -> None:
    return None
