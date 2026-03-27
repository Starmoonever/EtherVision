"""rename position_snapshot_cache to aave_position_snapshots, add eth_price_timestamp

Revision ID: a1b2c3d4e5f6
Revises: e2a7c14d8f05
Create Date: 2026-03-11 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "e2a7c14d8f05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 重命名快照缓存表（幂等：若新表已存在则跳过）
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'loan' AND table_name = 'position_snapshot_cache'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'loan' AND table_name = 'aave_position_snapshots'
            ) THEN
                ALTER TABLE loan.position_snapshot_cache RENAME TO aave_position_snapshots;
            END IF;
        END $$;
    """)

    # 2. 重命名相关索引（幂等：不存在时跳过）
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'loan' AND indexname = 'idx_psc_user_ts'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'loan' AND indexname = 'idx_aps_user_ts'
            ) THEN
                ALTER INDEX loan.idx_psc_user_ts RENAME TO idx_aps_user_ts;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'loan' AND indexname = 'idx_psc_block'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'loan' AND indexname = 'idx_aps_block'
            ) THEN
                ALTER INDEX loan.idx_psc_block RENAME TO idx_aps_block;
            END IF;
        END $$;
    """)

    # 3. 创建 ETH 历史价格缓存表
    op.execute("""
        CREATE TABLE IF NOT EXISTS loan.eth_price_timestamp (
            id               BIGSERIAL       PRIMARY KEY,
            timestamp_bucket BIGINT          NOT NULL,
            asset_address    TEXT            NOT NULL,
            asset_symbol     TEXT            NOT NULL DEFAULT '',
            price_usd        NUMERIC(30, 8)  NOT NULL,
            source           TEXT            NOT NULL DEFAULT 'defillama',
            fetched_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            UNIQUE (timestamp_bucket, asset_address)
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_eth_price_ts_bucket_addr
            ON loan.eth_price_timestamp (timestamp_bucket, asset_address);
    """)


def downgrade() -> None:
    # 删除 eth_price_timestamp 表
    op.execute("DROP TABLE IF EXISTS loan.eth_price_timestamp;")

    # 还原索引名
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'loan' AND indexname = 'idx_aps_user_ts'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'loan' AND indexname = 'idx_psc_user_ts'
            ) THEN
                ALTER INDEX loan.idx_aps_user_ts RENAME TO idx_psc_user_ts;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'loan' AND indexname = 'idx_aps_block'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'loan' AND indexname = 'idx_psc_block'
            ) THEN
                ALTER INDEX loan.idx_aps_block RENAME TO idx_psc_block;
            END IF;
        END $$;
    """)

    # 还原表名
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'loan' AND table_name = 'aave_position_snapshots'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'loan' AND table_name = 'position_snapshot_cache'
            ) THEN
                ALTER TABLE loan.aave_position_snapshots RENAME TO position_snapshot_cache;
            END IF;
        END $$;
    """)
