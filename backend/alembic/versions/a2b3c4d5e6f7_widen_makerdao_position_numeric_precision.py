"""widen makerdao position numeric precision

Revision ID: a2b3c4d5e6f7
Revises: e1f2a3b4c5d6
Create Date: 2026-04-27 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SCALE_18_COLUMNS = {
    "makerdao_current_vault_positions": (
        "collateral_amount",
        "debt_amount",
        "liquidation_ratio",
        "health_factor",
    ),
    "makerdao_system_urn_positions_current": (
        "collateral_amount",
        "debt_amount",
        "liquidation_ratio",
        "health_factor",
    ),
    "makerdao_position_snapshots": (
        "collateral_amount",
        "debt_amount",
        "health_factor",
    ),
}

_SCALE_8_COLUMNS = {
    "makerdao_current_vault_positions": (
        "collateral_value_usd",
        "debt_value_usd",
        "liquidation_price_usd",
    ),
    "makerdao_system_urn_positions_current": (
        "collateral_value_usd",
        "debt_value_usd",
        "liquidation_price_usd",
    ),
    "makerdao_position_snapshots": (
        "collateral_value_usd",
        "debt_value_usd",
        "liquidation_price_usd",
    ),
}


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names(schema="loan")


def _column_exists(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name, schema="loan")
    )


def _alter_numeric(
    table_name: str,
    column_name: str,
    *,
    precision: int,
    scale: int,
    existing_precision: int,
) -> None:
    if not _table_exists(table_name) or not _column_exists(table_name, column_name):
        return
    op.alter_column(
        table_name,
        column_name,
        type_=sa.Numeric(precision=precision, scale=scale),
        existing_type=sa.Numeric(precision=existing_precision, scale=scale),
        existing_nullable=True,
        schema="loan",
    )


def upgrade() -> None:
    for table_name, columns in _SCALE_18_COLUMNS.items():
        for column_name in columns:
            _alter_numeric(
                table_name,
                column_name,
                precision=78,
                scale=18,
                existing_precision=40,
            )

    for table_name, columns in _SCALE_8_COLUMNS.items():
        for column_name in columns:
            _alter_numeric(
                table_name,
                column_name,
                precision=78,
                scale=8,
                existing_precision=30,
            )


def downgrade() -> None:
    for table_name, columns in _SCALE_8_COLUMNS.items():
        for column_name in columns:
            _alter_numeric(
                table_name,
                column_name,
                precision=30,
                scale=8,
                existing_precision=78,
            )

    for table_name, columns in _SCALE_18_COLUMNS.items():
        for column_name in columns:
            _alter_numeric(
                table_name,
                column_name,
                precision=40,
                scale=18,
                existing_precision=78,
            )
