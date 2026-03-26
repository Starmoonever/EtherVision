"""add compound v2 active users table

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-26 15:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "compound_v2_active_users" not in inspector.get_table_names(schema="loan"):
        op.create_table(
            "compound_v2_active_users",
            sa.Column("user_address", postgresql.BYTEA(), nullable=False),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_snapshot_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deactivate_reason", sa.Text(), nullable=True),
            sa.Column(
                "last_total_collateral_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "last_total_debt_usd",
                sa.Numeric(precision=30, scale=8),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "last_health_factor",
                sa.Numeric(precision=40, scale=18),
                nullable=False,
                server_default=sa.text("0"),
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

    existing_indexes = {
        index["name"]
        for index in inspector.get_indexes("compound_v2_active_users", schema="loan")
    }
    if "idx_compound_v2_active_users_active" not in existing_indexes:
        op.create_index(
            "idx_compound_v2_active_users_active",
            "compound_v2_active_users",
            ["is_active", "last_event_at"],
            unique=False,
            schema="loan",
            postgresql_using="btree",
        )


def downgrade() -> None:
    op.drop_index(
        "idx_compound_v2_active_users_active",
        table_name="compound_v2_active_users",
        schema="loan",
    )
    op.drop_table("compound_v2_active_users", schema="loan")
