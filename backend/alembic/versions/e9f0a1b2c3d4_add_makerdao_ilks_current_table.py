"""add makerdao ilks current table

Revision ID: e9f0a1b2c3d4
Revises: 5e6f7a8b9c0d, 8a9b0c1d2e3f, b1c2d3e4f5a6, d9e0f1a2b3c4
Create Date: 2026-04-25 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e9f0a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = (
    "5e6f7a8b9c0d",
    "8a9b0c1d2e3f",
    "b1c2d3e4f5a6",
    "d9e0f1a2b3c4",
)
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
    if not _table_exists("makerdao_ilks_current"):
        op.create_table(
            "makerdao_ilks_current",
            sa.Column("ilk", sa.Text(), nullable=False),
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
            ),
            sa.Column("gem_symbol", sa.Text(), nullable=True),
            sa.Column("gem_address", sa.Text(), nullable=True),
            sa.Column("join_address", sa.Text(), nullable=True),
            sa.Column("clip_address", sa.Text(), nullable=True),
            sa.Column("pip_address", sa.Text(), nullable=True),
            sa.Column(
                "debt_ceiling", sa.Numeric(precision=40, scale=18), nullable=True
            ),
            sa.Column(
                "liquidation_ratio",
                sa.Numeric(precision=20, scale=18),
                nullable=True,
            ),
            sa.Column(
                "liquidation_penalty",
                sa.Numeric(precision=20, scale=18),
                nullable=True,
            ),
            sa.Column(
                "stability_fee", sa.Numeric(precision=20, scale=18), nullable=True
            ),
            sa.Column("dust", sa.Numeric(precision=40, scale=18), nullable=True),
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
            sa.PrimaryKeyConstraint("ilk", name="makerdao_ilks_current_pk"),
            schema="loan",
        )

    op.execute(
        sa.text(
            """
            ALTER TABLE loan.makerdao_ilks_current
                ALTER COLUMN gem_address SET STORAGE PLAIN,
                ALTER COLUMN join_address SET STORAGE PLAIN,
                ALTER COLUMN clip_address SET STORAGE PLAIN,
                ALTER COLUMN pip_address SET STORAGE PLAIN
            """
        )
    )

    if not _index_exists(
        "makerdao_ilks_current",
        "idx_makerdao_ilks_current_updated_at",
    ):
        op.create_index(
            "idx_makerdao_ilks_current_updated_at",
            "makerdao_ilks_current",
            ["updated_at"],
            unique=False,
            schema="loan",
        )

    if not _index_exists(
        "makerdao_ilks_current",
        "idx_makerdao_ilks_current_gem_address",
    ):
        op.create_index(
            "idx_makerdao_ilks_current_gem_address",
            "makerdao_ilks_current",
            ["gem_address"],
            unique=False,
            schema="loan",
        )


def downgrade() -> None:
    if not _table_exists("makerdao_ilks_current"):
        return
    if _index_exists("makerdao_ilks_current", "idx_makerdao_ilks_current_gem_address"):
        op.drop_index(
            "idx_makerdao_ilks_current_gem_address",
            table_name="makerdao_ilks_current",
            schema="loan",
        )
    if _index_exists("makerdao_ilks_current", "idx_makerdao_ilks_current_updated_at"):
        op.drop_index(
            "idx_makerdao_ilks_current_updated_at",
            table_name="makerdao_ilks_current",
            schema="loan",
        )
    op.drop_table("makerdao_ilks_current", schema="loan")
