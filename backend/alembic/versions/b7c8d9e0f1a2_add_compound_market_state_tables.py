"""add compound market_state and reserve snapshot tables

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-03-19 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
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
    if not _table_exists("compound_v2_market_snapshots"):
        op.create_table(
            "compound_v2_market_snapshots",
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("market", postgresql.BYTEA(), nullable=False),
            sa.Column(
                "total_supply", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column(
                "total_borrow", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column(
                "utilization", sa.Numeric(precision=20, scale=18), nullable=False
            ),
            sa.Column(
                "borrow_rate", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column(
                "supply_rate", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column("supply_usd", sa.Numeric(precision=30, scale=8), nullable=False),
            sa.Column("borrow_usd", sa.Numeric(precision=30, scale=8), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("timestamp", "market"),
            schema="loan",
        )
    if not _index_exists(
        "compound_v2_market_snapshots", "idx_compound_v2_market_snapshots_ts"
    ):
        op.create_index(
            "idx_compound_v2_market_snapshots_ts",
            "compound_v2_market_snapshots",
            ["timestamp"],
            unique=False,
            schema="loan",
        )
    if not _index_exists(
        "compound_v2_market_snapshots", "idx_compound_v2_market_snapshots_market_ts"
    ):
        op.create_index(
            "idx_compound_v2_market_snapshots_market_ts",
            "compound_v2_market_snapshots",
            ["market", "timestamp"],
            unique=False,
            schema="loan",
        )

    if not _table_exists("compound_v3_market_snapshots"):
        op.create_table(
            "compound_v3_market_snapshots",
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("market", postgresql.BYTEA(), nullable=False),
            sa.Column(
                "total_supply", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column(
                "total_borrow", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column(
                "utilization", sa.Numeric(precision=20, scale=18), nullable=False
            ),
            sa.Column(
                "borrow_rate", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column(
                "supply_rate", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column("supply_usd", sa.Numeric(precision=30, scale=8), nullable=False),
            sa.Column("borrow_usd", sa.Numeric(precision=30, scale=8), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("timestamp", "market"),
            schema="loan",
        )
    if not _index_exists(
        "compound_v3_market_snapshots", "idx_compound_v3_market_snapshots_ts"
    ):
        op.create_index(
            "idx_compound_v3_market_snapshots_ts",
            "compound_v3_market_snapshots",
            ["timestamp"],
            unique=False,
            schema="loan",
        )
    if not _index_exists(
        "compound_v3_market_snapshots", "idx_compound_v3_market_snapshots_market_ts"
    ):
        op.create_index(
            "idx_compound_v3_market_snapshots_market_ts",
            "compound_v3_market_snapshots",
            ["market", "timestamp"],
            unique=False,
            schema="loan",
        )

    if not _table_exists("compound_v2_market_snapshot_reserves"):
        op.create_table(
            "compound_v2_market_snapshot_reserves",
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("market", postgresql.BYTEA(), nullable=False),
            sa.Column("reserve", postgresql.BYTEA(), nullable=False),
            sa.Column("symbol", sa.Text(), nullable=True),
            sa.Column("decimals", sa.Integer(), nullable=True),
            sa.Column(
                "total_supply", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column(
                "total_borrow", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column(
                "utilization", sa.Numeric(precision=20, scale=18), nullable=False
            ),
            sa.Column(
                "borrow_rate", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column(
                "supply_rate", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column("supply_usd", sa.Numeric(precision=30, scale=8), nullable=False),
            sa.Column("borrow_usd", sa.Numeric(precision=30, scale=8), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("timestamp", "market", "reserve"),
            schema="loan",
        )
    if not _index_exists(
        "compound_v2_market_snapshot_reserves",
        "idx_compound_v2_market_snapshot_reserves_market_ts",
    ):
        op.create_index(
            "idx_compound_v2_market_snapshot_reserves_market_ts",
            "compound_v2_market_snapshot_reserves",
            ["market", "timestamp"],
            unique=False,
            schema="loan",
        )
    if not _index_exists(
        "compound_v2_market_snapshot_reserves",
        "idx_compound_v2_market_snapshot_reserves_reserve_ts",
    ):
        op.create_index(
            "idx_compound_v2_market_snapshot_reserves_reserve_ts",
            "compound_v2_market_snapshot_reserves",
            ["reserve", "timestamp"],
            unique=False,
            schema="loan",
        )

    if not _table_exists("compound_v3_market_snapshot_reserves"):
        op.create_table(
            "compound_v3_market_snapshot_reserves",
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("market", postgresql.BYTEA(), nullable=False),
            sa.Column("reserve", postgresql.BYTEA(), nullable=False),
            sa.Column("symbol", sa.Text(), nullable=True),
            sa.Column("decimals", sa.Integer(), nullable=True),
            sa.Column(
                "total_supply", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column(
                "total_borrow", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column(
                "utilization", sa.Numeric(precision=20, scale=18), nullable=False
            ),
            sa.Column(
                "borrow_rate", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column(
                "supply_rate", sa.Numeric(precision=38, scale=18), nullable=False
            ),
            sa.Column("supply_usd", sa.Numeric(precision=30, scale=8), nullable=False),
            sa.Column("borrow_usd", sa.Numeric(precision=30, scale=8), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("timestamp", "market", "reserve"),
            schema="loan",
        )
    if not _index_exists(
        "compound_v3_market_snapshot_reserves",
        "idx_compound_v3_market_snapshot_reserves_market_ts",
    ):
        op.create_index(
            "idx_compound_v3_market_snapshot_reserves_market_ts",
            "compound_v3_market_snapshot_reserves",
            ["market", "timestamp"],
            unique=False,
            schema="loan",
        )
    if not _index_exists(
        "compound_v3_market_snapshot_reserves",
        "idx_compound_v3_market_snapshot_reserves_reserve_ts",
    ):
        op.create_index(
            "idx_compound_v3_market_snapshot_reserves_reserve_ts",
            "compound_v3_market_snapshot_reserves",
            ["reserve", "timestamp"],
            unique=False,
            schema="loan",
        )


def downgrade() -> None:
    op.drop_index(
        "idx_compound_v3_market_snapshot_reserves_reserve_ts",
        table_name="compound_v3_market_snapshot_reserves",
        schema="loan",
    )
    op.drop_index(
        "idx_compound_v3_market_snapshot_reserves_market_ts",
        table_name="compound_v3_market_snapshot_reserves",
        schema="loan",
    )
    op.drop_table("compound_v3_market_snapshot_reserves", schema="loan")

    op.drop_index(
        "idx_compound_v2_market_snapshot_reserves_reserve_ts",
        table_name="compound_v2_market_snapshot_reserves",
        schema="loan",
    )
    op.drop_index(
        "idx_compound_v2_market_snapshot_reserves_market_ts",
        table_name="compound_v2_market_snapshot_reserves",
        schema="loan",
    )
    op.drop_table("compound_v2_market_snapshot_reserves", schema="loan")

    op.drop_index(
        "idx_compound_v3_market_snapshots_market_ts",
        table_name="compound_v3_market_snapshots",
        schema="loan",
    )
    op.drop_index(
        "idx_compound_v3_market_snapshots_ts",
        table_name="compound_v3_market_snapshots",
        schema="loan",
    )
    op.drop_table("compound_v3_market_snapshots", schema="loan")

    op.drop_index(
        "idx_compound_v2_market_snapshots_market_ts",
        table_name="compound_v2_market_snapshots",
        schema="loan",
    )
    op.drop_index(
        "idx_compound_v2_market_snapshots_ts",
        table_name="compound_v2_market_snapshots",
        schema="loan",
    )
    op.drop_table("compound_v2_market_snapshots", schema="loan")
