"""add morpho v2 vault current tables

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-04-27 09:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d9e0f1a2b3c4"
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
    # api/morpho/vault/v2/state相关：V2 金库当前快照主表
    if not _table_exists("morpho_vault_v2_current"):
        op.create_table(
            "morpho_vault_v2_current",
            sa.Column("vault_address", postgresql.BYTEA(), nullable=False),
            sa.Column("vault_name", sa.Text(), nullable=True),
            sa.Column("asset_address", postgresql.BYTEA(), nullable=True),
            sa.Column("asset_symbol", sa.Text(), nullable=True),
            sa.Column("asset_decimals", sa.Integer(), nullable=True),
            sa.Column("total_assets_usd", sa.Float(precision=53), nullable=True),
            sa.Column("idle_assets_usd", sa.Float(precision=53), nullable=True),
            sa.Column("liquidity_usd", sa.Float(precision=53), nullable=True),
            sa.Column("apy", sa.Float(precision=53), nullable=True),
            sa.Column("net_apy", sa.Float(precision=53), nullable=True),
            sa.Column(
                "net_apy_excluding_rewards", sa.Float(precision=53), nullable=True
            ),
            sa.Column("avg_net_apy", sa.Float(precision=53), nullable=True),
            sa.Column(
                "avg_net_apy_excluding_rewards", sa.Float(precision=53), nullable=True
            ),
            sa.Column("max_apy", sa.Float(precision=53), nullable=True),
            sa.Column(
                "force_deallocatable_liquidity_usd",
                sa.Float(precision=53),
                nullable=True,
            ),
            sa.Column("performance_fee", sa.Float(precision=53), nullable=True),
            sa.Column("management_fee", sa.Float(precision=53), nullable=True),
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

    # api/morpho/vault/v2/state相关：V2 adapters 当前快照表（最简结构）
    if not _table_exists("morpho_vault_v2_adapters_current"):
        op.create_table(
            "morpho_vault_v2_adapters_current",
            sa.Column("vault_address", postgresql.BYTEA(), nullable=False),
            sa.Column("id", sa.Text(), nullable=False),
            sa.Column("assets", sa.Numeric(precision=78, scale=0), nullable=True),
            sa.Column("assets_usd", sa.Numeric(precision=78, scale=18), nullable=True),
            sa.Column("type", sa.Text(), nullable=False),
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
            sa.PrimaryKeyConstraint("vault_address", "id", "type"),
            schema="loan",
        )

    # 地址字段按仓库标准使用 STORAGE PLAIN
    op.execute(
        sa.text(
            "ALTER TABLE loan.morpho_vault_v2_current "
            "ALTER COLUMN vault_address SET STORAGE PLAIN"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE loan.morpho_vault_v2_current "
            "ALTER COLUMN asset_address SET STORAGE PLAIN"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE loan.morpho_vault_v2_adapters_current "
            "ALTER COLUMN vault_address SET STORAGE PLAIN"
        )
    )

    if not _index_exists("morpho_vault_v2_current", "idx_morpho_v2_current_updated_at"):
        op.create_index(
            "idx_morpho_v2_current_updated_at",
            "morpho_vault_v2_current",
            ["updated_at"],
            unique=False,
            schema="loan",
        )


def downgrade() -> None:
    if _index_exists("morpho_vault_v2_current", "idx_morpho_v2_current_updated_at"):
        op.drop_index(
            "idx_morpho_v2_current_updated_at",
            table_name="morpho_vault_v2_current",
            schema="loan",
        )
    if _table_exists("morpho_vault_v2_adapters_current"):
        op.drop_table("morpho_vault_v2_adapters_current", schema="loan")
    if _table_exists("morpho_vault_v2_current"):
        op.drop_table("morpho_vault_v2_current", schema="loan")
