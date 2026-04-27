"""legacy makerdao revision bridge

Revision ID: e1f2a3b4c5d6
Revises: f1b2c3d4e5f6
Create Date: 2026-04-27 00:00:00.000000
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "f1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Bridge databases stamped with a legacy local MakerDAO revision."""


def downgrade() -> None:
    """No-op bridge downgrade."""
