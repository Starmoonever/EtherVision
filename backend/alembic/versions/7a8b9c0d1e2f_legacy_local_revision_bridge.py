"""legacy local revision bridge

Revision ID: 7a8b9c0d1e2f
Revises: 4d5e6f7a8b9c
Create Date: 2026-04-18 00:00:00.000000
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "7a8b9c0d1e2f"
down_revision: Union[str, Sequence[str], None] = "4d5e6f7a8b9c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op: bridge legacy local chain into repository chain.
    return None


def downgrade() -> None:
    return None
