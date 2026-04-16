"""Database helpers for the Morpho scaffold."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

import asyncpg
from crawler_shared.config import PostgresConfig
from crawler_shared.postgres import create_pool as create_asyncpg_pool

logger = logging.getLogger(__name__)

_DDL_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext($1));"
_DDL_LOCK_NAME = "loan.morpho_scaffold_ddl"

_DDL_MARKETS = """
CREATE TABLE IF NOT EXISTS loan.morpho_blue_markets (
    market_id TEXT PRIMARY KEY,
    chain TEXT NOT NULL DEFAULT 'ethereum',
    protocol TEXT NOT NULL DEFAULT 'morpho',
    market_type TEXT NOT NULL DEFAULT 'blue',
    loan_token_address BYTEA,
    collateral_token_address BYTEA,
    oracle_address BYTEA,
    irm_address BYTEA,
    lltv NUMERIC(20, 18),
    extra_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_DDL_CURRENT_USER_POSITIONS = """
CREATE TABLE IF NOT EXISTS loan.morpho_blue_current_user_positions (
    market_id TEXT NOT NULL,
    user_address BYTEA NOT NULL,
    chain TEXT NOT NULL DEFAULT 'ethereum',
    protocol TEXT NOT NULL DEFAULT 'morpho',
    market_type TEXT NOT NULL DEFAULT 'blue',
    snapshot_at TIMESTAMPTZ NOT NULL,
    block_timestamp TIMESTAMPTZ NOT NULL,
    block_number BIGINT,
    supply_shares NUMERIC(40, 18) NOT NULL DEFAULT 0,
    borrow_shares NUMERIC(40, 18) NOT NULL DEFAULT 0,
    collateral_amount NUMERIC(40, 18) NOT NULL DEFAULT 0,
    collateral_value_in_loan_asset NUMERIC(40, 18) NOT NULL DEFAULT 0,
    borrow_assets NUMERIC(40, 18) NOT NULL DEFAULT 0,
    health_factor NUMERIC(40, 18) NOT NULL DEFAULT 0,
    extra_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market_id, user_address),
    CONSTRAINT fk_morpho_blue_current_user_positions_market
        FOREIGN KEY (market_id)
        REFERENCES loan.morpho_blue_markets (market_id)
        ON DELETE CASCADE
);
"""

_DDL_CURRENT_POSITION_ASSETS = """
CREATE TABLE IF NOT EXISTS loan.morpho_blue_current_position_assets (
    market_id TEXT NOT NULL,
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
    PRIMARY KEY (market_id, user_address, asset_address, side),
    CONSTRAINT fk_morpho_blue_current_position_assets_position
        FOREIGN KEY (market_id, user_address)
        REFERENCES loan.morpho_blue_current_user_positions (market_id, user_address)
        ON DELETE CASCADE
);
"""

_DDL_POSITION_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS loan.morpho_blue_position_snapshots (
    market_id TEXT NOT NULL,
    user_address BYTEA NOT NULL,
    chain TEXT NOT NULL DEFAULT 'ethereum',
    protocol TEXT NOT NULL DEFAULT 'morpho',
    market_type TEXT NOT NULL DEFAULT 'blue',
    tx_hash TEXT NOT NULL,
    block_number BIGINT NOT NULL,
    block_timestamp TIMESTAMPTZ NOT NULL,
    operation_type TEXT,
    has_position BOOLEAN NOT NULL DEFAULT FALSE,
    is_healthy BOOLEAN NOT NULL DEFAULT TRUE,
    collateral_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    debt_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    health_factor NUMERIC(40, 18) NOT NULL DEFAULT 0,
    assets_jsonb JSONB NOT NULL DEFAULT '[]'::jsonb,
    extra_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    brief TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market_id, user_address, tx_hash),
    CONSTRAINT fk_morpho_blue_position_snapshots_market
        FOREIGN KEY (market_id)
        REFERENCES loan.morpho_blue_markets (market_id)
        ON DELETE CASCADE
);
"""

_DDL_MARKETS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_morpho_blue_markets_market_type
    ON loan.morpho_blue_markets (market_type);
CREATE INDEX IF NOT EXISTS idx_morpho_blue_markets_updated_at
    ON loan.morpho_blue_markets (updated_at DESC);
"""

_DDL_CURRENT_USER_POSITIONS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_morpho_blue_current_user_positions_user
    ON loan.morpho_blue_current_user_positions (user_address);
