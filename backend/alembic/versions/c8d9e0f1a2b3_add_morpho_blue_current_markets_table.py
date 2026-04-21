"""add morpho blue current markets table

Revision ID: c8d9e0f1a2b3
Revises: a7b8c9d0e1f2
Create Date: 2026-04-21 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names(schema="loan")


def _index_exists(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name, schema="loan")
    )


def upgrade() -> None:
    # api/morpho/markets相关：当前市场快照缓存表（供分页 markets 接口快速读取）
    if not _table_exists("morpho_blue_current_markets"):
        op.create_table(
            "morpho_blue_current_markets",
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("loan_symbol", sa.Text(), nullable=True),
            sa.Column("loan_address", sa.Text(), nullable=False),
            sa.Column("loan_decimals", sa.Integer(), nullable=True),
            sa.Column("collateral_symbol", sa.Text(), nullable=True),
            sa.Column("collateral_address", sa.Text(), nullable=True),
            sa.Column("collateral_decimals", sa.Integer(), nullable=True),
            sa.Column("oracle", sa.Text(), nullable=True),
            sa.Column("irm", sa.Text(), nullable=True),
            sa.Column("lltv_raw", sa.Numeric(precision=78, scale=0), nullable=True),
            sa.Column(
                "total_supply_assets", sa.Numeric(precision=78, scale=0), nullable=True
            ),
            sa.Column(
                "total_supply_shares", sa.Numeric(precision=78, scale=0), nullable=True
            ),
            sa.Column(
                "total_borrow_assets", sa.Numeric(precision=78, scale=0), nullable=True
            ),
            sa.Column(
                "total_borrow_shares", sa.Numeric(precision=78, scale=0), nullable=True
            ),
            sa.Column("last_update", sa.BigInteger(), nullable=True),
            sa.Column("fee_raw", sa.Numeric(precision=78, scale=0), nullable=True),
            sa.Column(
                "total_market_size_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=True,
            ),
            sa.Column(
                "source",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'morpho-blue-api'"),
            ),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("market_id"),
            schema="loan",
        )

    # 地址字段按仓库标准使用 STORAGE PLAIN
    op.execute(
        sa.text(
            "ALTER TABLE loan.morpho_blue_current_markets "
            "ALTER COLUMN loan_address SET STORAGE PLAIN"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE loan.morpho_blue_current_markets "
            "ALTER COLUMN collateral_address SET STORAGE PLAIN"
        )
    )

    if not _index_exists(
        "morpho_blue_current_markets", "idx_morpho_blue_current_markets_market_id"
    ):
        op.create_index(
            "idx_morpho_blue_current_markets_market_id",
            "morpho_blue_current_markets",
            ["market_id"],
            unique=True,
            schema="loan",
        )
    if not _index_exists(
        "morpho_blue_current_markets", "idx_morpho_blue_current_markets_loan_address"
    ):
        op.create_index(
            "idx_morpho_blue_current_markets_loan_address",
            "morpho_blue_current_markets",
            ["loan_address"],
            unique=False,
            schema="loan",
        )
    if not _index_exists(
        "morpho_blue_current_markets",
        "idx_morpho_blue_current_markets_collateral_address",
    ):
        op.create_index(
            "idx_morpho_blue_current_markets_collateral_address",
            "morpho_blue_current_markets",
            ["collateral_address"],
            unique=False,
            schema="loan",
        )
    if not _index_exists(
        "morpho_blue_current_markets",
        "idx_morpho_blue_current_markets_total_market_size_usd",
    ):
        op.create_index(
            "idx_morpho_blue_current_markets_total_market_size_usd",
            "morpho_blue_current_markets",
            ["total_market_size_usd"],
            unique=False,
            schema="loan",
        )


def downgrade() -> None:
    if _index_exists(
        "morpho_blue_current_markets",
        "idx_morpho_blue_current_markets_total_market_size_usd",
    ):
        op.drop_index(
            "idx_morpho_blue_current_markets_total_market_size_usd",
            table_name="morpho_blue_current_markets",
            schema="loan",
        )
    if _index_exists(
        "morpho_blue_current_markets",
        "idx_morpho_blue_current_markets_collateral_address",
    ):
        op.drop_index(
            "idx_morpho_blue_current_markets_collateral_address",
            table_name="morpho_blue_current_markets",
            schema="loan",
        )
    if _index_exists(
        "morpho_blue_current_markets", "idx_morpho_blue_current_markets_loan_address"
    ):
        op.drop_index(
            "idx_morpho_blue_current_markets_loan_address",
            table_name="morpho_blue_current_markets",
            schema="loan",
        )
    if _index_exists(
        "morpho_blue_current_markets", "idx_morpho_blue_current_markets_market_id"
    ):
        op.drop_index(
            "idx_morpho_blue_current_markets_market_id",
            table_name="morpho_blue_current_markets",
            schema="loan",
        )
    if _table_exists("morpho_blue_current_markets"):
        op.drop_table("morpho_blue_current_markets", schema="loan")
