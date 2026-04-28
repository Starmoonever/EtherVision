"""add market asset fields to morpho v2 current

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-04-28 14:55:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    cols = sa.inspect(op.get_bind()).get_columns(table_name, schema="loan")
    return any(col["name"] == column_name for col in cols)


def upgrade() -> None:
    if not _column_exists("morpho_vault_v2_current", "market_asset"):
        op.add_column(
            "morpho_vault_v2_current",
            sa.Column("market_asset", sa.Numeric(precision=78, scale=0), nullable=True),
            schema="loan",
        )
    if not _column_exists("morpho_vault_v2_current", "market_asset_usd"):
        op.add_column(
            "morpho_vault_v2_current",
            sa.Column(
                "market_asset_usd", sa.Numeric(precision=78, scale=18), nullable=True
            ),
            schema="loan",
        )


def downgrade() -> None:
    if _column_exists("morpho_vault_v2_current", "market_asset_usd"):
        op.drop_column("morpho_vault_v2_current", "market_asset_usd", schema="loan")
    if _column_exists("morpho_vault_v2_current", "market_asset"):
        op.drop_column("morpho_vault_v2_current", "market_asset", schema="loan")
