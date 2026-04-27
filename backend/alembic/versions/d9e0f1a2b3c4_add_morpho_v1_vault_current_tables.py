"""add morpho v1 vault current tables

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-04-24 16:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
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
    # api/morpho/vault/v1/state相关：V1 金库当前快照主表（仅保留精简接口字段）
    if not _table_exists("morpho_vault_v1_current"):
        op.create_table(
            "morpho_vault_v1_current",
            sa.Column("vault_address", postgresql.BYTEA(), nullable=False),
            sa.Column("vault_name", sa.Text(), nullable=True),
            sa.Column("asset_address", postgresql.BYTEA(), nullable=True),
            sa.Column("asset_symbol", sa.Text(), nullable=True),
            sa.Column("asset_decimals", sa.Integer(), nullable=True),
            sa.Column("total_assets_usd", sa.Float(precision=53), nullable=True),
            sa.Column("apy", sa.Float(precision=53), nullable=True),
            sa.Column("net_apy", sa.Float(precision=53), nullable=True),
            sa.Column(
                "net_apy_excluding_rewards", sa.Float(precision=53), nullable=True
            ),
            sa.Column("avg_net_apy", sa.Float(precision=53), nullable=True),
            sa.Column(
                "avg_net_apy_excluding_rewards",
                sa.Float(precision=53),
                nullable=True,
            ),
            sa.Column("timelock_seconds", sa.BigInteger(), nullable=True),
            sa.Column("fee_raw", sa.Float(precision=53), nullable=True),
            sa.Column("liquidity_usd", sa.Float(precision=53), nullable=True),
            sa.Column(
                "source_ts",
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
            sa.PrimaryKeyConstraint("vault_address"),
            schema="loan",
        )

    # api/morpho/vault/v1/state相关：V1 allocation 当前快照表（去冗余，不重复存 market 资产信息）
    if not _table_exists("morpho_vault_v1_allocation_current"):
        op.create_table(
            "morpho_vault_v1_allocation_current",
            sa.Column("vault_address", postgresql.BYTEA(), nullable=False),
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("supply_assets_usd", sa.Float(precision=53), nullable=True),
            sa.Column("supply_cap_usd", sa.Float(precision=53), nullable=True),
            sa.Column("liquidity_usd", sa.Float(precision=53), nullable=True),
            sa.Column(
                "source_ts",
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
            sa.PrimaryKeyConstraint("vault_address", "market_id"),
            schema="loan",
        )

    # 地址字段按仓库标准使用 STORAGE PLAIN
    op.execute(
        sa.text(
            "ALTER TABLE loan.morpho_vault_v1_current "
            "ALTER COLUMN vault_address SET STORAGE PLAIN"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE loan.morpho_vault_v1_current "
            "ALTER COLUMN asset_address SET STORAGE PLAIN"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE loan.morpho_vault_v1_allocation_current "
            "ALTER COLUMN vault_address SET STORAGE PLAIN"
        )
    )

    if not _index_exists(
        "morpho_vault_v1_allocation_current", "idx_morpho_v1_alloc_market_id"
    ):
        op.create_index(
            "idx_morpho_v1_alloc_market_id",
            "morpho_vault_v1_allocation_current",
            ["market_id"],
            unique=False,
            schema="loan",
        )
    if not _index_exists("morpho_vault_v1_current", "idx_morpho_v1_current_updated_at"):
        op.create_index(
            "idx_morpho_v1_current_updated_at",
            "morpho_vault_v1_current",
            ["updated_at"],
            unique=False,
            schema="loan",
        )
    if not _index_exists(
        "morpho_vault_v1_allocation_current", "idx_morpho_v1_alloc_updated_at"
    ):
        op.create_index(
            "idx_morpho_v1_alloc_updated_at",
            "morpho_vault_v1_allocation_current",
            ["updated_at"],
            unique=False,
            schema="loan",
        )


def downgrade() -> None:
    if _index_exists(
        "morpho_vault_v1_allocation_current", "idx_morpho_v1_alloc_updated_at"
    ):
        op.drop_index(
            "idx_morpho_v1_alloc_updated_at",
            table_name="morpho_vault_v1_allocation_current",
            schema="loan",
        )
    if _index_exists("morpho_vault_v1_current", "idx_morpho_v1_current_updated_at"):
        op.drop_index(
            "idx_morpho_v1_current_updated_at",
            table_name="morpho_vault_v1_current",
            schema="loan",
        )
    if _index_exists(
        "morpho_vault_v1_allocation_current", "idx_morpho_v1_alloc_market_id"
    ):
        op.drop_index(
            "idx_morpho_v1_alloc_market_id",
            table_name="morpho_vault_v1_allocation_current",
            schema="loan",
        )

    if _table_exists("morpho_vault_v1_allocation_current"):
        op.drop_table("morpho_vault_v1_allocation_current", schema="loan")
    if _table_exists("morpho_vault_v1_current"):
        op.drop_table("morpho_vault_v1_current", schema="loan")
