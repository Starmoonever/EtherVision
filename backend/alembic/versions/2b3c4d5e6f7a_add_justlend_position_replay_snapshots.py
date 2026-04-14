"""add justlend position replay snapshots

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-04-13 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "2b3c4d5e6f7a"
down_revision: Union[str, Sequence[str], None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "justlend_user_position_snapshots" not in inspector.get_table_names(
        schema="loan"
    ):
        op.create_table(
            "justlend_user_position_snapshots",
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
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_address",
                "snapshot_at",
                name="uq_justlend_user_position_snapshots_user_snapshot",
            ),
            schema="loan",
        )
    snapshot_indexes = {
        item["name"]
        for item in inspector.get_indexes(
            "justlend_user_position_snapshots", schema="loan"
        )
    }
    if "idx_justlend_user_position_snapshots_user_snapshot" not in snapshot_indexes:
        op.create_index(
            "idx_justlend_user_position_snapshots_user_snapshot",
            "justlend_user_position_snapshots",
            ["user_address", "snapshot_at"],
            unique=False,
            schema="loan",
        )
    if "idx_justlend_user_position_snapshots_block_timestamp" not in snapshot_indexes:
        op.create_index(
            "idx_justlend_user_position_snapshots_block_timestamp",
            "justlend_user_position_snapshots",
            ["block_timestamp"],
            unique=False,
            schema="loan",
        )

    if "justlend_user_position_snapshot_assets" not in inspector.get_table_names(
        schema="loan"
    ):
        op.create_table(
            "justlend_user_position_snapshot_assets",
            sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
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
                ["snapshot_id"],
                ["loan.justlend_user_position_snapshots.id"],
                name="fk_justlend_position_snapshot_assets_snapshot",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("snapshot_id", "asset_address", "side"),
            schema="loan",
        )
    asset_indexes = {
        item["name"]
        for item in inspector.get_indexes(
            "justlend_user_position_snapshot_assets", schema="loan"
        )
    }
    if "idx_justlend_position_snapshot_assets_user_snapshot" not in asset_indexes:
        op.create_index(
            "idx_justlend_position_snapshot_assets_user_snapshot",
            "justlend_user_position_snapshot_assets",
            ["user_address", "snapshot_at"],
            unique=False,
            schema="loan",
        )
    if "idx_justlend_position_snapshot_assets_asset" not in asset_indexes:
        op.create_index(
            "idx_justlend_position_snapshot_assets_asset",
            "justlend_user_position_snapshot_assets",
            ["asset_address"],
            unique=False,
            schema="loan",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "justlend_user_position_snapshot_assets" in inspector.get_table_names(
        schema="loan"
    ):
        for index_name in (
            "idx_justlend_position_snapshot_assets_asset",
            "idx_justlend_position_snapshot_assets_user_snapshot",
        ):
            existing = {
                item["name"]
                for item in inspector.get_indexes(
                    "justlend_user_position_snapshot_assets", schema="loan"
                )
            }
            if index_name in existing:
                op.drop_index(
                    index_name,
                    table_name="justlend_user_position_snapshot_assets",
                    schema="loan",
                )
        op.drop_table("justlend_user_position_snapshot_assets", schema="loan")

    if "justlend_user_position_snapshots" in inspector.get_table_names(schema="loan"):
        for index_name in (
            "idx_justlend_user_position_snapshots_block_timestamp",
            "idx_justlend_user_position_snapshots_user_snapshot",
        ):
            existing = {
                item["name"]
                for item in inspector.get_indexes(
                    "justlend_user_position_snapshots", schema="loan"
                )
            }
            if index_name in existing:
                op.drop_index(
                    index_name,
                    table_name="justlend_user_position_snapshots",
                    schema="loan",
                )
        op.drop_table("justlend_user_position_snapshots", schema="loan")
