"""add total_deposit_usd to justlend position tables

Revision ID: 8a9b0c1d2e3f
Revises: 6f7a8b9c0d1e
Create Date: 2026-04-21 10:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a9b0c1d2e3f"
down_revision: Union[str, Sequence[str], None] = "6f7a8b9c0d1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names(schema="loan")


def _column_exists(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name, schema="loan")
    )


def upgrade() -> None:
    tables = (
        "justlend_current_user_positions",
        "justlend_user_position_snapshots",
        "justlend_position_snapshots",
    )
    for table_name in tables:
        if not _table_exists(table_name):
            continue
        if _column_exists(table_name, "total_deposit_usd"):
            continue
        op.add_column(
            table_name,
            sa.Column(
                "total_deposit_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
                server_default=sa.text("0"),
            ),
            schema="loan",
        )


def downgrade() -> None:
    tables = (
        "justlend_position_snapshots",
        "justlend_user_position_snapshots",
        "justlend_current_user_positions",
    )
    for table_name in tables:
        if not _table_exists(table_name):
            continue
        if not _column_exists(table_name, "total_deposit_usd"):
            continue
        op.drop_column(table_name, "total_deposit_usd", schema="loan")
