"""widen makerdao ratio numeric precision

Revision ID: f1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-04-25 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names(schema="loan")


def _column_exists(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name, schema="loan")
    )


def _alter_numeric(table_name: str, column_name: str, precision: int) -> None:
    if not _table_exists(table_name) or not _column_exists(table_name, column_name):
        return
    op.alter_column(
        table_name,
        column_name,
        type_=sa.Numeric(precision=precision, scale=18),
        existing_type=sa.Numeric(precision=20 if precision == 40 else 40, scale=18),
        existing_nullable=True,
        schema="loan",
    )


def upgrade() -> None:
    for table_name, columns in {
        "makerdao_ilks_current": (
            "liquidation_ratio",
            "liquidation_penalty",
            "stability_fee",
        ),
        "makerdao_current_vault_positions": ("liquidation_ratio",),
        "makerdao_system_urn_positions_current": ("liquidation_ratio",),
    }.items():
        for column_name in columns:
            _alter_numeric(table_name, column_name, 40)


def downgrade() -> None:
    for table_name, columns in {
        "makerdao_system_urn_positions_current": ("liquidation_ratio",),
        "makerdao_current_vault_positions": ("liquidation_ratio",),
        "makerdao_ilks_current": (
            "stability_fee",
            "liquidation_penalty",
            "liquidation_ratio",
        ),
    }.items():
        for column_name in columns:
            _alter_numeric(table_name, column_name, 20)
