"""legacy revision bridge for environments stamped with older local revisions

Revision ID: e2a7c14d8f05
Revises: 24845454902f, 9c4f1a2b3d6e
Create Date: 2026-03-24 00:00:00.000000
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "e2a7c14d8f05"
down_revision: Union[str, Sequence[str], None] = (
    "24845454902f",
    "9c4f1a2b3d6e",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op bridge revision to reconnect legacy local alembic_version chains.
    return None


def downgrade() -> None:
    return None