CREATE INDEX IF NOT EXISTS idx_morpho_blue_current_user_positions_snapshot_at
    ON loan.morpho_blue_current_user_positions (snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_morpho_blue_current_user_positions_health_factor
    ON loan.morpho_blue_current_user_positions (health_factor);
"""

_DDL_CURRENT_POSITION_ASSETS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_morpho_blue_current_position_assets_user
    ON loan.morpho_blue_current_position_assets (user_address);
CREATE INDEX IF NOT EXISTS idx_morpho_blue_current_position_assets_asset
    ON loan.morpho_blue_current_position_assets (asset_address);
"""

_DDL_POSITION_SNAPSHOTS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_morpho_blue_position_snapshots_user_market_ts
    ON loan.morpho_blue_position_snapshots (
        user_address,
        market_id,
        block_timestamp DESC
    );
CREATE INDEX IF NOT EXISTS idx_morpho_blue_position_snapshots_tx_hash
    ON loan.morpho_blue_position_snapshots (tx_hash);
CREATE INDEX IF NOT EXISTS idx_morpho_blue_position_snapshots_health_factor
    ON loan.morpho_blue_position_snapshots (health_factor);
"""

_DDL_WATCHER_WATERMARKS = """
CREATE TABLE IF NOT EXISTS loan.morpho_watcher_watermarks (
    watcher_key TEXT PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cursor TEXT NOT NULL DEFAULT ''
);
"""


async def create_pool(pg: PostgresConfig, timeout: float = 10.0) -> asyncpg.Pool:
    return await create_asyncpg_pool(pg, timeout=timeout, min_size=2, max_size=10)


async def ensure_morpho_tables(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.fetchval(_DDL_LOCK_SQL, _DDL_LOCK_NAME)
            await conn.execute(_DDL_MARKETS)
            await conn.execute(_DDL_CURRENT_USER_POSITIONS)
            await conn.execute(_DDL_CURRENT_POSITION_ASSETS)
            await conn.execute(_DDL_POSITION_SNAPSHOTS)
            await conn.execute(_DDL_MARKETS_INDEXES)
            await conn.execute(_DDL_CURRENT_USER_POSITIONS_INDEXES)
            await conn.execute(_DDL_CURRENT_POSITION_ASSETS_INDEXES)
            await conn.execute(_DDL_POSITION_SNAPSHOTS_INDEXES)
            await conn.execute(_DDL_WATCHER_WATERMARKS)
    logger.info("Morpho scaffold tables are ready")


async def fetch_markets(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT
                market_id,
                chain,
                protocol,
                market_type,
                loan_token_address,
                collateral_token_address,
                oracle_address,
                irm_address,
                lltv,
                extra_jsonb,
                created_at,
                updated_at
            FROM loan.morpho_blue_markets
            ORDER BY market_id
            """
        )


async def fetch_current_user_positions(
    pool: asyncpg.Pool,
    *,
    user_address: bytes,
    market_id: str | None = None,
) -> tuple[list[asyncpg.Record], list[asyncpg.Record]]:
    async with pool.acquire() as conn:
        if market_id:
            positions = await conn.fetch(
                """
                SELECT
                    market_id,
                    user_address,
                    chain,
                    protocol,
                    market_type,
                    snapshot_at,
                    block_timestamp,
                    block_number,
                    supply_shares,
                    borrow_shares,
                    collateral_amount,
                    collateral_usd,
                    debt_usd,
                    health_factor,
                    extra_jsonb,
                    created_at,
                    updated_at
                FROM loan.morpho_blue_current_user_positions
                WHERE user_address = $1 AND market_id = $2
                ORDER BY snapshot_at DESC, market_id
                """,
                user_address,
                market_id,
            )
            assets = await conn.fetch(
                """
                SELECT
                    market_id,
                    user_address,
                    asset_address,
                    snapshot_at,
                    block_timestamp,
                    side,
                    symbol,
                    decimals,
                    amount,
                    price_usd,
                    value_usd,
                    extra_jsonb,
                    created_at,
                    updated_at
                FROM loan.morpho_blue_current_position_assets
                WHERE user_address = $1 AND market_id = $2
                ORDER BY market_id, value_usd DESC, asset_address, side
                """,
                user_address,
                market_id,
            )
            return positions, assets

        positions = await conn.fetch(
            """
            SELECT
                market_id,
                user_address,
                chain,
                protocol,
                market_type,
                snapshot_at,
                block_timestamp,
                block_number,
                supply_shares,
                borrow_shares,
                collateral_amount,
                collateral_value_in_loan_asset,
                borrow_assets,
                health_factor,
                extra_jsonb,
                created_at,
                updated_at
            FROM loan.morpho_blue_current_user_positions
            WHERE user_address = $1
            ORDER BY snapshot_at DESC, market_id
            """,
            user_address,
        )
        assets = await conn.fetch(
            """
            SELECT
                market_id,
                user_address,
                asset_address,
                snapshot_at,
                block_timestamp,
                side,
                symbol,
                decimals,
                amount,
                price_usd,
                value_usd,
                extra_jsonb,
                created_at,
                updated_at
            FROM loan.morpho_blue_current_position_assets
            WHERE user_address = $1
            ORDER BY market_id, value_usd DESC, asset_address, side
            """,
            user_address,
        )
    return positions, assets


