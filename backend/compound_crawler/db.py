"""Database helpers for Compound crawler."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import asyncpg
from crawler_shared.config import PostgresConfig
from crawler_shared.postgres import create_pool as create_asyncpg_pool
from sqlalchemy import inspect

from .orm_models import Base, CompoundV3UserPosition

logger = logging.getLogger(__name__)


_MARKET_TABLES = {
    "v2": "compound_v2_market_snapshots",
    "v3": "compound_v3_market_snapshots",
}

_RESERVE_TABLES = {
    "v2": "compound_v2_market_snapshot_reserves",
    "v3": "compound_v3_market_snapshot_reserves",
}


@dataclass
class MarketSnapshotRow:
    timestamp: datetime
    market: bytes
    symbol: str | None
    total_supply: Decimal
    total_borrow: Decimal
    collateral_usd: Decimal
    utilization: Decimal
    borrow_rate: Decimal
    supply_rate: Decimal
    price_usd: Decimal
    supply_usd: Decimal
    borrow_usd: Decimal


@dataclass
class ReserveSnapshotRow:
    timestamp: datetime
    market: bytes
    reserve: bytes
    symbol: str | None
    decimals: int | None
    total_supply: Decimal
    total_borrow: Decimal
    utilization: Decimal
    borrow_rate: Decimal
    supply_rate: Decimal
    price_in_base: Decimal
    price_usd: Decimal
    supply_usd: Decimal
    borrow_usd: Decimal


_DDL_MARKET = """
CREATE TABLE IF NOT EXISTS loan.{table_name} (
    "timestamp"    TIMESTAMPTZ     NOT NULL,
    market         BYTEA           NOT NULL,
    symbol         TEXT            NULL,
    total_supply   NUMERIC(38, 18) NOT NULL,
    total_borrow   NUMERIC(38, 18) NOT NULL,
    collateral_usd NUMERIC(30, 8)  NOT NULL,
    utilization    NUMERIC(20, 18) NOT NULL,
    borrow_rate    NUMERIC(38, 18) NOT NULL,
    supply_rate    NUMERIC(38, 18) NOT NULL,
    price_usd      NUMERIC(30, 8)  NOT NULL,
    supply_usd     NUMERIC(30, 8)  NOT NULL,
    borrow_usd     NUMERIC(30, 8)  NOT NULL,
    created_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("timestamp", market)
);
"""


_DDL_MARKET_INDEX_TS = """
CREATE INDEX IF NOT EXISTS {index_name}
    ON loan.{table_name} ("timestamp" DESC);
"""


_DDL_MARKET_INDEX_MARKET = """
CREATE INDEX IF NOT EXISTS {index_name}
    ON loan.{table_name} (market, "timestamp" DESC);
"""


_DDL_RESERVE = """
CREATE TABLE IF NOT EXISTS loan.{table_name} (
    "timestamp"    TIMESTAMPTZ     NOT NULL,
    market         BYTEA           NOT NULL,
    reserve        BYTEA           NOT NULL,
    symbol         TEXT            NULL,
    decimals       INTEGER         NULL,
    total_supply   NUMERIC(38, 18) NOT NULL,
    total_borrow   NUMERIC(38, 18) NOT NULL,
    utilization    NUMERIC(20, 18) NOT NULL,
    borrow_rate    NUMERIC(38, 18) NOT NULL,
    supply_rate    NUMERIC(38, 18) NOT NULL,
    price_in_base  NUMERIC(30, 8)  NOT NULL,
    price_usd      NUMERIC(30, 8)  NOT NULL,
    supply_usd     NUMERIC(30, 8)  NOT NULL,
    borrow_usd     NUMERIC(30, 8)  NOT NULL,
    created_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("timestamp", market, reserve)
);
"""


_DDL_RESERVE_INDEX_MARKET_TS = """
CREATE INDEX IF NOT EXISTS {index_name}
    ON loan.{table_name} (market, "timestamp" DESC);
"""


_DDL_RESERVE_INDEX_RESERVE_TS = """
CREATE INDEX IF NOT EXISTS {index_name}
    ON loan.{table_name} (reserve, "timestamp" DESC);
