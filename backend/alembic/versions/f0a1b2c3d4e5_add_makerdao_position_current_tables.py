"""add makerdao position current tables

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-04-25 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e9f0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names(schema="loan")


def _index_exists(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name, schema="loan")
    )


def _create_position_columns(*, include_vault_fields: bool) -> list[sa.Column]:
    columns: list[sa.Column] = []
    if include_vault_fields:
        columns.extend(
            [
                sa.Column("vault_uid", sa.Text(), nullable=False),
                sa.Column("vault_id", sa.BigInteger(), nullable=True),
            ]
        )
    else:
        columns.extend(
            [
                sa.Column("position_uid", sa.Text(), nullable=False),
                sa.Column(
                    "position_type",
                    sa.Text(),
                    nullable=False,
                    server_default=sa.text("'system_urn'"),
                ),
            ]
        )
    columns.extend(
        [
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
                server_default=sa.text("'makerdao'"),
            ),
            sa.Column(
                "vault_type",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'vault'"),
            )
            if include_vault_fields
            else sa.Column("ilk", sa.Text(), nullable=False),
        ]
    )
    if include_vault_fields:
        columns.append(sa.Column("ilk", sa.Text(), nullable=False))
    columns.extend(
        [
            sa.Column("urn_address", sa.Text(), nullable=False),
            sa.Column("owner_address", sa.Text(), nullable=True)
            if include_vault_fields
            else sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        ]
    )
    if include_vault_fields:
        columns.extend(
            [
                sa.Column("proxy_address", sa.Text(), nullable=True),
                sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
            ]
        )
    columns.extend(
        [
            sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("block_number", sa.BigInteger(), nullable=True),
            sa.Column("collateral_symbol", sa.Text(), nullable=True),
            sa.Column("collateral_token_address", sa.Text(), nullable=True),
            sa.Column(
                "collateral_amount",
                sa.Numeric(precision=78, scale=18),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("collateral_value_usd", sa.Numeric(78, 8), nullable=True),
            sa.Column(
                "debt_symbol",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'DAI'"),
            ),
            sa.Column("debt_token_address", sa.Text(), nullable=True),
            sa.Column(
                "debt_amount",
                sa.Numeric(precision=78, scale=18),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("debt_value_usd", sa.Numeric(78, 8), nullable=True),
            sa.Column("liquidation_ratio", sa.Numeric(78, 18), nullable=True),
            sa.Column("liquidation_price_usd", sa.Numeric(78, 8), nullable=True),
            sa.Column("health_factor", sa.Numeric(78, 18), nullable=True),
            sa.Column(
                "is_healthy",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
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
        ]
    )
    return columns


def upgrade() -> None:
    if not _table_exists("makerdao_current_vault_positions"):
        op.create_table(
            "makerdao_current_vault_positions",
            *_create_position_columns(include_vault_fields=True),
            sa.PrimaryKeyConstraint(
                "vault_uid",
                name="makerdao_current_vault_positions_pk",
            ),
            sa.ForeignKeyConstraint(
                ["ilk"],
                ["loan.makerdao_ilks_current.ilk"],
                name="fk_makerdao_current_vault_positions_ilk",
                ondelete="RESTRICT",
            ),
            schema="loan",
        )

    if not _table_exists("makerdao_system_urn_positions_current"):
        op.create_table(
            "makerdao_system_urn_positions_current",
            *_create_position_columns(include_vault_fields=False),
            sa.PrimaryKeyConstraint(
                "position_uid",
                name="makerdao_system_urn_positions_current_pk",
            ),
            sa.ForeignKeyConstraint(
                ["ilk"],
                ["loan.makerdao_ilks_current.ilk"],
                name="fk_makerdao_system_urn_positions_current_ilk",
                ondelete="RESTRICT",
            ),
            schema="loan",
        )

    for table_name, columns in {
        "makerdao_current_vault_positions": (
            "urn_address",
            "owner_address",
            "proxy_address",
            "collateral_token_address",
            "debt_token_address",
        ),
        "makerdao_system_urn_positions_current": (
            "urn_address",
            "collateral_token_address",
            "debt_token_address",
        ),
    }.items():
        if _table_exists(table_name):
            for column in columns:
                op.execute(
                    sa.text(
                        f"ALTER TABLE loan.{table_name} "
                        f"ALTER COLUMN {column} SET STORAGE PLAIN"
                    )
                )

    indexes = (
        (
            "idx_makerdao_current_vault_positions_owner",
            "makerdao_current_vault_positions",
            ["owner_address"],
        ),
        (
            "idx_makerdao_current_vault_positions_urn",
            "makerdao_current_vault_positions",
            ["urn_address"],
        ),
        (
            "idx_makerdao_current_vault_positions_ilk",
            "makerdao_current_vault_positions",
            ["ilk"],
        ),
        (
            "idx_makerdao_current_vault_positions_snapshot_at",
            "makerdao_current_vault_positions",
            ["snapshot_at"],
        ),
        (
            "idx_makerdao_system_urn_positions_current_urn",
            "makerdao_system_urn_positions_current",
            ["urn_address"],
        ),
        (
            "idx_makerdao_system_urn_positions_current_ilk",
            "makerdao_system_urn_positions_current",
            ["ilk"],
        ),
        (
            "idx_makerdao_system_urn_positions_current_snapshot_at",
            "makerdao_system_urn_positions_current",
            ["snapshot_at"],
        ),
    )
    for index_name, table_name, columns in indexes:
        if _table_exists(table_name) and not _index_exists(table_name, index_name):
            op.create_index(index_name, table_name, columns, schema="loan")


def downgrade() -> None:
    for table_name in (
        "makerdao_system_urn_positions_current",
        "makerdao_current_vault_positions",
    ):
        if _table_exists(table_name):
            op.drop_table(table_name, schema="loan")
