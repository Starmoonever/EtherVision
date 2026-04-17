"""add tron price timestamp cache

Revision ID: 6f7a8b9c0d1e
Revises: 4d5e6f7a8b9c
Create Date: 2026-04-17 17:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6f7a8b9c0d1e"
down_revision: Union[str, Sequence[str], None] = "4d5e6f7a8b9c"
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
    if not _table_exists("tron_price_timestamp"):
        op.create_table(
            "tron_price_timestamp",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("timestamp_bucket", sa.BigInteger(), nullable=False),
            sa.Column("asset_address", sa.Text(), nullable=False),
            sa.Column(
                "asset_symbol",
                sa.Text(),
                nullable=False,
                server_default=sa.text("''"),
            ),
            sa.Column("price_usd", sa.Numeric(precision=30, scale=8), nullable=False),
            sa.Column(
                "source",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'justlend-api'"),
            ),
            sa.Column(
                "fetched_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "timestamp_bucket",
                "asset_address",
                name="uq_tron_price_timestamp_bucket_asset",
            ),
            schema="loan",
        )

    op.execute(
        sa.text(
            "ALTER TABLE loan.tron_price_timestamp "
            "ALTER COLUMN asset_address SET STORAGE PLAIN"
        )
    )

    if not _index_exists("tron_price_timestamp", "idx_tron_price_ts_bucket_addr"):
        op.create_index(
            "idx_tron_price_ts_bucket_addr",
            "tron_price_timestamp",
            ["timestamp_bucket", "asset_address"],
            unique=False,
            schema="loan",
        )


def downgrade() -> None:
    if _index_exists("tron_price_timestamp", "idx_tron_price_ts_bucket_addr"):
        op.drop_index(
            "idx_tron_price_ts_bucket_addr",
            table_name="tron_price_timestamp",
            schema="loan",
        )
    if _table_exists("tron_price_timestamp"):
        op.drop_table("tron_price_timestamp", schema="loan")
