"""legacy local revision bridge for environments stamped with 9c4f1a2b3d6e

Revision ID: 9c4f1a2b3d6e
Revises:
Create Date: 2026-03-27 12:30:00.000000
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "9c4f1a2b3d6e"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op bridge revision to reconnect legacy local alembic_version chains.
    return None


def downgrade() -> None:
    return None
