"""add compound v2 position and config tables

Revision ID: c3e4f5a6b7c8
Revises: b7c8d9e0f1a2
Create Date: 2026-03-24 16:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c3e4f5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
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
    if not _table_exists("compound_v2_user_position_snapshots"):
        op.create_table(
            "compound_v2_user_position_snapshots",
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("block_number", sa.BigInteger(), nullable=False),
            sa.Column("market", postgresql.BYTEA(), nullable=False),
            sa.Column("symbol", sa.Text(), nullable=True),
            sa.Column("user_address", postgresql.BYTEA(), nullable=False),
            sa.Column("has_open_position", sa.Boolean(), nullable=False),
            sa.Column("is_liquidatable", sa.Boolean(), nullable=False),
            sa.Column("base_token", postgresql.BYTEA(), nullable=True),
            sa.Column("base_symbol", sa.Text(), nullable=True),
            sa.Column(
                "base_price_usd", sa.Numeric(precision=30, scale=8), nullable=True
            ),
            sa.Column(
                "eth_price_usd", sa.Numeric(precision=30, scale=8), nullable=False
            ),
            sa.Column(
                "total_collateral_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
            ),
            sa.Column(
                "total_debt_usd", sa.Numeric(precision=30, scale=8), nullable=False
            ),
            sa.Column(
                "discounted_collateral_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
            ),
            sa.Column(
                "liquidation_buffer_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
            ),
            sa.Column(
                "health_factor", sa.Numeric(precision=40, scale=18), nullable=False
            ),
            sa.Column(
                "eth_sensitive_collateral_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
            ),
            sa.Column(
                "eth_sensitive_debt_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
            ),
            sa.Column(
                "net_eth_exposure_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
            ),
            sa.Column(
                "non_eth_collateral_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
            ),
            sa.Column(
                "non_eth_debt_usd", sa.Numeric(precision=30, scale=8), nullable=False
            ),
            sa.Column(
                "basis_risk_collateral_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
            ),
            sa.Column(
                "eth_down_liq_price_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=True,
            ),
            sa.Column(
                "eth_up_liq_price_usd", sa.Numeric(precision=30, scale=8), nullable=True
            ),
            sa.Column("eth_liq_mode", sa.Text(), nullable=False),
            sa.Column("dominant_risk", sa.Text(), nullable=False),
            sa.Column(
                "assets_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("timestamp", "market", "user_address"),
            schema="loan",
        )
    if not _index_exists(
        "compound_v2_user_position_snapshots",
        "idx_compound_v2_user_position_snapshots_market_ts",
    ):
        op.create_index(
            "idx_compound_v2_user_position_snapshots_market_ts",
            "compound_v2_user_position_snapshots",
            ["market", "timestamp"],
            unique=False,
            schema="loan",
        )
    if not _index_exists(
        "compound_v2_user_position_snapshots",
        "idx_compound_v2_user_position_snapshots_user_ts",
    ):
        op.create_index(
            "idx_compound_v2_user_position_snapshots_user_ts",
            "compound_v2_user_position_snapshots",
            ["user_address", "timestamp"],
            unique=False,
            schema="loan",
        )

    if not _table_exists("compound_v2_user_position_snapshot_assets"):
        op.create_table(
            "compound_v2_user_position_snapshot_assets",
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("block_number", sa.BigInteger(), nullable=False),
            sa.Column("market", postgresql.BYTEA(), nullable=False),
            sa.Column("user_address", postgresql.BYTEA(), nullable=False),
            sa.Column("asset", postgresql.BYTEA(), nullable=False),
            sa.Column("symbol", sa.Text(), nullable=True),
            sa.Column("side", sa.Text(), nullable=False),
            sa.Column("decimals", sa.Integer(), nullable=True),
            sa.Column("amount", sa.Numeric(precision=38, scale=18), nullable=False),
            sa.Column(
                "price_in_base", sa.Numeric(precision=30, scale=8), nullable=True
            ),
            sa.Column("price_usd", sa.Numeric(precision=30, scale=8), nullable=False),
            sa.Column("value_usd", sa.Numeric(precision=30, scale=8), nullable=False),
            sa.Column(
                "discounted_value_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
            ),
            sa.Column(
                "borrow_collateral_factor",
                sa.Numeric(precision=20, scale=18),
                nullable=True,
            ),
            sa.Column(
                "liquidate_collateral_factor",
                sa.Numeric(precision=20, scale=18),
                nullable=True,
            ),
            sa.Column(
                "liquidation_factor", sa.Numeric(precision=20, scale=18), nullable=True
            ),
            sa.Column("beta_to_eth", sa.Numeric(precision=20, scale=8), nullable=False),
            sa.Column("is_eth_correlated", sa.Boolean(), nullable=False),
            sa.Column("is_basis_risk_asset", sa.Boolean(), nullable=False),
            sa.Column("ctoken", postgresql.BYTEA(), nullable=True),
            sa.Column("underlying", postgresql.BYTEA(), nullable=True),
            sa.Column(
                "exchange_rate", sa.Numeric(precision=38, scale=18), nullable=True
            ),
            sa.Column(
                "is_entered_market",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "collateral_factor", sa.Numeric(precision=20, scale=18), nullable=True
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint(
                "timestamp", "market", "user_address", "asset", "side"
            ),
            schema="loan",
        )
    if not _index_exists(
        "compound_v2_user_position_snapshot_assets",
        "idx_compound_v2_user_position_snapshot_assets_market_ts",
    ):
        op.create_index(
            "idx_compound_v2_user_position_snapshot_assets_market_ts",
            "compound_v2_user_position_snapshot_assets",
            ["market", "timestamp"],
            unique=False,
            schema="loan",
        )
    if not _index_exists(
        "compound_v2_user_position_snapshot_assets",
        "idx_compound_v2_user_position_snapshot_assets_user_ts",
    ):
        op.create_index(
            "idx_compound_v2_user_position_snapshot_assets_user_ts",
            "compound_v2_user_position_snapshot_assets",
            ["user_address", "timestamp"],
            unique=False,
            schema="loan",
        )

    if not _table_exists("compound_v2_market_config_versions"):
        op.create_table(
            "compound_v2_market_config_versions",
            sa.Column("market", postgresql.BYTEA(), nullable=False),
            sa.Column("symbol", sa.Text(), nullable=True),
            sa.Column(
                "effective_timestamp", sa.DateTime(timezone=True), nullable=False
            ),
            sa.Column("block_number", sa.BigInteger(), nullable=False),
            sa.Column("config_hash", sa.Text(), nullable=False),
            sa.Column("comptroller", postgresql.BYTEA(), nullable=True),
            sa.Column("interest_rate_model", postgresql.BYTEA(), nullable=True),
            sa.Column("underlying", postgresql.BYTEA(), nullable=True),
            sa.Column("underlying_symbol", sa.Text(), nullable=True),
            sa.Column("ctoken_decimals", sa.Integer(), nullable=True),
            sa.Column("underlying_decimals", sa.Integer(), nullable=True),
            sa.Column(
                "collateral_factor", sa.Numeric(precision=20, scale=18), nullable=True
            ),
            sa.Column(
                "reserve_factor", sa.Numeric(precision=20, scale=18), nullable=True
            ),
            sa.Column(
                "liquidation_threshold",
                sa.Numeric(precision=20, scale=18),
                nullable=True,
            ),
            sa.Column("borrow_cap", sa.Numeric(precision=38, scale=18), nullable=True),
            sa.Column("supply_cap", sa.Numeric(precision=38, scale=18), nullable=True),
            sa.Column(
                "is_listed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "is_comped",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "is_deprecated",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "raw_config_jsonb",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("market", "config_hash"),
            schema="loan",
        )
    if not _index_exists(
        "compound_v2_market_config_versions",
        "idx_compound_v2_market_config_versions_market_effective_ts",
    ):
        op.create_index(
            "idx_compound_v2_market_config_versions_market_effective_ts",
            "compound_v2_market_config_versions",
            ["market", "effective_timestamp"],
            unique=False,
            schema="loan",
        )

    if not _table_exists("compound_v2_protocol_config_versions"):
        op.create_table(
            "compound_v2_protocol_config_versions",
            sa.Column(
                "effective_timestamp", sa.DateTime(timezone=True), nullable=False
            ),
            sa.Column("block_number", sa.BigInteger(), nullable=False),
            sa.Column("config_hash", sa.Text(), nullable=False),
            sa.Column("comptroller", postgresql.BYTEA(), nullable=False),
            sa.Column("price_oracle", postgresql.BYTEA(), nullable=True),
            sa.Column(
                "close_factor", sa.Numeric(precision=20, scale=18), nullable=True
            ),
            sa.Column(
                "liquidation_incentive",
                sa.Numeric(precision=20, scale=18),
                nullable=True,
            ),
            sa.Column("pause_guardian", postgresql.BYTEA(), nullable=True),
            sa.Column(
                "transfer_paused",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "seize_paused",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "mint_paused",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "borrow_paused",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "raw_config_jsonb",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("config_hash"),
            schema="loan",
        )
    if not _index_exists(
        "compound_v2_protocol_config_versions",
        "idx_compound_v2_protocol_config_versions_effective_ts",
    ):
        op.create_index(
            "idx_compound_v2_protocol_config_versions_effective_ts",
            "compound_v2_protocol_config_versions",
            ["effective_timestamp"],
            unique=False,
            schema="loan",
        )

    if not _table_exists("compound_v2_user_memberships"):
        op.create_table(
            "compound_v2_user_memberships",
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("block_number", sa.BigInteger(), nullable=False),
            sa.Column("user_address", postgresql.BYTEA(), nullable=False),
            sa.Column("market", postgresql.BYTEA(), nullable=False),
            sa.Column("symbol", sa.Text(), nullable=True),
            sa.Column("is_entered", sa.Boolean(), nullable=False),
            sa.Column(
                "raw_membership_jsonb",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("timestamp", "user_address", "market"),
            schema="loan",
        )
    if not _index_exists(
        "compound_v2_user_memberships", "idx_compound_v2_user_memberships_market_ts"
    ):
        op.create_index(
            "idx_compound_v2_user_memberships_market_ts",
            "compound_v2_user_memberships",
            ["market", "timestamp"],
            unique=False,
            schema="loan",
        )
    if not _index_exists(
        "compound_v2_user_memberships", "idx_compound_v2_user_memberships_user_ts"
    ):
        op.create_index(
            "idx_compound_v2_user_memberships_user_ts",
            "compound_v2_user_memberships",
            ["user_address", "timestamp"],
            unique=False,
            schema="loan",
        )


def downgrade() -> None:
    op.drop_index(
        "idx_compound_v2_user_memberships_user_ts",
        table_name="compound_v2_user_memberships",
        schema="loan",
    )
    op.drop_index(
        "idx_compound_v2_user_memberships_market_ts",
        table_name="compound_v2_user_memberships",
        schema="loan",
    )
    op.drop_table("compound_v2_user_memberships", schema="loan")

    op.drop_index(
        "idx_compound_v2_protocol_config_versions_effective_ts",
        table_name="compound_v2_protocol_config_versions",
        schema="loan",
    )
    op.drop_table("compound_v2_protocol_config_versions", schema="loan")

    op.drop_index(
        "idx_compound_v2_market_config_versions_market_effective_ts",
        table_name="compound_v2_market_config_versions",
        schema="loan",
    )
    op.drop_table("compound_v2_market_config_versions", schema="loan")

    op.drop_index(
        "idx_compound_v2_user_position_snapshot_assets_user_ts",
        table_name="compound_v2_user_position_snapshot_assets",
        schema="loan",
    )
    op.drop_index(
        "idx_compound_v2_user_position_snapshot_assets_market_ts",
        table_name="compound_v2_user_position_snapshot_assets",
        schema="loan",
    )
    op.drop_table("compound_v2_user_position_snapshot_assets", schema="loan")

    op.drop_index(
        "idx_compound_v2_user_position_snapshots_user_ts",
        table_name="compound_v2_user_position_snapshots",
        schema="loan",
    )
    op.drop_index(
        "idx_compound_v2_user_position_snapshots_market_ts",
        table_name="compound_v2_user_position_snapshots",
        schema="loan",
    )
    op.drop_table("compound_v2_user_position_snapshots", schema="loan")