"""


_UPSERT_MARKET = """
INSERT INTO loan.{table_name} (
    "timestamp", market,
    symbol, total_supply, total_borrow, collateral_usd, utilization,
    borrow_rate, supply_rate, price_usd,
    supply_usd, borrow_usd
) VALUES (
    $1, $2,
    $3, $4, $5, $6, $7,
    $8, $9, $10,
    $11, $12
)
ON CONFLICT ("timestamp", market) DO UPDATE SET
    symbol = EXCLUDED.symbol,
    total_supply = EXCLUDED.total_supply,
    total_borrow = EXCLUDED.total_borrow,
    collateral_usd = EXCLUDED.collateral_usd,
    utilization = EXCLUDED.utilization,
    borrow_rate = EXCLUDED.borrow_rate,
    supply_rate = EXCLUDED.supply_rate,
    price_usd = EXCLUDED.price_usd,
    supply_usd = EXCLUDED.supply_usd,
    borrow_usd = EXCLUDED.borrow_usd,
    created_at = NOW();
"""


_UPSERT_RESERVE = """
INSERT INTO loan.{table_name} (
    "timestamp", market, reserve,
    symbol, decimals,
    total_supply, total_borrow, utilization,
    borrow_rate, supply_rate, price_in_base, price_usd,
    supply_usd, borrow_usd
) VALUES (
    $1, $2, $3,
    $4, $5,
    $6, $7, $8,
    $9, $10, $11, $12,
    $13, $14
)
ON CONFLICT ("timestamp", market, reserve) DO UPDATE SET
    symbol = EXCLUDED.symbol,
    decimals = EXCLUDED.decimals,
    total_supply = EXCLUDED.total_supply,
    total_borrow = EXCLUDED.total_borrow,
    utilization = EXCLUDED.utilization,
    borrow_rate = EXCLUDED.borrow_rate,
    supply_rate = EXCLUDED.supply_rate,
    price_in_base = EXCLUDED.price_in_base,
    price_usd = EXCLUDED.price_usd,
    supply_usd = EXCLUDED.supply_usd,
    borrow_usd = EXCLUDED.borrow_usd,
    created_at = NOW();
"""


async def create_pool(pg: PostgresConfig) -> asyncpg.Pool:
    return await create_asyncpg_pool(pg, min_size=1, max_size=10)


async def _try_enable_hypertable(conn: Any, table_name: str) -> None:
    """在 TimescaleDB 可用时将表升级为 hypertable；不可用则静默降级。"""
    await conn.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_extension
                WHERE extname = 'timescaledb'
            ) THEN
                PERFORM create_hypertable(
                    'loan.{table_name}',
                    'timestamp',
                    if_not_exists => TRUE,
                    migrate_data => TRUE
                );
            END IF;
        EXCEPTION
            WHEN undefined_function THEN
                -- timescaledb 未安装或版本函数签名不兼容，保持普通表
                NULL;
        END;
        $$;
        """
    )


async def _ensure_market_columns(conn: Any, table_name: str) -> None:
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ADD COLUMN IF NOT EXISTS symbol TEXT;
        """
    )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ADD COLUMN IF NOT EXISTS collateral_usd NUMERIC(30, 8);
        """
    )
    await conn.execute(
        f"""
        UPDATE loan.{table_name}
        SET collateral_usd = 0
        WHERE collateral_usd IS NULL;
        """
    )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ALTER COLUMN collateral_usd SET NOT NULL;
        """
    )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        DROP COLUMN IF EXISTS price_in_base;
        """
    )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ADD COLUMN IF NOT EXISTS price_usd NUMERIC(30, 8);
        """
    )
    await conn.execute(
        f"""
        UPDATE loan.{table_name}
        SET price_usd = CASE
            WHEN total_supply <> 0 THEN ROUND(supply_usd / total_supply, 8)
            WHEN total_borrow <> 0 THEN ROUND(borrow_usd / total_borrow, 8)
            ELSE 0
        END
        WHERE price_usd IS NULL;
        """
    )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ALTER COLUMN price_usd SET NOT NULL;
        """
    )


async def _ensure_reserve_columns(conn: Any, table_name: str) -> None:
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ADD COLUMN IF NOT EXISTS price_in_base NUMERIC(30, 8);
        """
    )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ADD COLUMN IF NOT EXISTS price_usd NUMERIC(30, 8);
        """
    )
    await conn.execute(
        f"""
        UPDATE loan.{table_name}
        SET price_in_base = price_usd
        WHERE price_in_base IS NULL
          AND price_usd IS NOT NULL;
        """
    )
    await conn.execute(
        f"""
        UPDATE loan.{table_name}
        SET price_usd = CASE
            WHEN total_supply <> 0 THEN ROUND(supply_usd / total_supply, 8)
            WHEN total_borrow <> 0 THEN ROUND(borrow_usd / total_borrow, 8)
            ELSE 0
        END
        WHERE price_usd IS NULL;
        """
    )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ALTER COLUMN price_in_base SET NOT NULL;
        """
    )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ALTER COLUMN price_usd SET NOT NULL;
        """
    )


