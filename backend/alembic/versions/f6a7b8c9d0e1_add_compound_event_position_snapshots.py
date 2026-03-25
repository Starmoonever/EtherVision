"""add compound event-driven position snapshot table

Revision ID: f6a7b8c9d0e1
Revises: d4e5f6a7b8c9
Create Date: 2026-03-25 11:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compound_position_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_address", postgresql.BYTEA(), nullable=False),
        sa.Column("protocol", sa.Text(), nullable=False),
        sa.Column("market", postgresql.BYTEA(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("tx_hash", sa.Text(), nullable=False),
        sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("has_open_position", sa.Boolean(), nullable=False),
        sa.Column("is_liquidatable", sa.Boolean(), nullable=False),
        sa.Column("base_token", postgresql.BYTEA(), nullable=True),
        sa.Column("base_symbol", sa.Text(), nullable=True),
        sa.Column("base_price_usd", sa.Numeric(precision=30, scale=8), nullable=True),
        sa.Column("eth_price_usd", sa.Numeric(precision=30, scale=8), nullable=False),
        sa.Column(
            "total_collateral_usd", sa.Numeric(precision=30, scale=8), nullable=False
        ),
        sa.Column("total_debt_usd", sa.Numeric(precision=30, scale=8), nullable=False),
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
        sa.Column("health_factor", sa.Numeric(precision=40, scale=18), nullable=False),
        sa.Column(
            "eth_sensitive_collateral_usd",
            sa.Numeric(precision=30, scale=8),
            nullable=False,
        ),
        sa.Column(
            "eth_sensitive_debt_usd", sa.Numeric(precision=30, scale=8), nullable=False
        ),
        sa.Column(
            "net_eth_exposure_usd", sa.Numeric(precision=30, scale=8), nullable=False
        ),
        sa.Column(
            "non_eth_collateral_usd", sa.Numeric(precision=30, scale=8), nullable=False
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
            "eth_down_liq_price_usd", sa.Numeric(precision=30, scale=8), nullable=True
        ),
        sa.Column(
            "eth_up_liq_price_usd", sa.Numeric(precision=30, scale=8), nullable=True
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
            "brief",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "cached_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_address",
            "protocol",
            "market",
            "tx_hash",
            name="uq_compound_snapshot",
        ),
        schema="loan",
    )
    op.create_index(
        "idx_compound_position_snapshots_user_market_ts",
        "compound_position_snapshots",
        ["user_address", "protocol", "market", "block_timestamp"],
        unique=False,
        schema="loan",
    )
    op.create_index(
        "idx_compound_position_snapshots_block",
        "compound_position_snapshots",
        ["block_number"],
        unique=False,
        schema="loan",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_compound_position_snapshots_block",
        table_name="compound_position_snapshots",
        schema="loan",
    )
    op.drop_index(
        "idx_compound_position_snapshots_user_market_ts",
        table_name="compound_position_snapshots",
        schema="loan",
    )
    op.drop_table("compound_position_snapshots", schema="loan")