async def upsert_market(
    pool: asyncpg.Pool,
    *,
    market_id: str,
    chain: str = "ethereum",
    protocol: str = "morpho",
    market_type: str = "blue",
    loan_token_address: bytes | None = None,
    collateral_token_address: bytes | None = None,
    oracle_address: bytes | None = None,
    irm_address: bytes | None = None,
    lltv: Decimal | None = None,
    extra_jsonb: dict[str, Any] | None = None,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO loan.morpho_blue_markets (
                market_id,
                chain,
                protocol,
                market_type,
                loan_token_address,
                collateral_token_address,
                oracle_address,
                irm_address,
                lltv,
                extra_jsonb,
                updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
            ON CONFLICT (market_id) DO UPDATE SET
                chain = EXCLUDED.chain,
                protocol = EXCLUDED.protocol,
                market_type = EXCLUDED.market_type,
                loan_token_address = EXCLUDED.loan_token_address,
                collateral_token_address = EXCLUDED.collateral_token_address,
                oracle_address = EXCLUDED.oracle_address,
                irm_address = EXCLUDED.irm_address,
                lltv = EXCLUDED.lltv,
                extra_jsonb = EXCLUDED.extra_jsonb,
                updated_at = NOW()
            """,
            market_id,
            chain,
            protocol,
            market_type,
            loan_token_address,
            collateral_token_address,
            oracle_address,
            irm_address,
            lltv,
            json.dumps(extra_jsonb or {}, ensure_ascii=False),
        )


async def upsert_current_user_position(
    pool: asyncpg.Pool,
    *,
    market_id: str,
    user_address: bytes,
    chain: str,
    protocol: str,
    market_type: str,
    snapshot_at: datetime,
    block_timestamp: datetime,
    block_number: int | None,
    supply_shares: Decimal,
    borrow_shares: Decimal,
    collateral_amount: Decimal,
    collateral_usd: Decimal,
    debt_usd: Decimal,
    health_factor: Decimal,
    extra_jsonb: dict[str, Any],
    assets: list[dict[str, Any]],
) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO loan.morpho_blue_current_user_positions (
                    market_id,
                    user_address,
                    chain,
                    protocol,
                    market_type,
                    snapshot_at,
                    block_timestamp,
                    block_number,
                    supply_shares,
                    borrow_shares,
                    collateral_amount,
                    collateral_usd,
                    debt_usd,
                    health_factor,
                    extra_jsonb,
                    updated_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8,
                    $9, $10, $11, $12, $13, $14, $15, NOW()
                )
                ON CONFLICT (market_id, user_address) DO UPDATE SET
                    chain = EXCLUDED.chain,
                    protocol = EXCLUDED.protocol,
                    market_type = EXCLUDED.market_type,
                    snapshot_at = EXCLUDED.snapshot_at,
                    block_timestamp = EXCLUDED.block_timestamp,
                    block_number = EXCLUDED.block_number,
                    supply_shares = EXCLUDED.supply_shares,
                    borrow_shares = EXCLUDED.borrow_shares,
                    collateral_amount = EXCLUDED.collateral_amount,
                    collateral_usd = EXCLUDED.collateral_usd,
                    debt_usd = EXCLUDED.debt_usd,
                    health_factor = EXCLUDED.health_factor,
                    extra_jsonb = EXCLUDED.extra_jsonb,
                    updated_at = NOW()
                """,
                market_id,
                user_address,
                chain,
                protocol,
                market_type,
                snapshot_at,
                block_timestamp,
                block_number,
                supply_shares,
                borrow_shares,
                collateral_amount,
                collateral_usd,
                debt_usd,
                health_factor,
                json.dumps(extra_jsonb, ensure_ascii=False),
            )
            await conn.execute(
                """
                DELETE FROM loan.morpho_blue_current_position_assets
                WHERE market_id = $1 AND user_address = $2
                """,
                market_id,
                user_address,
            )
            if assets:
                await conn.executemany(
                    """
                    INSERT INTO loan.morpho_blue_current_position_assets (
                        market_id,
                        user_address,
                        asset_address,
                        snapshot_at,
                        block_timestamp,
                        side,
                        symbol,
                        decimals,
                        amount,
                        price_usd,
                        value_usd,
                        extra_jsonb,
                        updated_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7,
                        $8, $9, $10, $11, $12, NOW()
                    )
                    """,
                    [
                        (
                            market_id,
                            user_address,
                            asset["asset_address"],
                            snapshot_at,
                            block_timestamp,
                            asset["side"],
                            asset.get("symbol"),
                            asset.get("decimals"),
                            asset.get("amount", Decimal("0")),
                            asset.get("price_usd", Decimal("0")),
                            asset.get("value_usd", Decimal("0")),
                            json.dumps(
                                asset.get("extra_jsonb", {}), ensure_ascii=False
                            ),
                        )
                        for asset in assets
                    ],
                )


async def fetch_position_replay_snapshots(
    pool: asyncpg.Pool,
    *,
    user_address: bytes,
    market_id: str,
    from_ts: datetime,
    to_ts: datetime,
) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT
                market_id,
                user_address,
                chain,
                protocol,
                market_type,
                tx_hash,
                block_number,
                block_timestamp,
                operation_type,
                has_position,
                is_healthy,
                collateral_usd,
                debt_usd,
                health_factor,
                assets_jsonb,
                extra_jsonb,
                brief,
                created_at,
                updated_at
            FROM loan.morpho_blue_position_snapshots
            WHERE user_address = $1
              AND market_id = $2
              AND block_timestamp >= $3
              AND block_timestamp <= $4
            ORDER BY block_timestamp ASC, block_number ASC, tx_hash ASC
            """,
            user_address,
            market_id,
            from_ts,
            to_ts,
        )


async def upsert_position_replay_snapshots(
    pool: asyncpg.Pool,
    *,
    rows: list[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    values = [
        (
            row["market_id"],
            row["user_address"],
            row["chain"],
            row["protocol"],
            row["market_type"],
            row["tx_hash"],
            row["block_number"],
            row["block_timestamp"],
            row.get("operation_type"),
            row["has_position"],
            row["is_healthy"],
            row["collateral_value_in_loan_asset"],
            row["borrow_assets"],
            row["health_factor"],
            json.dumps(row.get("assets_jsonb", []), ensure_ascii=False),
            json.dumps(row.get("extra_jsonb", {}), ensure_ascii=False),
            row.get("brief", ""),
        )
        for row in rows
    ]
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO loan.morpho_blue_position_snapshots (
                market_id,
                user_address,
                chain,
                protocol,
                market_type,
                tx_hash,
                block_number,
                block_timestamp,
                operation_type,
                has_position,
                is_healthy,
                collateral_value_in_loan_asset,
                borrow_assets,
                health_factor,
                assets_jsonb,
                extra_jsonb,
                brief,
                updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9,
                $10, $11, $12, $13, $14, $15, $16, $17, NOW()
            )
            ON CONFLICT (market_id, user_address, tx_hash) DO UPDATE SET
                chain = EXCLUDED.chain,
                protocol = EXCLUDED.protocol,
                market_type = EXCLUDED.market_type,
                block_number = EXCLUDED.block_number,
                block_timestamp = EXCLUDED.block_timestamp,
                operation_type = EXCLUDED.operation_type,
                has_position = EXCLUDED.has_position,
                is_healthy = EXCLUDED.is_healthy,
                collateral_value_in_loan_asset = EXCLUDED.collateral_value_in_loan_asset,
                borrow_assets = EXCLUDED.borrow_assets,
                health_factor = EXCLUDED.health_factor,
                assets_jsonb = EXCLUDED.assets_jsonb,
                extra_jsonb = EXCLUDED.extra_jsonb,
                brief = EXCLUDED.brief,
                updated_at = NOW()
            """,
            values,
        )
    return len(rows)