async def ensure_market_state_tables(
    pool: asyncpg.Pool,
    protocol: str | None = None,
    use_timescaledb: bool = False,
) -> None:
    """创建 Compound market_state 表与 reserve 明细表。"""
    if protocol is None or protocol == "all":
        protocols = ["v2", "v3"]
    else:
        protocol = protocol.lower()
        if protocol not in ("v2", "v3"):
            raise ValueError(f"Unsupported protocol: {protocol}")
        protocols = [protocol]

    async with pool.acquire() as conn:
        for p in protocols:
            market_table = _MARKET_TABLES[p]
            reserve_table = _RESERVE_TABLES[p]

            await conn.execute(_DDL_MARKET.format(table_name=market_table))
            await _ensure_market_columns(conn, market_table)
            await conn.execute(
                _DDL_MARKET_INDEX_TS.format(
                    index_name=f"idx_{market_table}_ts",
                    table_name=market_table,
                )
            )
            await conn.execute(
                _DDL_MARKET_INDEX_MARKET.format(
                    index_name=f"idx_{market_table}_market_ts",
                    table_name=market_table,
                )
            )

            await conn.execute(_DDL_RESERVE.format(table_name=reserve_table))
            await _ensure_reserve_columns(conn, reserve_table)
            await conn.execute(
                _DDL_RESERVE_INDEX_MARKET_TS.format(
                    index_name=f"idx_{reserve_table}_market_ts",
                    table_name=reserve_table,
                )
            )
            await conn.execute(
                _DDL_RESERVE_INDEX_RESERVE_TS.format(
                    index_name=f"idx_{reserve_table}_reserve_ts",
                    table_name=reserve_table,
                )
            )

            if use_timescaledb:
                await _try_enable_hypertable(conn, market_table)
                await _try_enable_hypertable(conn, reserve_table)

            logger.info(
                "Compound market_state tables ready: %s, %s (timescaledb=%s)",
                market_table,
                reserve_table,
                use_timescaledb,
            )


def market_table_name(protocol: str) -> str:
    p = protocol.lower()
    if p not in _MARKET_TABLES:
        raise ValueError(f"Unsupported protocol: {protocol}")
    return _MARKET_TABLES[p]


def reserve_table_name(protocol: str) -> str:
    p = protocol.lower()
    if p not in _RESERVE_TABLES:
        raise ValueError(f"Unsupported protocol: {protocol}")
    return _RESERVE_TABLES[p]


async def upsert_market_snapshots(
    pool: asyncpg.Pool,
    protocol: str,
    rows: list[MarketSnapshotRow],
) -> int:
    if not rows:
        return 0
    table_name = market_table_name(protocol)
    sql = _UPSERT_MARKET.format(table_name=table_name)
    values = [
        (
            r.timestamp,
            r.market,
            r.symbol,
            r.total_supply,
            r.total_borrow,
            r.collateral_usd,
            r.utilization,
            r.borrow_rate,
            r.supply_rate,
            r.price_usd,
            r.supply_usd,
            r.borrow_usd,
        )
        for r in rows
    ]
    async with pool.acquire() as conn:
        await conn.executemany(sql, values)
    return len(rows)


async def upsert_reserve_snapshots(
    pool: asyncpg.Pool,
    protocol: str,
    rows: list[ReserveSnapshotRow],
) -> int:
    if not rows:
        return 0
    table_name = reserve_table_name(protocol)
    sql = _UPSERT_RESERVE.format(table_name=table_name)
    values = [
        (
            r.timestamp,
            r.market,
            r.reserve,
            r.symbol,
            r.decimals,
            r.total_supply,
            r.total_borrow,
            r.utilization,
            r.borrow_rate,
            r.supply_rate,
            r.price_in_base,
            r.price_usd,
            r.supply_usd,
            r.borrow_usd,
        )
        for r in rows
    ]
    async with pool.acquire() as conn:
        await conn.executemany(sql, values)
    return len(rows)


def ensure_compound_v3_user_positions_table(engine):
    inspector = inspect(engine)
    if not inspector.has_table("compound_v3_user_positions", schema="loan"):
        Base.metadata.create_all(engine, tables=[CompoundV3UserPosition.__table__])
