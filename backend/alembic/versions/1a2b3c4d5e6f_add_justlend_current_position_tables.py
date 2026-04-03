"""add justlend current position tables

Revision ID: 1a2b3c4d5e6f
Revises: 0f1e2d3c4b5a
Create Date: 2026-04-03 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = "0f1e2d3c4b5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "justlend_current_user_positions" not in inspector.get_table_names(
        schema="loan"
    ):
        op.create_table(
            "justlend_current_user_positions",
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
                server_default=sa.text("'justlend'"),
            ),
            sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("block_number", sa.BigInteger(), nullable=True),
            sa.Column("source_cursor", sa.Text(), nullable=True),
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
            sa.PrimaryKeyConstraint("user_address"),
            schema="loan",
        )

    if "justlend_current_user_position_assets" not in inspector.get_table_names(
        schema="loan"
    ):
        op.create_table(
            "justlend_current_user_position_assets",
            sa.Column("user_address", postgresql.BYTEA(), nullable=False),
            sa.Column("asset_address", postgresql.BYTEA(), nullable=False),
            sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("side", sa.Text(), nullable=False),
            sa.Column("symbol", sa.Text(), nullable=True),
            sa.Column("decimals", sa.Integer(), nullable=True),
            sa.Column(
                "amount",
                sa.Numeric(precision=40, scale=18),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "price_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "value_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
                server_default=sa.text("0"),
            ),
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
            sa.ForeignKeyConstraint(
                ["user_address"],
                ["loan.justlend_current_user_positions.user_address"],
                ondelete="CASCADE",
                name="fk_justlend_current_position_assets_user",
            ),
            sa.PrimaryKeyConstraint("user_address", "asset_address", "side"),
            schema="loan",
        )

    existing_position_indexes = {
        index["name"]
        for index in inspector.get_indexes(
            "justlend_current_user_positions", schema="loan"
        )
    }
    if (
        "idx_justlend_current_user_positions_snapshot_at"
        not in existing_position_indexes
    ):
        op.create_index(
            "idx_justlend_current_user_positions_snapshot_at",
            "justlend_current_user_positions",
            ["snapshot_at"],
            unique=False,
            schema="loan",
        )
    if (
        "idx_justlend_current_user_positions_block_timestamp"
        not in existing_position_indexes
    ):
        op.create_index(
            "idx_justlend_current_user_positions_block_timestamp",
            "justlend_current_user_positions",
            ["block_timestamp"],
            unique=False,
            schema="loan",
        )
    if (
        "idx_justlend_current_user_positions_health_factor"
        not in existing_position_indexes
    ):
        op.create_index(
            "idx_justlend_current_user_positions_health_factor",
            "justlend_current_user_positions",
            ["health_factor"],
            unique=False,
            schema="loan",
        )

    existing_asset_indexes = {
        index["name"]
        for index in inspector.get_indexes(
            "justlend_current_user_position_assets", schema="loan"
        )
    }
    if "idx_justlend_current_user_position_assets_user" not in existing_asset_indexes:
        op.create_index(
            "idx_justlend_current_user_position_assets_user",
            "justlend_current_user_position_assets",
            ["user_address"],
            unique=False,
            schema="loan",
        )
    if "idx_justlend_current_user_position_assets_asset" not in existing_asset_indexes:
        op.create_index(
            "idx_justlend_current_user_position_assets_asset",
            "justlend_current_user_position_assets",
            ["asset_address"],
            unique=False,
            schema="loan",
        )
    if (
        "idx_justlend_current_user_position_assets_snapshot_at"
        not in existing_asset_indexes
    ):
        op.create_index(
            "idx_justlend_current_user_position_assets_snapshot_at",
            "justlend_current_user_position_assets",
            ["snapshot_at"],
            unique=False,
            schema="loan",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "justlend_current_user_position_assets" in inspector.get_table_names(
        schema="loan"
    ):
        existing_asset_indexes = {
            index["name"]
            for index in inspector.get_indexes(
                "justlend_current_user_position_assets", schema="loan"
            )
        }
        for name in (
            "idx_justlend_current_user_position_assets_snapshot_at",
            "idx_justlend_current_user_position_assets_asset",
            "idx_justlend_current_user_position_assets_user",
        ):
            if name in existing_asset_indexes:
                op.drop_index(
                    name,
                    table_name="justlend_current_user_position_assets",
                    schema="loan",
                )
        op.drop_table("justlend_current_user_position_assets", schema="loan")

    if "justlend_current_user_positions" in inspector.get_table_names(schema="loan"):
        existing_position_indexes = {
            index["name"]
            for index in inspector.get_indexes(
                "justlend_current_user_positions", schema="loan"
            )
        }
        for name in (
            "idx_justlend_current_user_positions_health_factor",
            "idx_justlend_current_user_positions_block_timestamp",
            "idx_justlend_current_user_positions_snapshot_at",
        ):
            if name in existing_position_indexes:
                op.drop_index(
                    name, table_name="justlend_current_user_positions", schema="loan"
                )
        op.drop_table("justlend_current_user_positions", schema="loan")
