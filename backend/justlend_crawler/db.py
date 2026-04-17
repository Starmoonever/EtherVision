"""Database helpers for the JustLend scaffold."""

from __future__ import annotations

import logging
import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from dataclasses import dataclass

import asyncpg
from crawler_shared.config import PostgresConfig
from crawler_shared.postgres import create_pool as create_asyncpg_pool
from .constants import JUSTLEND_REPLAY_METHOD_IDS

logger = logging.getLogger(__name__)
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

_CANDIDATE_HISTORY_TIME_COLUMNS = (
    "block_timestamp",
    "timestamp",
    "block_time",
    "event_time",
    "created_at",
)
_CANDIDATE_HISTORY_BLOCK_COLUMNS = ("block_number", "block_num")
_CANDIDATE_HISTORY_TX_COLUMNS = ("tx_hash", "transaction_hash", "hash")
_CANDIDATE_HISTORY_USER_COLUMNS = (
    "from_address",
    "user_address",
    "owner_address",
    "account",
)
_CANDIDATE_HISTORY_STATUS_COLUMNS = ("tx_status", "status")
_CANDIDATE_HISTORY_CONTRACT_TYPE_COLUMNS = ("contract_type",)

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

_DDL_POSITION_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS loan.justlend_user_position_snapshots (
    id BIGSERIAL PRIMARY KEY,
    user_address BYTEA NOT NULL,
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
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_justlend_user_position_snapshots_user_snapshot
        UNIQUE (user_address, snapshot_at)
);
"""

_DDL_POSITION_SNAPSHOT_ASSETS = """
CREATE TABLE IF NOT EXISTS loan.justlend_user_position_snapshot_assets (
    snapshot_id BIGINT NOT NULL,
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
    PRIMARY KEY (snapshot_id, asset_address, side),
    CONSTRAINT fk_justlend_position_snapshot_assets_snapshot
        FOREIGN KEY (snapshot_id)
        REFERENCES loan.justlend_user_position_snapshots (id)
        ON DELETE CASCADE
);
"""

_DDL_POSITION_SNAPSHOTS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_justlend_user_position_snapshots_user_snapshot
    ON loan.justlend_user_position_snapshots (user_address, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_justlend_user_position_snapshots_block_timestamp
    ON loan.justlend_user_position_snapshots (block_timestamp DESC);
"""

