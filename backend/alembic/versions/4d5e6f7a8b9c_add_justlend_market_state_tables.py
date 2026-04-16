"""add justlend market state tables

Revision ID: 4d5e6f7a8b9c
Revises: 3c4d5e6f7a8b
Create Date: 2026-04-16 15:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4d5e6f7a8b9c"
down_revision: Union[str, Sequence[str], None] = "3c4d5e6f7a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names(schema="loan")


def _index_exists(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name, schema="loan")
    )


def _set_storage_plain(table_name: str, *columns: str) -> None:
    for column in columns:
        op.execute(
            sa.text(
                f"ALTER TABLE loan.{table_name} ALTER COLUMN {column} SET STORAGE PLAIN"
            )
        )


def upgrade() -> None:
    if not _table_exists("justlend_markets_current"):
        op.create_table(
            "justlend_markets_current",
            sa.Column("market_address", sa.Text(), nullable=False),
            sa.Column(
                "chain", sa.Text(), nullable=False, server_default=sa.text("'tron'")
            ),
            sa.Column(
                "protocol",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'justlend'"),
            ),
            sa.Column(
                "market_type",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'jtoken'"),
            ),
            sa.Column("underlying_address", sa.Text(), nullable=True),
            sa.Column("comptroller_address", sa.Text(), nullable=True),
            sa.Column("oracle_address", sa.Text(), nullable=True),
            sa.Column("symbol", sa.Text(), nullable=True),
            sa.Column("underlying_symbol", sa.Text(), nullable=True),
            sa.Column("underlying_decimals", sa.Integer(), nullable=True),
            sa.Column("jtoken_decimals", sa.Integer(), nullable=True),
            sa.Column("is_listed", sa.Boolean(), nullable=True),
            sa.Column("is_entered_supported", sa.Boolean(), nullable=True),
            sa.Column("collateral_factor", sa.Numeric(precision=20, scale=18)),
            sa.Column("reserve_factor", sa.Numeric(precision=20, scale=18)),
            sa.Column("borrow_cap", sa.Numeric(precision=40, scale=18)),
            sa.Column("supply_cap", sa.Numeric(precision=40, scale=18)),
            sa.Column("exchange_rate", sa.Numeric(precision=40, scale=18)),
            sa.Column("cash", sa.Numeric(precision=40, scale=18)),
            sa.Column("total_borrows", sa.Numeric(precision=40, scale=18)),
            sa.Column("total_reserves", sa.Numeric(precision=40, scale=18)),
            sa.Column("total_supply", sa.Numeric(precision=40, scale=18)),
            sa.Column("utilization", sa.Numeric(precision=20, scale=18)),
            sa.Column("borrow_rate", sa.Numeric(precision=38, scale=18)),
            sa.Column("supply_rate", sa.Numeric(precision=38, scale=18)),
            sa.Column("underlying_price_in_trx", sa.Numeric(precision=30, scale=12)),
            sa.Column("price_usd", sa.Numeric(precision=30, scale=8)),
            sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("block_number", sa.BigInteger(), nullable=True),
            sa.Column(
                "extra_jsonb",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
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
            sa.PrimaryKeyConstraint("market_address"),
            schema="loan",
        )
    _set_storage_plain(
        "justlend_markets_current",
        "market_address",
        "underlying_address",
        "comptroller_address",
        "oracle_address",
    )
    if not _index_exists(
        "justlend_markets_current", "idx_justlend_markets_current_updated_at"
    ):
        op.create_index(
            "idx_justlend_markets_current_updated_at",
            "justlend_markets_current",
            ["updated_at"],
            unique=False,
            schema="loan",
        )
    if not _index_exists(
        "justlend_markets_current", "idx_justlend_markets_current_underlying"
    ):
        op.create_index(
            "idx_justlend_markets_current_underlying",
            "justlend_markets_current",
            ["underlying_address"],
            unique=False,
            schema="loan",
        )
    if not _index_exists(
        "justlend_markets_current", "idx_justlend_markets_current_symbol"
    ):
        op.create_index(
            "idx_justlend_markets_current_symbol",
            "justlend_markets_current",
            ["symbol"],
            unique=False,
            schema="loan",
        )

    if not _table_exists("justlend_market_snapshots"):
        op.create_table(
            "justlend_market_snapshots",
            sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("market_address", sa.Text(), nullable=False),
            sa.Column(
                "chain", sa.Text(), nullable=False, server_default=sa.text("'tron'")
            ),
            sa.Column(
                "protocol",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'justlend'"),
            ),
            sa.Column(
                "market_type",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'jtoken'"),
            ),
            sa.Column("underlying_address", sa.Text(), nullable=True),
            sa.Column("comptroller_address", sa.Text(), nullable=True),
            sa.Column("oracle_address", sa.Text(), nullable=True),
            sa.Column("symbol", sa.Text(), nullable=True),
            sa.Column("underlying_symbol", sa.Text(), nullable=True),
            sa.Column("underlying_decimals", sa.Integer(), nullable=True),
            sa.Column("jtoken_decimals", sa.Integer(), nullable=True),
            sa.Column("is_listed", sa.Boolean(), nullable=True),
            sa.Column("is_entered_supported", sa.Boolean(), nullable=True),
            sa.Column("collateral_factor", sa.Numeric(precision=20, scale=18)),
            sa.Column("reserve_factor", sa.Numeric(precision=20, scale=18)),
            sa.Column("borrow_cap", sa.Numeric(precision=40, scale=18)),
            sa.Column("supply_cap", sa.Numeric(precision=40, scale=18)),
            sa.Column("exchange_rate", sa.Numeric(precision=40, scale=18)),
            sa.Column("cash", sa.Numeric(precision=40, scale=18)),
            sa.Column("total_borrows", sa.Numeric(precision=40, scale=18)),
            sa.Column("total_reserves", sa.Numeric(precision=40, scale=18)),
            sa.Column("total_supply", sa.Numeric(precision=40, scale=18)),
            sa.Column("utilization", sa.Numeric(precision=20, scale=18)),
            sa.Column("borrow_rate", sa.Numeric(precision=38, scale=18)),
            sa.Column("supply_rate", sa.Numeric(precision=38, scale=18)),
            sa.Column("underlying_price_in_trx", sa.Numeric(precision=30, scale=12)),
            sa.Column("price_usd", sa.Numeric(precision=30, scale=8)),
            sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("block_number", sa.BigInteger(), nullable=True),
            sa.Column(
                "extra_jsonb",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("snapshot_at", "market_address"),
            schema="loan",
        )
    _set_storage_plain(
        "justlend_market_snapshots",
        "market_address",
        "underlying_address",
        "comptroller_address",
        "oracle_address",
    )
    if not _index_exists(
        "justlend_market_snapshots", "idx_justlend_market_snapshots_market_ts"
    ):
        op.create_index(
            "idx_justlend_market_snapshots_market_ts",
            "justlend_market_snapshots",
            ["market_address", "snapshot_at"],
            unique=False,
            schema="loan",
        )
    if not _index_exists(
        "justlend_market_snapshots", "idx_justlend_market_snapshots_ts"
    ):
        op.create_index(
            "idx_justlend_market_snapshots_ts",
            "justlend_market_snapshots",
            ["snapshot_at"],
            unique=False,
            schema="loan",
        )
    if not _index_exists(
        "justlend_market_snapshots", "idx_justlend_market_snapshots_underlying_ts"
    ):
        op.create_index(
            "idx_justlend_market_snapshots_underlying_ts",
            "justlend_market_snapshots",
            ["underlying_address", "snapshot_at"],
            unique=False,
            schema="loan",
        )


def downgrade() -> None:
    if _table_exists("justlend_market_snapshots"):
        for index_name in (
            "idx_justlend_market_snapshots_underlying_ts",
            "idx_justlend_market_snapshots_ts",
            "idx_justlend_market_snapshots_market_ts",
        ):
            if _index_exists("justlend_market_snapshots", index_name):
                op.drop_index(
                    index_name,
                    table_name="justlend_market_snapshots",
                    schema="loan",
                )
        op.drop_table("justlend_market_snapshots", schema="loan")

    if _table_exists("justlend_markets_current"):
        for index_name in (
            "idx_justlend_markets_current_symbol",
            "idx_justlend_markets_current_underlying",
            "idx_justlend_markets_current_updated_at",
        ):
            if _index_exists("justlend_markets_current", index_name):
                op.drop_index(
                    index_name,
                    table_name="justlend_markets_current",
                    schema="loan",
                )
        op.drop_table("justlend_markets_current", schema="loan")
