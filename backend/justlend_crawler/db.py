"""Database helpers for the JustLend scaffold."""

from __future__ import annotations

import logging

import asyncpg
from crawler_shared.config import PostgresConfig
from crawler_shared.postgres import create_pool as create_asyncpg_pool

logger = logging.getLogger(__name__)

_DDL_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext($1));"
_DDL_LOCK_NAME = "loan.justlend_scaffold_ddl"

_DDL_USER_POSITIONS = """
CREATE TABLE IF NOT EXISTS loan.justlend_trx_user_positions (
    user_address TEXT PRIMARY KEY,
    chain TEXT NOT NULL DEFAULT 'tron',
    protocol TEXT NOT NULL DEFAULT 'justlend',
    block_number BIGINT NOT NULL DEFAULT 0,
    scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    total_collateral_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    total_debt_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    health_factor NUMERIC(40, 18) NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);
"""

_DDL_POSITION_ASSETS = """
CREATE TABLE IF NOT EXISTS loan.justlend_trx_position_assets (
    user_address TEXT NOT NULL,
    asset_address TEXT NOT NULL,
    symbol TEXT NOT NULL DEFAULT '',
    side TEXT NOT NULL,
    amount NUMERIC(40, 18) NOT NULL DEFAULT 0,
    price_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    value_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (user_address, asset_address, side)
);
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
            await conn.execute(_DDL_USER_POSITIONS)
            await conn.execute(_DDL_POSITION_ASSETS)
            await conn.execute(_DDL_WATCHER_WATERMARKS)
    logger.info("JustLend scaffold tables are ready")
