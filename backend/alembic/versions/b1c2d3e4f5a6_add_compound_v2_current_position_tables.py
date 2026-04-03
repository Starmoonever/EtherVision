"""add compound v2 current position tables

Revision ID: b1c2d3e4f5a6
Revises: 0f1e2d3c4b5a, a7b8c9d0e1f2
Create Date: 2026-04-02 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = ("0f1e2d3c4b5a",)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "compound_v2_current_positions" not in inspector.get_table_names(schema="loan"):
        op.create_table(
            "compound_v2_current_positions",
            sa.Column("market", postgresql.BYTEA(), nullable=False),
            sa.Column("user_address", postgresql.BYTEA(), nullable=False),
            sa.Column("symbol", sa.Text(), nullable=True),
            sa.Column("last_block_number", sa.BigInteger(), nullable=False),
            sa.Column(
                "last_block_timestamp", sa.DateTime(timezone=True), nullable=False
            ),
            sa.Column("last_tx_hash", sa.Text(), nullable=True),
            sa.Column("has_open_position", sa.Boolean(), nullable=False),
            sa.Column("is_liquidatable", sa.Boolean(), nullable=False),
            sa.Column("base_token", postgresql.BYTEA(), nullable=True),
            sa.Column("base_symbol", sa.Text(), nullable=True),
            sa.Column(
                "base_price_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=True,
            ),
            sa.Column(
                "eth_price_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
            ),
            sa.Column(
                "total_collateral_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
            ),
            sa.Column(
                "total_debt_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
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
                "health_factor",
                sa.Numeric(precision=40, scale=18),
                nullable=False,
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
                "non_eth_debt_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
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
                "eth_up_liq_price_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=True,
            ),
            sa.Column("eth_liq_mode", sa.Text(), nullable=False),
            sa.Column("dominant_risk", sa.Text(), nullable=False),
            sa.Column(
                "assets_jsonb",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
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
            sa.PrimaryKeyConstraint("market", "user_address"),
            schema="loan",
        )

    if "compound_v2_current_position_assets" not in inspector.get_table_names(
        schema="loan"
    ):
        op.create_table(
            "compound_v2_current_position_assets",
            sa.Column("market", postgresql.BYTEA(), nullable=False),
            sa.Column("user_address", postgresql.BYTEA(), nullable=False),
            sa.Column("asset", postgresql.BYTEA(), nullable=False),
            sa.Column("side", sa.Text(), nullable=False),
            sa.Column("symbol", sa.Text(), nullable=True),
            sa.Column("decimals", sa.Integer(), nullable=True),
            sa.Column("amount", sa.Numeric(precision=38, scale=18), nullable=False),
            sa.Column(
                "price_in_base",
                sa.Numeric(precision=30, scale=8),
                nullable=True,
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
                "liquidation_factor",
                sa.Numeric(precision=20, scale=18),
                nullable=True,
            ),
            sa.Column("beta_to_eth", sa.Numeric(precision=20, scale=8), nullable=False),
            sa.Column("is_eth_correlated", sa.Boolean(), nullable=False),
            sa.Column("is_basis_risk_asset", sa.Boolean(), nullable=False),
            sa.Column("last_block_number", sa.BigInteger(), nullable=False),
            sa.Column(
                "last_block_timestamp", sa.DateTime(timezone=True), nullable=False
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
            sa.PrimaryKeyConstraint("market", "user_address", "asset", "side"),
            schema="loan",
        )

    existing_position_indexes = {
        index["name"]
        for index in inspector.get_indexes(
            "compound_v2_current_positions", schema="loan"
        )
    }
    if "idx_compound_v2_current_positions_user" not in existing_position_indexes:
        op.create_index(
            "idx_compound_v2_current_positions_user",
            "compound_v2_current_positions",
            ["user_address", "last_block_timestamp"],
            unique=False,
            schema="loan",
        )
    if "idx_compound_v2_current_positions_updated" not in existing_position_indexes:
        op.create_index(
            "idx_compound_v2_current_positions_updated",
            "compound_v2_current_positions",
            ["updated_at"],
            unique=False,
            schema="loan",
        )

    existing_asset_indexes = {
        index["name"]
        for index in inspector.get_indexes(
            "compound_v2_current_position_assets",
            schema="loan",
        )
    }
    if "idx_compound_v2_current_position_assets_user" not in existing_asset_indexes:
        op.create_index(
            "idx_compound_v2_current_position_assets_user",
            "compound_v2_current_position_assets",
            ["user_address", "last_block_timestamp"],
            unique=False,
            schema="loan",
        )
    if "idx_compound_v2_current_position_assets_updated" not in existing_asset_indexes:
        op.create_index(
            "idx_compound_v2_current_position_assets_updated",
            "compound_v2_current_position_assets",
            ["updated_at"],
            unique=False,
            schema="loan",
        )


def downgrade() -> None:
    op.drop_index(
        "idx_compound_v2_current_position_assets_updated",
        table_name="compound_v2_current_position_assets",
        schema="loan",
    )
    op.drop_index(
        "idx_compound_v2_current_position_assets_user",
        table_name="compound_v2_current_position_assets",
        schema="loan",
    )
    op.drop_index(
        "idx_compound_v2_current_positions_updated",
        table_name="compound_v2_current_positions",
        schema="loan",
    )
    op.drop_index(
        "idx_compound_v2_current_positions_user",
        table_name="compound_v2_current_positions",
        schema="loan",
    )
    op.drop_table("compound_v2_current_position_assets", schema="loan")
    op.drop_table("compound_v2_current_positions", schema="loan")
