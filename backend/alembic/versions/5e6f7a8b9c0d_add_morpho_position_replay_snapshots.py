"""add morpho position replay snapshots

Revision ID: 5e6f7a8b9c0d
Revises: 2b3c4d5e6f7a
Create Date: 2026-04-16 11:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5e6f7a8b9c0d"
down_revision: Union[str, Sequence[str], None] = "2b3c4d5e6f7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "morpho_blue_position_snapshots" not in inspector.get_table_names(schema="loan"):
        op.create_table(
            "morpho_blue_position_snapshots",
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("user_address", postgresql.BYTEA(), nullable=False),
            sa.Column(
                "chain",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'ethereum'"),
            ),
            sa.Column(
                "protocol",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'morpho'"),
            ),
            sa.Column(
                "market_type",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'blue'"),
            ),
            sa.Column("tx_hash", sa.Text(), nullable=False),
            sa.Column("block_number", sa.BigInteger(), nullable=False),
            sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("operation_type", sa.Text(), nullable=True),
            sa.Column(
                "has_position",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "is_healthy",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "collateral_value_in_loan_asset",
                sa.Numeric(precision=40, scale=18),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "borrow_assets",
                sa.Numeric(precision=40, scale=18),
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
            sa.ForeignKeyConstraint(
                ["market_id"],
                ["loan.morpho_blue_markets.market_id"],
                name="fk_morpho_blue_position_snapshots_market",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("market_id", "user_address", "tx_hash"),
            schema="loan",
        )

    existing_indexes = {
        item["name"]
        for item in inspector.get_indexes(
            "morpho_blue_position_snapshots", schema="loan"
        )
    }
    if "idx_morpho_blue_position_snapshots_user_market_ts" not in existing_indexes:
        op.create_index(
            "idx_morpho_blue_position_snapshots_user_market_ts",
            "morpho_blue_position_snapshots",
            ["user_address", "market_id", "block_timestamp"],
            unique=False,
            schema="loan",
        )
    if "idx_morpho_blue_position_snapshots_tx_hash" not in existing_indexes:
        op.create_index(
            "idx_morpho_blue_position_snapshots_tx_hash",
            "morpho_blue_position_snapshots",
            ["tx_hash"],
            unique=False,
            schema="loan",
        )
    if "idx_morpho_blue_position_snapshots_health_factor" not in existing_indexes:
        op.create_index(
            "idx_morpho_blue_position_snapshots_health_factor",
            "morpho_blue_position_snapshots",
            ["health_factor"],
            unique=False,
            schema="loan",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "morpho_blue_position_snapshots" not in inspector.get_table_names(schema="loan"):
        return

    existing_indexes = {
        item["name"]
        for item in inspector.get_indexes(
            "morpho_blue_position_snapshots", schema="loan"
        )
    }
    for index_name in (
        "idx_morpho_blue_position_snapshots_health_factor",
        "idx_morpho_blue_position_snapshots_tx_hash",
        "idx_morpho_blue_position_snapshots_user_market_ts",
    ):
        if index_name in existing_indexes:
            op.drop_index(
                index_name,
                table_name="morpho_blue_position_snapshots",
                schema="loan",
            )

    op.drop_table("morpho_blue_position_snapshots", schema="loan")
