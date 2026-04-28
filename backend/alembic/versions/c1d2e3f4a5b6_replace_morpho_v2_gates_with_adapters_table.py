"""replace morpho v2 gates table with adapters table

Revision ID: c1d2e3f4a5b6
Revises: 5e6f7a8b9c0d, 8a9b0c1d2e3f, a1b2c3d4e5f6, a2b3c4d5e6f7, b1c2d3e4f5a6
Create Date: 2026-04-28 14:38:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = (
    "5e6f7a8b9c0d",
    "8a9b0c1d2e3f",
    "a1b2c3d4e5f6",
    "a2b3c4d5e6f7",
    "b1c2d3e4f5a6",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names(schema="loan")


def upgrade() -> None:
    # 按需求替换：去掉 gates 表，新增 adapters 表
    if _table_exists("morpho_vault_v2_gates_current"):
        op.drop_table("morpho_vault_v2_gates_current", schema="loan")

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

    op.execute(
        sa.text(
            "ALTER TABLE loan.morpho_vault_v2_adapters_current "
            "ALTER COLUMN vault_address SET STORAGE PLAIN"
        )
    )


def downgrade() -> None:
    if _table_exists("morpho_vault_v2_adapters_current"):
        op.drop_table("morpho_vault_v2_adapters_current", schema="loan")

    if not _table_exists("morpho_vault_v2_gates_current"):
        op.create_table(
            "morpho_vault_v2_gates_current",
            sa.Column("vault_address", postgresql.BYTEA(), nullable=False),
            sa.Column("gate_type", sa.Text(), nullable=False),
            sa.Column("gate_address", postgresql.BYTEA(), nullable=True),
            sa.Column(
                "abdicated",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "pending_abdication_executable_at", sa.BigInteger(), nullable=True
            ),
            sa.Column("pending_address", postgresql.BYTEA(), nullable=True),
            sa.Column("pending_executable_at", sa.BigInteger(), nullable=True),
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
            sa.PrimaryKeyConstraint("vault_address", "gate_type"),
            schema="loan",
        )
        op.execute(
            sa.text(
                "ALTER TABLE loan.morpho_vault_v2_gates_current "
                "ALTER COLUMN vault_address SET STORAGE PLAIN"
            )
        )
        op.execute(
            sa.text(
                "ALTER TABLE loan.morpho_vault_v2_gates_current "
                "ALTER COLUMN gate_address SET STORAGE PLAIN"
            )
        )
        op.execute(
            sa.text(
                "ALTER TABLE loan.morpho_vault_v2_gates_current "
                "ALTER COLUMN pending_address SET STORAGE PLAIN"
            )
        )
