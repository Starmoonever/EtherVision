"""add justlend position snapshots

Revision ID: 3c4d5e6f7a8b
Revises: 2b3c4d5e6f7a
Create Date: 2026-04-13 16:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3c4d5e6f7a8b"
down_revision: Union[str, Sequence[str], None] = "2b3c4d5e6f7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "justlend_position_snapshots" not in inspector.get_table_names(schema="loan"):
        op.create_table(
            "justlend_position_snapshots",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("user_address", postgresql.BYTEA(), nullable=False),
            sa.Column(
                "chain",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'tron'"),
            ),
            sa.Column(
                "protocol",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'trx'"),
            ),
            sa.Column("tx_hash", sa.Text(), nullable=False),
            sa.Column("block_number", sa.BigInteger(), nullable=False),
            sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("market", postgresql.BYTEA(), nullable=True),
            sa.Column("symbol", sa.Text(), nullable=True),
            sa.Column("method_id", sa.Text(), nullable=True),
            sa.Column("operation_type", sa.Text(), nullable=True),
            sa.Column(
                "has_open_position",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "is_liquidatable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "total_collateral_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "total_debt_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "available_borrow_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "discounted_collateral_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "liquidation_buffer_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "health_factor",
                sa.Numeric(precision=40, scale=18),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "ltv",
                sa.Numeric(precision=10, scale=6),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "liquidation_threshold",
                sa.Numeric(precision=10, scale=6),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "assets_jsonb",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "extra_jsonb",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "brief",
                sa.Text(),
                nullable=False,
                server_default=sa.text("''"),
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
            sa.PrimaryKeyConstraint("id"),
            schema="loan",
        )

    existing_indexes = {
        item["name"]
        for item in inspector.get_indexes("justlend_position_snapshots", schema="loan")
    }
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_justlend_position_snapshots_user_tx_market
        ON loan.justlend_position_snapshots (
            user_address,
            tx_hash,
            COALESCE(encode(market, 'hex'), '')
        )
        """
    )
    if "idx_justlend_position_snapshots_user_ts" not in existing_indexes:
        op.create_index(
            "idx_justlend_position_snapshots_user_ts",
            "justlend_position_snapshots",
            ["user_address", "block_timestamp"],
            unique=False,
            schema="loan",
        )
    if "idx_justlend_position_snapshots_user_protocol_ts" not in existing_indexes:
        op.create_index(
            "idx_justlend_position_snapshots_user_protocol_ts",
            "justlend_position_snapshots",
            ["user_address", "protocol", "block_timestamp"],
            unique=False,
            schema="loan",
        )
    if "idx_justlend_position_snapshots_tx_hash" not in existing_indexes:
        op.create_index(
            "idx_justlend_position_snapshots_tx_hash",
            "justlend_position_snapshots",
            ["tx_hash"],
            unique=False,
            schema="loan",
        )
    if "idx_justlend_position_snapshots_market_ts" not in existing_indexes:
        op.create_index(
            "idx_justlend_position_snapshots_market_ts",
            "justlend_position_snapshots",
            ["market", "block_timestamp"],
            unique=False,
            schema="loan",
        )
    if "idx_justlend_position_snapshots_health_factor" not in existing_indexes:
        op.create_index(
            "idx_justlend_position_snapshots_health_factor",
            "justlend_position_snapshots",
            ["health_factor"],
            unique=False,
            schema="loan",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "justlend_position_snapshots" not in inspector.get_table_names(schema="loan"):
        return

    existing_indexes = {
        item["name"]
        for item in inspector.get_indexes("justlend_position_snapshots", schema="loan")
    }
    for index_name in (
        "idx_justlend_position_snapshots_health_factor",
        "idx_justlend_position_snapshots_market_ts",
        "idx_justlend_position_snapshots_tx_hash",
        "idx_justlend_position_snapshots_user_protocol_ts",
        "idx_justlend_position_snapshots_user_ts",
    ):
        if index_name in existing_indexes:
            op.drop_index(
                index_name,
                table_name="justlend_position_snapshots",
                schema="loan",
            )
    op.execute(
        "DROP INDEX IF EXISTS loan.uq_justlend_position_snapshots_user_tx_market"
    )
    op.drop_table("justlend_position_snapshots", schema="loan")
