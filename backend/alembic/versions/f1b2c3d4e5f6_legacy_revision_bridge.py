"""legacy revision bridge

Revision ID: f1b2c3d4e5f6
Revises: a1b2c3d4e5f6
Create Date: 2026-03-15 00:00:00.000000
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "f1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 兼容历史环境：该 revision 仅用于补齐版本链，无 DDL 变更
    pass


def downgrade() -> None:
    pass
