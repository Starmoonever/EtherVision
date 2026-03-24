"""drop price_in_base from compound v2 reserve snapshots

Revision ID: d4e5f6a7b8c9
Revises: c3e4f5a6b7c8
Create Date: 2026-03-24 16:35:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE loan.compound_v2_market_snapshot_reserves
        DROP COLUMN IF EXISTS price_in_base;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE loan.compound_v2_market_snapshot_reserves
        ADD COLUMN IF NOT EXISTS price_in_base NUMERIC(30, 8);
        """
    )
    op.execute(
        """
        UPDATE loan.compound_v2_market_snapshot_reserves
        SET price_in_base = price_usd
        WHERE price_in_base IS NULL;
        """
    )
    op.execute(
        """
        ALTER TABLE loan.compound_v2_market_snapshot_reserves
        ALTER COLUMN price_in_base SET NOT NULL;
        """
    )