_DDL_POSITION_SNAPSHOT_ASSETS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_justlend_position_snapshot_assets_user_snapshot
    ON loan.justlend_user_position_snapshot_assets (user_address, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_justlend_position_snapshot_assets_asset
    ON loan.justlend_user_position_snapshot_assets (asset_address);
"""

_DDL_EVENT_POSITION_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS loan.justlend_position_snapshots (
    id BIGSERIAL PRIMARY KEY,
    user_address BYTEA NOT NULL,
    chain TEXT NOT NULL DEFAULT 'tron',
    protocol TEXT NOT NULL DEFAULT 'trx',
    tx_hash TEXT NOT NULL,
    block_number BIGINT NOT NULL,
    block_timestamp TIMESTAMPTZ NOT NULL,
    market BYTEA NULL,
    symbol TEXT,
    method_id TEXT,
    operation_type TEXT,
    has_open_position BOOLEAN NOT NULL DEFAULT TRUE,
    is_liquidatable BOOLEAN NOT NULL DEFAULT FALSE,
    total_collateral_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    total_debt_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    available_borrow_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    discounted_collateral_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    liquidation_buffer_usd NUMERIC(30, 8) NOT NULL DEFAULT 0,
    health_factor NUMERIC(40, 18) NOT NULL DEFAULT 0,
    ltv NUMERIC(10, 6) NOT NULL DEFAULT 0,
    liquidation_threshold NUMERIC(10, 6) NOT NULL DEFAULT 0,
    assets_jsonb JSONB NOT NULL DEFAULT '[]'::jsonb,
    extra_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    brief TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_DDL_EVENT_POSITION_SNAPSHOTS_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_justlend_position_snapshots_user_tx_market
    ON loan.justlend_position_snapshots (
        user_address,
        tx_hash,
        COALESCE(encode(market, 'hex'), '')
    );
CREATE INDEX IF NOT EXISTS idx_justlend_position_snapshots_user_ts
    ON loan.justlend_position_snapshots (user_address, block_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_justlend_position_snapshots_user_protocol_ts
    ON loan.justlend_position_snapshots (user_address, protocol, block_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_justlend_position_snapshots_tx_hash
    ON loan.justlend_position_snapshots (tx_hash);
CREATE INDEX IF NOT EXISTS idx_justlend_position_snapshots_market_ts
    ON loan.justlend_position_snapshots (market, block_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_justlend_position_snapshots_health_factor
    ON loan.justlend_position_snapshots (health_factor);
"""

_SQL_UPSERT_EVENT_POSITION_SNAPSHOT = """
INSERT INTO loan.justlend_position_snapshots (
    user_address,
    chain,
    protocol,
    tx_hash,
    block_number,
    block_timestamp,
    market,
    symbol,
    method_id,
    operation_type,
    has_open_position,
    is_liquidatable,
    total_collateral_usd,
    total_debt_usd,
    available_borrow_usd,
    discounted_collateral_usd,
    liquidation_buffer_usd,
    health_factor,
    ltv,
    liquidation_threshold,
    assets_jsonb,
    extra_jsonb,
    brief,
    updated_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
    $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
    $21, $22, $23, NOW()
)
ON CONFLICT (
    user_address,
    tx_hash,
    (COALESCE(encode(market, 'hex'), ''))
) DO UPDATE SET
    chain = EXCLUDED.chain,
    protocol = EXCLUDED.protocol,
    block_number = EXCLUDED.block_number,
    block_timestamp = EXCLUDED.block_timestamp,
    market = EXCLUDED.market,
    symbol = EXCLUDED.symbol,
    method_id = EXCLUDED.method_id,
    operation_type = EXCLUDED.operation_type,
    has_open_position = EXCLUDED.has_open_position,
    is_liquidatable = EXCLUDED.is_liquidatable,
    total_collateral_usd = EXCLUDED.total_collateral_usd,
    total_debt_usd = EXCLUDED.total_debt_usd,
    available_borrow_usd = EXCLUDED.available_borrow_usd,
    discounted_collateral_usd = EXCLUDED.discounted_collateral_usd,
    liquidation_buffer_usd = EXCLUDED.liquidation_buffer_usd,
    health_factor = EXCLUDED.health_factor,
    ltv = EXCLUDED.ltv,
    liquidation_threshold = EXCLUDED.liquidation_threshold,
    assets_jsonb = EXCLUDED.assets_jsonb,
    extra_jsonb = EXCLUDED.extra_jsonb,
    brief = EXCLUDED.brief,
    updated_at = NOW()
"""

_SQL_GET_EVENT_POSITION_SNAPSHOTS = """
SELECT
    id,
    user_address,
    chain,
    protocol,
    tx_hash,
    block_number,
    block_timestamp,
    market,
    symbol,
    method_id,
    operation_type,
    has_open_position,
    is_liquidatable,
    total_collateral_usd,
    total_debt_usd,
    available_borrow_usd,
    discounted_collateral_usd,
    liquidation_buffer_usd,
    health_factor,
    ltv,
    liquidation_threshold,
    assets_jsonb,
    extra_jsonb,
    brief,
    created_at,
    updated_at
FROM loan.justlend_position_snapshots
WHERE user_address = $1
  AND protocol = $2
  AND block_timestamp BETWEEN $3 AND $4
  AND ($5::bytea IS NULL OR market = $5::bytea)
ORDER BY block_timestamp ASC, block_number ASC, tx_hash ASC
"""


@dataclass
class JustLendEventPositionSnapshotRow:
    user_address: bytes
    chain: str
    protocol: str
    tx_hash: str
    block_number: int
    block_timestamp: datetime
    market: bytes | None
    symbol: str | None
    method_id: str | None
    operation_type: str | None
    has_open_position: bool
    is_liquidatable: bool
    total_collateral_usd: Decimal
    total_debt_usd: Decimal
    available_borrow_usd: Decimal
    discounted_collateral_usd: Decimal
    liquidation_buffer_usd: Decimal
    health_factor: Decimal
    ltv: Decimal
    liquidation_threshold: Decimal
    assets_jsonb: list[dict[str, Any]]
    extra_jsonb: dict[str, Any]
    brief: str = ""


_DDL_WATCHER_WATERMARKS = """
CREATE TABLE IF NOT EXISTS loan.justlend_watcher_watermarks (
    watcher_key TEXT PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cursor TEXT NOT NULL DEFAULT ''
);
"""

_DDL_MARKETS_CURRENT = """
CREATE TABLE IF NOT EXISTS loan.justlend_markets_current (
    market_address TEXT PRIMARY KEY,
    chain TEXT NOT NULL DEFAULT 'tron',
    protocol TEXT NOT NULL DEFAULT 'justlend',
    market_type TEXT NOT NULL DEFAULT 'jtoken',
    underlying_address TEXT,
    comptroller_address TEXT,
    oracle_address TEXT,
    symbol TEXT,
    underlying_symbol TEXT,
    underlying_decimals INTEGER,
    jtoken_decimals INTEGER,
    is_listed BOOLEAN,
    is_entered_supported BOOLEAN,
    collateral_factor NUMERIC(20, 18),
    reserve_factor NUMERIC(20, 18),
    borrow_cap NUMERIC(40, 18),
    supply_cap NUMERIC(40, 18),
    exchange_rate NUMERIC(40, 18),
    cash NUMERIC(40, 18),
    total_borrows NUMERIC(40, 18),
    total_reserves NUMERIC(40, 18),
    total_supply NUMERIC(40, 18),
    utilization NUMERIC(20, 18),
    borrow_rate NUMERIC(38, 18),
    supply_rate NUMERIC(38, 18),
    underlying_price_in_trx NUMERIC(30, 12),
    price_usd NUMERIC(30, 8),
    snapshot_at TIMESTAMPTZ NOT NULL,
    block_timestamp TIMESTAMPTZ,
    block_number BIGINT,
    extra_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_DDL_MARKETS_CURRENT_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_justlend_markets_current_updated_at
    ON loan.justlend_markets_current (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_justlend_markets_current_underlying
    ON loan.justlend_markets_current (underlying_address);
CREATE INDEX IF NOT EXISTS idx_justlend_markets_current_symbol
    ON loan.justlend_markets_current (symbol);
"""

_DDL_MARKET_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS loan.justlend_market_snapshots (
    snapshot_at TIMESTAMPTZ NOT NULL,
    market_address TEXT NOT NULL,
    chain TEXT NOT NULL DEFAULT 'tron',
    protocol TEXT NOT NULL DEFAULT 'justlend',
    market_type TEXT NOT NULL DEFAULT 'jtoken',
    underlying_address TEXT,
    comptroller_address TEXT,
    oracle_address TEXT,
    symbol TEXT,
    underlying_symbol TEXT,
    underlying_decimals INTEGER,
    jtoken_decimals INTEGER,
    is_listed BOOLEAN,
    is_entered_supported BOOLEAN,
    collateral_factor NUMERIC(20, 18),
    reserve_factor NUMERIC(20, 18),
    borrow_cap NUMERIC(40, 18),
    supply_cap NUMERIC(40, 18),
    exchange_rate NUMERIC(40, 18),
    cash NUMERIC(40, 18),
    total_borrows NUMERIC(40, 18),
    total_reserves NUMERIC(40, 18),
    total_supply NUMERIC(40, 18),
    utilization NUMERIC(20, 18),
    borrow_rate NUMERIC(38, 18),
    supply_rate NUMERIC(38, 18),
    underlying_price_in_trx NUMERIC(30, 12),
    price_usd NUMERIC(30, 8),
    block_timestamp TIMESTAMPTZ,
    block_number BIGINT,
    extra_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (snapshot_at, market_address)
);
"""

_DDL_MARKET_SNAPSHOTS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_justlend_market_snapshots_market_ts
    ON loan.justlend_market_snapshots (market_address, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_justlend_market_snapshots_ts
    ON loan.justlend_market_snapshots (snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_justlend_market_snapshots_underlying_ts
    ON loan.justlend_market_snapshots (underlying_address, snapshot_at DESC);
"""

_DDL_TRON_PRICE_TIMESTAMP = """
CREATE TABLE IF NOT EXISTS loan.tron_price_timestamp (
    id               BIGSERIAL       PRIMARY KEY,
    timestamp_bucket BIGINT          NOT NULL,
    asset_address    TEXT            NOT NULL,
    asset_symbol     TEXT            NOT NULL DEFAULT '',
    price_usd        NUMERIC(30, 8)  NOT NULL,
    source           TEXT            NOT NULL DEFAULT 'justlend-api',
    fetched_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (timestamp_bucket, asset_address)
);
"""

_DDL_TRON_PRICE_TIMESTAMP_INDEX = """
CREATE INDEX IF NOT EXISTS idx_tron_price_ts_bucket_addr
    ON loan.tron_price_timestamp (timestamp_bucket, asset_address);
"""

_DDL_TRON_PRICE_TIMESTAMP_STORAGE = """
ALTER TABLE loan.tron_price_timestamp
    ALTER COLUMN asset_address SET STORAGE PLAIN;
"""

_SQL_GET_TRON_PRICE_CACHED = """
SELECT price_usd
  FROM loan.tron_price_timestamp
 WHERE timestamp_bucket = $1
   AND asset_address = $2
 LIMIT 1
"""

_SQL_GET_TRON_BUCKET_PRICES_CACHED = """
SELECT timestamp_bucket, price_usd
  FROM loan.tron_price_timestamp
 WHERE asset_address = $1
   AND timestamp_bucket = ANY($2::bigint[])
 ORDER BY timestamp_bucket ASC
"""

_SQL_UPSERT_TRON_PRICE = """
INSERT INTO loan.tron_price_timestamp
    (timestamp_bucket, asset_address, asset_symbol, price_usd, source)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (timestamp_bucket, asset_address) DO UPDATE SET
    price_usd = EXCLUDED.price_usd,
    asset_symbol = EXCLUDED.asset_symbol,
    source = EXCLUDED.source,
    fetched_at = NOW()
"""

_SQL_UPSERT_MARKET_CURRENT = """
INSERT INTO loan.justlend_markets_current (
    market_address,
    chain,
    protocol,
    market_type,
    underlying_address,
    comptroller_address,
    oracle_address,
    symbol,
    underlying_symbol,
    underlying_decimals,
    jtoken_decimals,
    is_listed,
    is_entered_supported,
    collateral_factor,
    reserve_factor,
    borrow_cap,
    supply_cap,
    exchange_rate,
    cash,
    total_borrows,
    total_reserves,
    total_supply,
    utilization,
    borrow_rate,
    supply_rate,
    underlying_price_in_trx,
    price_usd,
    snapshot_at,
    block_timestamp,
    block_number,
    extra_jsonb,
    updated_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
    $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
    $21, $22, $23, $24, $25, $26, $27, $28, $29, $30,
    $31, NOW()
)
ON CONFLICT (market_address) DO UPDATE SET
    chain = EXCLUDED.chain,
    protocol = EXCLUDED.protocol,
    market_type = EXCLUDED.market_type,
    underlying_address = EXCLUDED.underlying_address,
    comptroller_address = EXCLUDED.comptroller_address,
    oracle_address = EXCLUDED.oracle_address,
    symbol = EXCLUDED.symbol,
    underlying_symbol = EXCLUDED.underlying_symbol,
    underlying_decimals = EXCLUDED.underlying_decimals,
    jtoken_decimals = EXCLUDED.jtoken_decimals,
    is_listed = EXCLUDED.is_listed,
    is_entered_supported = EXCLUDED.is_entered_supported,
    collateral_factor = EXCLUDED.collateral_factor,
    reserve_factor = EXCLUDED.reserve_factor,
    borrow_cap = EXCLUDED.borrow_cap,
    supply_cap = EXCLUDED.supply_cap,
    exchange_rate = EXCLUDED.exchange_rate,
    cash = EXCLUDED.cash,
    total_borrows = EXCLUDED.total_borrows,
    total_reserves = EXCLUDED.total_reserves,
    total_supply = EXCLUDED.total_supply,
    utilization = EXCLUDED.utilization,
    borrow_rate = EXCLUDED.borrow_rate,
    supply_rate = EXCLUDED.supply_rate,
    underlying_price_in_trx = EXCLUDED.underlying_price_in_trx,
    price_usd = EXCLUDED.price_usd,
    snapshot_at = EXCLUDED.snapshot_at,
    block_timestamp = EXCLUDED.block_timestamp,
    block_number = EXCLUDED.block_number,
    extra_jsonb = EXCLUDED.extra_jsonb,
    updated_at = NOW()
"""

_SQL_INSERT_MARKET_SNAPSHOT = """
INSERT INTO loan.justlend_market_snapshots (
    snapshot_at,
    market_address,
    chain,
    protocol,
    market_type,
    underlying_address,
    comptroller_address,
    oracle_address,
    symbol,
    underlying_symbol,
    underlying_decimals,
    jtoken_decimals,
    is_listed,
    is_entered_supported,
    collateral_factor,
    reserve_factor,
    borrow_cap,
    supply_cap,
    exchange_rate,
    cash,
    total_borrows,
    total_reserves,
    total_supply,
    utilization,
    borrow_rate,
    supply_rate,
    underlying_price_in_trx,
    price_usd,
    block_timestamp,
    block_number,
    extra_jsonb
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
    $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
    $21, $22, $23, $24, $25, $26, $27, $28, $29, $30,
    $31
)
ON CONFLICT (snapshot_at, market_address) DO UPDATE SET
    chain = EXCLUDED.chain,
    protocol = EXCLUDED.protocol,
    market_type = EXCLUDED.market_type,
    underlying_address = EXCLUDED.underlying_address,
    comptroller_address = EXCLUDED.comptroller_address,
    oracle_address = EXCLUDED.oracle_address,
    symbol = EXCLUDED.symbol,
    underlying_symbol = EXCLUDED.underlying_symbol,
    underlying_decimals = EXCLUDED.underlying_decimals,
    jtoken_decimals = EXCLUDED.jtoken_decimals,
    is_listed = EXCLUDED.is_listed,
    is_entered_supported = EXCLUDED.is_entered_supported,
    collateral_factor = EXCLUDED.collateral_factor,
    reserve_factor = EXCLUDED.reserve_factor,
    borrow_cap = EXCLUDED.borrow_cap,
    supply_cap = EXCLUDED.supply_cap,
    exchange_rate = EXCLUDED.exchange_rate,
    cash = EXCLUDED.cash,
    total_borrows = EXCLUDED.total_borrows,
    total_reserves = EXCLUDED.total_reserves,
    total_supply = EXCLUDED.total_supply,
    utilization = EXCLUDED.utilization,
    borrow_rate = EXCLUDED.borrow_rate,
    supply_rate = EXCLUDED.supply_rate,
    underlying_price_in_trx = EXCLUDED.underlying_price_in_trx,
    price_usd = EXCLUDED.price_usd,
    block_timestamp = EXCLUDED.block_timestamp,
    block_number = EXCLUDED.block_number,
    extra_jsonb = EXCLUDED.extra_jsonb
"""


@dataclass
class JustLendMarketStateRow:
    market_address: str
    chain: str = "tron"
    protocol: str = "justlend"
    market_type: str = "jtoken"
    underlying_address: str | None = None
    comptroller_address: str | None = None
    oracle_address: str | None = None
    symbol: str | None = None
    underlying_symbol: str | None = None
    underlying_decimals: int | None = None
    jtoken_decimals: int | None = None
    is_listed: bool | None = None
    is_entered_supported: bool | None = None
    collateral_factor: Decimal | None = None
    reserve_factor: Decimal | None = None
    borrow_cap: Decimal | None = None
    supply_cap: Decimal | None = None
    exchange_rate: Decimal | None = None
    cash: Decimal | None = None
    total_borrows: Decimal | None = None
    total_reserves: Decimal | None = None
    total_supply: Decimal | None = None
    utilization: Decimal | None = None
    borrow_rate: Decimal | None = None
    supply_rate: Decimal | None = None
    underlying_price_in_trx: Decimal | None = None
    price_usd: Decimal | None = None
    snapshot_at: datetime | None = None
    block_timestamp: datetime | None = None
    block_number: int | None = None
    extra_jsonb: dict[str, Any] | None = None


async def create_pool(pg: PostgresConfig, timeout: float = 10.0) -> asyncpg.Pool:
    return await create_asyncpg_pool(pg, timeout=timeout, min_size=2, max_size=10)


def _first_existing_column(
    available_columns: dict[str, str],
    candidates: tuple[str, ...],
) -> str | None:
    for name in candidates:
        if name in available_columns:
            return name
    return None


def _sql_value_expr_by_type(column_name: str, data_type: str, param_index: int) -> str:
    if data_type == "bytea":
        return f"{column_name} = ${param_index}::bytea"
    return f"lower({column_name}::text) = lower(${param_index}::text)"


def _double_sha256(data: bytes) -> bytes:
    import hashlib

    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def _tron_bytes_to_base58_bytes(address: bytes) -> bytes | None:
    if len(address) != 21 or address[0] != 0x41:
        return None
    raw = address + _double_sha256(address)[:4]
    num = int.from_bytes(raw, "big")
    chars: list[str] = []
    while num > 0:
        num, rem = divmod(num, 58)
        chars.append(_BASE58_ALPHABET[rem])
    encoded = "".join(reversed(chars)) or "1"
    pad = len(raw) - len(raw.lstrip(b"\x00"))
    return (("1" * pad) + encoded).encode("utf-8")


def _build_justlend_user_predicate(
    column_name: str,
    data_type: str,
    *,
    bind_values: list[Any],
    user_address: bytes,
) -> str:
    if data_type != "bytea":
        bind_values.append(user_address.hex())
        return f"lower({column_name}::text) = lower(${len(bind_values)}::text)"

    candidates: list[bytes] = [user_address]
    base58_bytes = _tron_bytes_to_base58_bytes(user_address)
    if base58_bytes is not None and base58_bytes not in candidates:
        candidates.append(base58_bytes)
    bind_values.append(candidates)
    return f"{column_name} = ANY(${len(bind_values)}::bytea[])"


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
            await conn.execute(_DDL_POSITION_SNAPSHOTS)
            await conn.execute(_DDL_POSITION_SNAPSHOT_ASSETS)
            await conn.execute(_DDL_POSITION_SNAPSHOTS_INDEXES)
            await conn.execute(_DDL_POSITION_SNAPSHOT_ASSETS_INDEXES)
            await conn.execute(_DDL_EVENT_POSITION_SNAPSHOTS)
            await conn.execute(_DDL_EVENT_POSITION_SNAPSHOTS_INDEXES)
            await conn.execute(_DDL_WATCHER_WATERMARKS)
            await conn.execute(_DDL_MARKETS_CURRENT)
            await conn.execute(_DDL_MARKETS_CURRENT_INDEXES)
            await conn.execute(_DDL_MARKET_SNAPSHOTS)
            await conn.execute(_DDL_MARKET_SNAPSHOTS_INDEXES)
            await conn.execute(_DDL_TRON_PRICE_TIMESTAMP)
            await conn.execute(_DDL_TRON_PRICE_TIMESTAMP_INDEX)
            await conn.execute(_DDL_TRON_PRICE_TIMESTAMP_STORAGE)
    logger.info("JustLend scaffold tables are ready")


def _tron_price_bucket(unix_ts: int) -> int:
    return (unix_ts // 900) * 900


async def ensure_tron_price_cache_table(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.fetchval(_DDL_LOCK_SQL, f"{_DDL_LOCK_NAME}.tron_price_timestamp")
            await conn.execute(_DDL_TRON_PRICE_TIMESTAMP)
            await conn.execute(_DDL_TRON_PRICE_TIMESTAMP_INDEX)
            await conn.execute(_DDL_TRON_PRICE_TIMESTAMP_STORAGE)


async def get_cached_tron_price_usd(
    pool: asyncpg.Pool,
    unix_ts: int,
    asset_address: str,
) -> Decimal | None:
    row = await pool.fetchrow(
        _SQL_GET_TRON_PRICE_CACHED,
        _tron_price_bucket(unix_ts),
        asset_address,
    )
    if row is None:
        return None
    return Decimal(str(row["price_usd"]))


async def get_cached_tron_bucket_prices_usd(
    pool: asyncpg.Pool,
    *,
    asset_address: str,
    buckets: list[int],
) -> dict[int, Decimal]:
    if not buckets:
        return {}
    rows = await pool.fetch(
        _SQL_GET_TRON_BUCKET_PRICES_CACHED,
        asset_address,
        sorted(set(buckets)),
    )
    return {
        int(row["timestamp_bucket"]): Decimal(str(row["price_usd"])) for row in rows
    }


async def upsert_tron_price_cache(
    pool: asyncpg.Pool,
    unix_ts: int,
    asset_address: str,
    asset_symbol: str,
    price_usd: Decimal,
    source: str = "justlend-api",
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            _SQL_UPSERT_TRON_PRICE,
            _tron_price_bucket(unix_ts),
            asset_address,
            asset_symbol,
            price_usd,
            source,
        )


async def fetch_justlend_user_tx_history(
    pool: asyncpg.Pool,
    *,
    user_address: bytes,
    from_dt: datetime,
    to_dt: datetime,
    only_success: bool = True,
) -> list[Any]:
    async with pool.acquire() as conn:
        col_rows = await conn.fetch(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'justlend'
              AND table_name = 'justlend_history'
            """
        )
        if not col_rows:
            raise RuntimeError("justlend.justlend_history not found")

        column_types = {
            str(row["column_name"]): str(row["data_type"]) for row in col_rows
        }
        time_col = _first_existing_column(column_types, _CANDIDATE_HISTORY_TIME_COLUMNS)
        block_col = _first_existing_column(
            column_types, _CANDIDATE_HISTORY_BLOCK_COLUMNS
        )
        tx_col = _first_existing_column(column_types, _CANDIDATE_HISTORY_TX_COLUMNS)
        user_col = _first_existing_column(column_types, _CANDIDATE_HISTORY_USER_COLUMNS)
        status_col = _first_existing_column(
            column_types, _CANDIDATE_HISTORY_STATUS_COLUMNS
        )
        contract_type_col = _first_existing_column(
            column_types, _CANDIDATE_HISTORY_CONTRACT_TYPE_COLUMNS
        )

        if not time_col or not block_col or not tx_col or not user_col:
            raise RuntimeError(
                "justlend.justlend_history missing required columns "
                f"(time={time_col}, block={block_col}, tx={tx_col}, user={user_col})"
            )

        bind_values: list[Any] = []
        where_clauses: list[str] = []

        if only_success and status_col is not None:
            bind_values.append(1)
            where_clauses.append(f"{status_col} = ${len(bind_values)}")

        bind_values.append(from_dt)
        where_clauses.append(f"{time_col} >= ${len(bind_values)}::timestamptz")
        bind_values.append(to_dt)
        where_clauses.append(f"{time_col} <= ${len(bind_values)}::timestamptz")

        where_clauses.append(
            _build_justlend_user_predicate(
                user_col,
                column_types[user_col],
                bind_values=bind_values,
                user_address=user_address,
            )
        )

        select_method_id = "method_id" if "method_id" in column_types else "NULL"
        select_contract = "contract" if "contract" in column_types else "NULL"
        select_parse_summary = (
            "parse_summary" if "parse_summary" in column_types else "NULL"
        )
        select_parse_input = "parse_input" if "parse_input" in column_types else "NULL"
        select_contract_type = (
            contract_type_col if contract_type_col in column_types else "NULL"
        )
        sql = f"""
            SELECT
                {tx_col} AS tx_hash,
                {block_col} AS block_number,
                {time_col} AS block_timestamp,
                {select_method_id} AS method_id,
                {select_contract} AS contract,
                {select_contract_type} AS contract_type,
                {select_parse_summary} AS parse_summary,
                {select_parse_input} AS parse_input
            FROM justlend.justlend_history
            WHERE {" AND ".join(where_clauses)}
            ORDER BY {time_col} ASC, {block_col} ASC
        """
        return await conn.fetch(sql, *bind_values)


async def fetch_justlend_replay_candidate_addresses(
    pool: asyncpg.Pool,
    *,
    from_dt: datetime,
    to_dt: datetime,
    only_success: bool = True,
    limit: int = 0,
) -> list[bytes]:
    async with pool.acquire() as conn:
        col_rows = await conn.fetch(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'justlend'
              AND table_name = 'justlend_history'
            """
        )
        if not col_rows:
            raise RuntimeError("justlend.justlend_history not found")

        column_types = {
            str(row["column_name"]): str(row["data_type"]) for row in col_rows
        }
        time_col = _first_existing_column(column_types, _CANDIDATE_HISTORY_TIME_COLUMNS)
        user_col = _first_existing_column(column_types, _CANDIDATE_HISTORY_USER_COLUMNS)
        status_col = _first_existing_column(
            column_types, _CANDIDATE_HISTORY_STATUS_COLUMNS
        )
        method_col = "method_id" if "method_id" in column_types else None
        contract_type_col = _first_existing_column(
            column_types, _CANDIDATE_HISTORY_CONTRACT_TYPE_COLUMNS
        )
        if not time_col or not user_col or method_col is None:
            raise RuntimeError(
                "justlend.justlend_history missing required replay columns "
                f"(time={time_col}, user={user_col}, method={method_col})"
            )

        bind_values: list[Any] = []
        where_clauses: list[str] = []

        if only_success and status_col is not None:
            bind_values.append(1)
            where_clauses.append(f"{status_col} = ${len(bind_values)}")

        bind_values.append(from_dt)
        where_clauses.append(f"{time_col} >= ${len(bind_values)}::timestamptz")
        bind_values.append(to_dt)
        where_clauses.append(f"{time_col} <= ${len(bind_values)}::timestamptz")

        bind_values.append(list(JUSTLEND_REPLAY_METHOD_IDS))
        where_clauses.append(f"{method_col} = ANY(${len(bind_values)}::text[])")

        if contract_type_col is not None:
            bind_values.append(31)
            where_clauses.append(f"{contract_type_col} = ${len(bind_values)}")

        sql = f"""
            SELECT {user_col} AS user_address
            FROM justlend.justlend_history
            WHERE {" AND ".join(where_clauses)}
              AND {user_col} IS NOT NULL
            GROUP BY {user_col}
            ORDER BY MIN({time_col}) ASC, {user_col}
        """
        if limit > 0:
            bind_values.append(limit)
            sql += f"\nLIMIT ${len(bind_values)}"
        rows = await conn.fetch(sql, *bind_values)
        return [
            bytes(row["user_address"])
            for row in rows
            if row["user_address"] is not None
        ]


async def fetch_existing_justlend_snapshot_addresses(
    pool: asyncpg.Pool,
    *,
    from_dt: datetime,
    to_dt: datetime,
    protocol: str = "trx",
    limit: int = 0,
) -> list[bytes]:
    bind_values: list[Any] = [protocol, from_dt, to_dt]
    sql = """
        SELECT user_address
        FROM loan.justlend_position_snapshots
        WHERE protocol = $1
          AND block_timestamp >= $2::timestamptz
          AND block_timestamp <= $3::timestamptz
        GROUP BY user_address
        ORDER BY MIN(block_timestamp) ASC, user_address
    """
    if limit > 0:
        bind_values.append(limit)
        sql += f"\nLIMIT ${len(bind_values)}"
    rows = await pool.fetch(sql, *bind_values)
    return [
        bytes(row["user_address"]) for row in rows if row["user_address"] is not None
    ]


async def fetch_justlend_tx_effects(
    pool: asyncpg.Pool,
    *,
    tx_hashes: list[str],
) -> dict[str, dict[str, Any]]:
    if not tx_hashes:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH txs AS (
                SELECT lower(tx_hash) AS tx_hash
                FROM unnest($1::text[]) AS t(tx_hash)
            )
            SELECT * FROM (
                SELECT
                    encode(m.tx_hash, 'hex') AS tx_hash,
                    'deposit'::text AS operation_type,
                    m.market_address,
                    m.underlying_address,
                    COALESCE(m.underlying_amount_decimal, m.input_amount_decimal, 0) AS amount_decimal,
                    NULL::bytea AS payer,
                    NULL::bytea AS borrower,
                    NULL::bytea AS liquidator,
                    NULL::bytea AS collateral_market
                FROM justlend.justlend_mint m
                JOIN txs ON encode(m.tx_hash, 'hex') = txs.tx_hash
                UNION ALL
                SELECT
                    encode(b.tx_hash, 'hex') AS tx_hash,
                    'borrow'::text AS operation_type,
                    b.market_address,
                    b.underlying_address,
                    COALESCE(b.underlying_amount_decimal, b.input_amount_decimal, 0) AS amount_decimal,
                    NULL::bytea AS payer,
                    NULL::bytea AS borrower,
                    NULL::bytea AS liquidator,
                    NULL::bytea AS collateral_market
                FROM justlend.justlend_borrow b
                JOIN txs ON encode(b.tx_hash, 'hex') = txs.tx_hash
                UNION ALL
                SELECT
                    encode(r.tx_hash, 'hex') AS tx_hash,
                    'withdraw'::text AS operation_type,
                    r.market_address,
                    r.underlying_address,
                    COALESCE(r.underlying_amount_decimal, r.input_amount_decimal, 0) AS amount_decimal,
                    NULL::bytea AS payer,
                    NULL::bytea AS borrower,
                    NULL::bytea AS liquidator,
                    NULL::bytea AS collateral_market
                FROM justlend.justlend_redeem r
                JOIN txs ON encode(r.tx_hash, 'hex') = txs.tx_hash
                UNION ALL
                SELECT
                    encode(rp.tx_hash, 'hex') AS tx_hash,
                    'repay'::text AS operation_type,
                    rp.market_address,
                    rp.underlying_address,
                    COALESCE(rp.underlying_amount_decimal, rp.input_amount_decimal, 0) AS amount_decimal,
                    rp.payer,
                    rp.borrower,
                    NULL::bytea AS liquidator,
                    NULL::bytea AS collateral_market
                FROM justlend.justlend_repay rp
                JOIN txs ON encode(rp.tx_hash, 'hex') = txs.tx_hash
                UNION ALL
                SELECT
                    encode(l.tx_hash, 'hex') AS tx_hash,
                    'liquidation'::text AS operation_type,
                    l.market_address,
                    l.underlying_address,
                    COALESCE(l.underlying_amount_decimal, l.input_amount_decimal, 0) AS amount_decimal,
                    NULL::bytea AS payer,
                    l.borrower,
                    l.liquidator,
                    l.collateral_market
                FROM justlend.justlend_liquidate l
                JOIN txs ON encode(l.tx_hash, 'hex') = txs.tx_hash
            ) q
            """,
            tx_hashes,
        )
    effects: dict[str, dict[str, Any]] = {}
    for row in rows:
        effects[str(row["tx_hash"])] = {
            "operation_type": row["operation_type"],
            "market_address": row["market_address"],
            "underlying_address": row["underlying_address"],
            "amount_decimal": Decimal(str(row["amount_decimal"] or "0")),
            "payer": row["payer"],
            "borrower": row["borrower"],
            "liquidator": row["liquidator"],
            "collateral_market": row["collateral_market"],
        }
    return effects


async def fetch_current_user_position(
    pool: asyncpg.Pool, user_address: bytes
) -> tuple[asyncpg.Record | None, list[asyncpg.Record]]:
    async with pool.acquire() as conn:
        position = await conn.fetchrow(
            """
            SELECT
                user_address,
                chain,
                protocol,
                snapshot_at,
                block_timestamp,
                block_number,
                source_cursor,
                total_collateral_usd,
                total_debt_usd,
                available_borrow_usd,
                health_factor,
                ltv,
                liquidation_threshold,
                extra_jsonb,
                created_at,
                updated_at
            FROM loan.justlend_current_user_positions
            WHERE user_address = $1
            """,
            user_address,
        )
        if position is None:
            return None, []
        assets = await conn.fetch(
            """
            SELECT
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
            FROM loan.justlend_current_user_position_assets
            WHERE user_address = $1
            ORDER BY value_usd DESC, asset_address, side
            """,
            user_address,
        )
    return position, assets


async def fetch_current_user_positions_page(
    pool: asyncpg.Pool,
    *,
    page_size: int,
    offset: int,
    sort_by: str,
    order: str,
    user_address: bytes | None = None,
    side: str = "all",
    asset_address: bytes | None = None,
) -> list[asyncpg.Record]:
    sort_expr_map = {
        "health_factor": "p.health_factor",
        "total_supply_usd": "p.total_collateral_usd",
        "total_borrow_usd": "p.total_debt_usd",
        "asset_value_usd": "COALESCE(ma.matched_asset_value_usd, 0)",
    }
    sort_expr = sort_expr_map.get(sort_by, "p.health_factor")
    order_sql = "ASC" if order.lower() == "asc" else "DESC"

    params: list[Any] = []
    where_clauses: list[str] = []
    matched_asset_cte = "matched_asset AS (SELECT NULL::bytea AS user_address, NULL::numeric AS matched_asset_value_usd WHERE FALSE)"
    if sort_by == "asset_value_usd":
        params.extend([asset_address, side])
        matched_asset_cte = f"""
        matched_asset AS (
            SELECT
                user_address,
                SUM(value_usd) AS matched_asset_value_usd
            FROM loan.justlend_current_user_position_assets
            WHERE asset_address = ${len(params) - 1}
              AND side = ${len(params)}
            GROUP BY user_address
        )"""

    if user_address is not None:
        params.append(user_address)
        where_clauses.append(f"p.user_address = ${len(params)}")

    params.extend([page_size, offset])
    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
        WITH
        {matched_asset_cte}
        SELECT
            p.user_address,
            p.chain,
            p.protocol,
            p.snapshot_at,
            p.block_timestamp,
            p.block_number,
            p.source_cursor,
            p.total_collateral_usd,
            p.total_debt_usd,
            p.available_borrow_usd,
            p.health_factor,
            p.ltv,
            p.liquidation_threshold,
            p.extra_jsonb,
            p.created_at,
            p.updated_at,
            COALESCE(ma.matched_asset_value_usd, 0) AS matched_asset_value_usd,
            COUNT(*) OVER() AS total_count
        FROM loan.justlend_current_user_positions p
        LEFT JOIN matched_asset ma
          ON ma.user_address = p.user_address
        {where_sql}
        ORDER BY {sort_expr} {order_sql}, p.user_address ASC
        LIMIT ${len(params) - 1}
        OFFSET ${len(params)}
    """
    async with pool.acquire() as conn:
        return await conn.fetch(*([sql] + params))


async def fetch_current_user_position_assets_by_users(
    pool: asyncpg.Pool,
    *,
    user_addresses: list[bytes],
    side: str = "all",
) -> list[asyncpg.Record]:
    if not user_addresses:
        return []
    params: list[Any] = [user_addresses]
    side_sql = ""
    if side != "all":
        params.append(side)
        side_sql = f"AND side = ${len(params)}"
    sql = f"""
        SELECT
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
        FROM loan.justlend_current_user_position_assets
        WHERE user_address = ANY($1::bytea[])
          {side_sql}
        ORDER BY user_address, value_usd DESC, asset_address, side
    """
    async with pool.acquire() as conn:
        return await conn.fetch(*([sql] + params))


async def upsert_current_user_position(
    pool: asyncpg.Pool,
    *,
    user_address: bytes,
    chain: str,
    protocol: str,
    snapshot_at: datetime,
    block_timestamp: datetime,
    block_number: int | None,
    source_cursor: str | None,
    total_collateral_usd: Decimal,
    total_debt_usd: Decimal,
    available_borrow_usd: Decimal,
    health_factor: Decimal,
    ltv: Decimal,
    liquidation_threshold: Decimal,
    extra_jsonb: dict[str, Any],
    assets: list[dict[str, Any]],
) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO loan.justlend_current_user_positions (
                    user_address,
                    chain,
                    protocol,
                    snapshot_at,
                    block_timestamp,
                    block_number,
                    source_cursor,
                    total_collateral_usd,
                    total_debt_usd,
                    available_borrow_usd,
                    health_factor,
                    ltv,
                    liquidation_threshold,
                    extra_jsonb,
                    updated_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7,
                    $8, $9, $10, $11, $12, $13, $14, NOW()
                )
                ON CONFLICT (user_address) DO UPDATE SET
                    chain = EXCLUDED.chain,
                    protocol = EXCLUDED.protocol,
                    snapshot_at = EXCLUDED.snapshot_at,
                    block_timestamp = EXCLUDED.block_timestamp,
                    block_number = EXCLUDED.block_number,
                    source_cursor = EXCLUDED.source_cursor,
                    total_collateral_usd = EXCLUDED.total_collateral_usd,
                    total_debt_usd = EXCLUDED.total_debt_usd,
                    available_borrow_usd = EXCLUDED.available_borrow_usd,
                    health_factor = EXCLUDED.health_factor,
                    ltv = EXCLUDED.ltv,
                    liquidation_threshold = EXCLUDED.liquidation_threshold,
                    extra_jsonb = EXCLUDED.extra_jsonb,
                    updated_at = NOW()
                """,
                user_address,
                chain,
                protocol,
                snapshot_at,
                block_timestamp,
                block_number,
                source_cursor,
                total_collateral_usd,
                total_debt_usd,
                available_borrow_usd,
                health_factor,
                ltv,
                liquidation_threshold,
                json.dumps(extra_jsonb, ensure_ascii=False),
            )
            await conn.execute(
                """
                DELETE FROM loan.justlend_current_user_position_assets
                WHERE user_address = $1
                """,
                user_address,
            )
            if assets:
                await conn.executemany(
                    """
                    INSERT INTO loan.justlend_current_user_position_assets (
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
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW()
                    )
                    """,
                    [
                        (
                            user_address,
                            asset["asset_address"],
                            snapshot_at,
                            block_timestamp,
                            asset["side"],
                            asset.get("symbol"),
                            asset.get("decimals"),
                            asset["amount"],
                            asset["price_usd"],
                            asset["value_usd"],
                            json.dumps(
                                asset.get("extra_jsonb", {}), ensure_ascii=False
                            ),
                        )
                        for asset in assets
                    ],
                )


async def append_user_position_snapshot(
    pool: asyncpg.Pool,
    *,
    user_address: bytes,
    chain: str,
    protocol: str,
    snapshot_at: datetime,
    block_timestamp: datetime,
    block_number: int | None,
    source_cursor: str | None,
    total_collateral_usd: Decimal,
    total_debt_usd: Decimal,
    available_borrow_usd: Decimal,
    health_factor: Decimal,
    ltv: Decimal,
    liquidation_threshold: Decimal,
    extra_jsonb: dict[str, Any],
    assets: list[dict[str, Any]],
) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            snapshot_id = await conn.fetchval(
                """
                INSERT INTO loan.justlend_user_position_snapshots (
                    user_address,
                    chain,
                    protocol,
                    snapshot_at,
                    block_timestamp,
                    block_number,
                    source_cursor,
                    total_collateral_usd,
                    total_debt_usd,
                    available_borrow_usd,
                    health_factor,
                    ltv,
                    liquidation_threshold,
                    extra_jsonb,
                    updated_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7,
                    $8, $9, $10, $11, $12, $13, $14, NOW()
                )
                ON CONFLICT (user_address, snapshot_at) DO UPDATE SET
                    chain = EXCLUDED.chain,
                    protocol = EXCLUDED.protocol,
                    block_timestamp = EXCLUDED.block_timestamp,
                    block_number = EXCLUDED.block_number,
                    source_cursor = EXCLUDED.source_cursor,
                    total_collateral_usd = EXCLUDED.total_collateral_usd,
                    total_debt_usd = EXCLUDED.total_debt_usd,
                    available_borrow_usd = EXCLUDED.available_borrow_usd,
                    health_factor = EXCLUDED.health_factor,
                    ltv = EXCLUDED.ltv,
                    liquidation_threshold = EXCLUDED.liquidation_threshold,
                    extra_jsonb = EXCLUDED.extra_jsonb,
                    updated_at = NOW()
                RETURNING id
                """,
                user_address,
                chain,
                protocol,
                snapshot_at,
                block_timestamp,
                block_number,
                source_cursor,
                total_collateral_usd,
                total_debt_usd,
                available_borrow_usd,
                health_factor,
                ltv,
                liquidation_threshold,
                json.dumps(extra_jsonb, ensure_ascii=False),
            )
            await conn.execute(
                """
                DELETE FROM loan.justlend_user_position_snapshot_assets
                WHERE snapshot_id = $1
                """,
                snapshot_id,
            )
            if assets:
                await conn.executemany(
                    """
                    INSERT INTO loan.justlend_user_position_snapshot_assets (
                        snapshot_id,
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
                            snapshot_id,
                            user_address,
                            asset["asset_address"],
                            snapshot_at,
                            block_timestamp,
                            asset["side"],
                            asset.get("symbol"),
                            asset.get("decimals"),
                            asset["amount"],
                            asset["price_usd"],
                            asset["value_usd"],
                            json.dumps(
                                asset.get("extra_jsonb", {}), ensure_ascii=False
                            ),
                        )
                        for asset in assets
                    ],
                )


async def fetch_user_position_replay_snapshots(
    pool: asyncpg.Pool,
    *,
    user_address: bytes,
    from_ts: datetime,
    to_ts: datetime,
) -> tuple[list[asyncpg.Record], list[asyncpg.Record]]:
    async with pool.acquire() as conn:
        snapshots = await conn.fetch(
            """
            SELECT
                id,
                user_address,
                chain,
                protocol,
                snapshot_at,
                block_timestamp,
                block_number,
                source_cursor,
                total_collateral_usd,
                total_debt_usd,
                available_borrow_usd,
                health_factor,
                ltv,
                liquidation_threshold,
                extra_jsonb,
                created_at,
                updated_at
            FROM loan.justlend_user_position_snapshots
            WHERE user_address = $1
              AND snapshot_at >= $2
              AND snapshot_at <= $3
            ORDER BY snapshot_at ASC, id ASC
            """,
            user_address,
            from_ts,
            to_ts,
        )
        if not snapshots:
            return [], []
        snapshot_ids = [int(row["id"]) for row in snapshots]
        assets = await conn.fetch(
            """
            SELECT
                snapshot_id,
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
            FROM loan.justlend_user_position_snapshot_assets
            WHERE snapshot_id = ANY($1::bigint[])
            ORDER BY snapshot_at ASC, value_usd DESC, asset_address, side
            """,
            snapshot_ids,
        )
    return snapshots, assets


async def upsert_justlend_event_snapshots(
    pool: asyncpg.Pool,
    rows: list[JustLendEventPositionSnapshotRow],
) -> int:
    if not rows:
        return 0
    values = [
        (
            row.user_address,
            row.chain,
            row.protocol,
            row.tx_hash,
            row.block_number,
            row.block_timestamp,
            row.market,
            row.symbol,
            row.method_id,
            row.operation_type,
            row.has_open_position,
            row.is_liquidatable,
            row.total_collateral_usd,
            row.total_debt_usd,
            row.available_borrow_usd,
            row.discounted_collateral_usd,
            row.liquidation_buffer_usd,
            row.health_factor,
            row.ltv,
            row.liquidation_threshold,
            json.dumps(row.assets_jsonb, ensure_ascii=False),
            json.dumps(row.extra_jsonb, ensure_ascii=False),
            row.brief,
        )
        for row in rows
    ]
    async with pool.acquire() as conn:
        await conn.executemany(_SQL_UPSERT_EVENT_POSITION_SNAPSHOT, values)
    return len(rows)


async def get_justlend_event_snapshots(
    pool: asyncpg.Pool,
    *,
    user_address: bytes,
    protocol: str,
    from_ts: datetime,
    to_ts: datetime,
    market: bytes | None = None,
) -> list[Any]:
    return await pool.fetch(
        _SQL_GET_EVENT_POSITION_SNAPSHOTS,
        user_address,
        protocol,
        from_ts,
        to_ts,
        market,
    )


def _market_state_values(row: JustLendMarketStateRow) -> tuple[Any, ...]:
    return (
        row.market_address,
        row.chain,
        row.protocol,
        row.market_type,
        row.underlying_address,
        row.comptroller_address,
        row.oracle_address,
        row.symbol,
        row.underlying_symbol,
        row.underlying_decimals,
        row.jtoken_decimals,
        row.is_listed,
        row.is_entered_supported,
        row.collateral_factor,
        row.reserve_factor,
        row.borrow_cap,
        row.supply_cap,
        row.exchange_rate,
        row.cash,
        row.total_borrows,
        row.total_reserves,
        row.total_supply,
        row.utilization,
        row.borrow_rate,
        row.supply_rate,
        row.underlying_price_in_trx,
        row.price_usd,
        row.snapshot_at,
        row.block_timestamp,
        row.block_number,
        json.dumps(row.extra_jsonb or {}, ensure_ascii=False),
    )


async def upsert_justlend_market_states(
    pool: asyncpg.Pool,
    rows: list[JustLendMarketStateRow],
    *,
    update_current: bool = True,
    insert_snapshots: bool = True,
) -> int:
    if not rows:
        return 0

    current_values = [_market_state_values(row) for row in rows]
    snapshot_values = []
    if insert_snapshots:
        snapshot_values = [
            (
                row.snapshot_at,
                row.market_address,
                row.chain,
                row.protocol,
                row.market_type,
                row.underlying_address,
                row.comptroller_address,
                row.oracle_address,
                row.symbol,
                row.underlying_symbol,
                row.underlying_decimals,
                row.jtoken_decimals,
                row.is_listed,
                row.is_entered_supported,
                row.collateral_factor,
                row.reserve_factor,
                row.borrow_cap,
                row.supply_cap,
                row.exchange_rate,
                row.cash,
                row.total_borrows,
                row.total_reserves,
                row.total_supply,
                row.utilization,
                row.borrow_rate,
                row.supply_rate,
                row.underlying_price_in_trx,
                row.price_usd,
                row.block_timestamp,
                row.block_number,
                json.dumps(row.extra_jsonb or {}, ensure_ascii=False),
            )
            for row in rows
            if row.snapshot_at is not None
        ]

    async with pool.acquire() as conn:
        async with conn.transaction():
            if update_current:
                await conn.executemany(_SQL_UPSERT_MARKET_CURRENT, current_values)
            if snapshot_values:
                await conn.executemany(_SQL_INSERT_MARKET_SNAPSHOT, snapshot_values)
    return len(rows)


async def fetch_justlend_markets_current(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT
                market_address,
                chain,
                protocol,
                market_type,
                underlying_address,
                comptroller_address,
                oracle_address,
                symbol,
                underlying_symbol,
                underlying_decimals,
                jtoken_decimals,
                is_listed,
                is_entered_supported,
                collateral_factor,
                reserve_factor,
                borrow_cap,
                supply_cap,
                exchange_rate,
                cash,
                total_borrows,
                total_reserves,
                total_supply,
                utilization,
                borrow_rate,
                supply_rate,
                underlying_price_in_trx,
                price_usd,
                snapshot_at,
                block_timestamp,
                block_number,
                extra_jsonb,
                created_at,
                updated_at
            FROM loan.justlend_markets_current
            ORDER BY COALESCE(underlying_symbol, symbol, market_address), market_address
            """
        )


async def fetch_justlend_market_state(
    pool: asyncpg.Pool,
    *,
    market_address: str,
    as_of: datetime | None = None,
) -> asyncpg.Record | None:
    async with pool.acquire() as conn:
        if as_of is None:
            return await conn.fetchrow(
                """
                SELECT
                    market_address,
                    chain,
                    protocol,
                    market_type,
                    underlying_address,
                    comptroller_address,
                    oracle_address,
                    symbol,
                    underlying_symbol,
                    underlying_decimals,
                    jtoken_decimals,
                    is_listed,
                    is_entered_supported,
                    collateral_factor,
                    reserve_factor,
                    borrow_cap,
                    supply_cap,
                    exchange_rate,
                    cash,
                    total_borrows,
                    total_reserves,
                    total_supply,
                    utilization,
                    borrow_rate,
                    supply_rate,
                    underlying_price_in_trx,
                    price_usd,
                    snapshot_at,
                    block_timestamp,
                    block_number,
                    extra_jsonb,
                    created_at,
                    updated_at
                FROM loan.justlend_markets_current
                WHERE market_address = $1
                """,
                market_address,
            )

        return await conn.fetchrow(
            """
            SELECT
                market_address,
                chain,
                protocol,
                market_type,
                underlying_address,
                comptroller_address,
                oracle_address,
                symbol,
                underlying_symbol,
                underlying_decimals,
                jtoken_decimals,
                is_listed,
                is_entered_supported,
                collateral_factor,
                reserve_factor,
                borrow_cap,
                supply_cap,
                exchange_rate,
                cash,
                total_borrows,
                total_reserves,
                total_supply,
                utilization,
                borrow_rate,
                supply_rate,
                underlying_price_in_trx,
                price_usd,
                snapshot_at,
                block_timestamp,
                block_number,
                extra_jsonb,
                created_at,
                created_at AS updated_at
            FROM loan.justlend_market_snapshots
            WHERE market_address = $1
              AND snapshot_at <= $2
            ORDER BY snapshot_at DESC
            LIMIT 1
            """,
            market_address,
            as_of,
        )


async def fetch_justlend_market_state_period(
    pool: asyncpg.Pool,
    *,
    market_address: str,
    from_ts: datetime,
    to_ts: datetime,
) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT
                market_address,
                chain,
                protocol,
                market_type,
                underlying_address,
                comptroller_address,
                oracle_address,
                symbol,
                underlying_symbol,
                underlying_decimals,
                jtoken_decimals,
                is_listed,
                is_entered_supported,
                collateral_factor,
                reserve_factor,
                borrow_cap,
                supply_cap,
                exchange_rate,
                cash,
                total_borrows,
                total_reserves,
                total_supply,
                utilization,
                borrow_rate,
                supply_rate,
                underlying_price_in_trx,
                price_usd,
                snapshot_at,
                block_timestamp,
                block_number,
                extra_jsonb,
                created_at,
                created_at AS updated_at
            FROM loan.justlend_market_snapshots
            WHERE market_address = $1
              AND snapshot_at BETWEEN $2 AND $3
            ORDER BY snapshot_at ASC
            """,
            market_address,
            from_ts,
            to_ts,
        )
