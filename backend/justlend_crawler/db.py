"""Database helpers for the JustLend scaffold."""

from __future__ import annotations

import logging

import asyncpg
from crawler_shared.config import PostgresConfig
from crawler_shared.postgres import create_pool as create_asyncpg_pool

logger = logging.getLogger(__name__)

_DDL_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext($1));"
_DDL_LOCK_NAME = "loan.justlend_scaffold_ddl"

_DDL_CURRENT_USER_POSITIONS = """
CREATE TABLE IF NOT EXISTS loan.justlend_current_user_positions (
    user_address BYTEA PRIMARY KEY,
    chain TEXT NOT NULL DEFAULT 'tron',
    protocol TEXT NOT NULL DEFAULT 'justlend',
    snapshot_at TIMESTAMPTZ NOT NULL,
    block_timestamp TIMESTAMPTZ NOT NULL,
    block_number BIGINT,
    source_cursor TEXT,
    total_collateral_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    total_debt_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    available_borrow_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    health_factor NUMERIC(40, 18) NOT NULL DEFAULT 0,
    ltv NUMERIC(10, 6) NOT NULL DEFAULT 0,
    liquidation_threshold NUMERIC(10, 6) NOT NULL DEFAULT 0,
    extra_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_DDL_CURRENT_POSITION_ASSETS = """
CREATE TABLE IF NOT EXISTS loan.justlend_current_user_position_assets (
    user_address BYTEA NOT NULL,
    asset_address BYTEA NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    block_timestamp TIMESTAMPTZ NOT NULL,
    side TEXT NOT NULL,
    symbol TEXT,
    decimals INTEGER,
    amount NUMERIC(40, 18) NOT NULL DEFAULT 0,
    price_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    value_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    extra_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_address, asset_address, side),
    CONSTRAINT fk_justlend_current_position_assets_user
        FOREIGN KEY (user_address)
        REFERENCES loan.justlend_current_user_positions (user_address)
        ON DELETE CASCADE
);
"""

_DDL_CURRENT_USER_POSITIONS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_justlend_current_user_positions_snapshot_at
    ON loan.justlend_current_user_positions (snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_justlend_current_user_positions_block_timestamp
    ON loan.justlend_current_user_positions (block_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_justlend_current_user_positions_health_factor
    ON loan.justlend_current_user_positions (health_factor);
"""

_DDL_CURRENT_POSITION_ASSETS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_justlend_current_user_position_assets_user
    ON loan.justlend_current_user_position_assets (user_address);
CREATE INDEX IF NOT EXISTS idx_justlend_current_user_position_assets_asset
    ON loan.justlend_current_user_position_assets (asset_address);
CREATE INDEX IF NOT EXISTS idx_justlend_current_user_position_assets_snapshot_at
    ON loan.justlend_current_user_position_assets (snapshot_at DESC);
"""

_DDL_WATCHER_WATERMARKS = """
CREATE TABLE IF NOT EXISTS loan.justlend_watcher_watermarks (
    watcher_key TEXT PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cursor TEXT NOT NULL DEFAULT ''
);
"""


async def create_pool(pg: PostgresConfig, timeout: float = 10.0) -> asyncpg.Pool:
    return await create_asyncpg_pool(pg, timeout=timeout, min_size=2, max_size=10)


async def ensure_justlend_tables(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            # CREATE TABLE IF NOT EXISTS is still race-prone across processes.
            # Serialize JustLend DDL during startup to avoid pg_type catalog clashes.
            await conn.fetchval(_DDL_LOCK_SQL, _DDL_LOCK_NAME)
            await conn.execute(_DDL_CURRENT_USER_POSITIONS)
            await conn.execute(_DDL_CURRENT_POSITION_ASSETS)
            await conn.execute(_DDL_CURRENT_USER_POSITIONS_INDEXES)
            await conn.execute(_DDL_CURRENT_POSITION_ASSETS_INDEXES)
            await conn.execute(_DDL_WATCHER_WATERMARKS)
    logger.info("JustLend scaffold tables are ready")
