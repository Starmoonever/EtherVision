"""Database helpers for the MakerDAO scaffold."""

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
_DDL_LOCK_NAME = "loan.makerdao_scaffold_ddl"

_DDL_ILKS = """
CREATE TABLE IF NOT EXISTS loan.makerdao_ilks_current (
    ilk TEXT PRIMARY KEY,
    chain TEXT NOT NULL DEFAULT 'ethereum',
    protocol TEXT NOT NULL DEFAULT 'makerdao',
    vault_type TEXT NOT NULL DEFAULT 'vault',
    gem_symbol TEXT,
    gem_address TEXT,
    join_address TEXT,
    clip_address TEXT,
    pip_address TEXT,
    debt_ceiling NUMERIC(40, 18),
    liquidation_ratio NUMERIC(40, 18),
    liquidation_penalty NUMERIC(40, 18),
    stability_fee NUMERIC(40, 18),
    dust NUMERIC(40, 18),
    extra_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_DDL_CURRENT_VAULT_POSITIONS = """
CREATE TABLE IF NOT EXISTS loan.makerdao_current_vault_positions (
    vault_uid TEXT PRIMARY KEY,
    vault_id BIGINT,
    chain TEXT NOT NULL DEFAULT 'ethereum',
    protocol TEXT NOT NULL DEFAULT 'makerdao',
    vault_type TEXT NOT NULL DEFAULT 'vault',
    ilk TEXT NOT NULL,
    urn_address TEXT NOT NULL,
    owner_address TEXT,
    proxy_address TEXT,
    snapshot_at TIMESTAMPTZ NOT NULL,
    block_timestamp TIMESTAMPTZ NOT NULL,
    block_number BIGINT,
    collateral_symbol TEXT,
    collateral_token_address TEXT,
    collateral_amount NUMERIC(40, 18) NOT NULL DEFAULT 0,
    collateral_value_usd NUMERIC(30, 8),
    debt_symbol TEXT NOT NULL DEFAULT 'DAI',
    debt_token_address TEXT,
    debt_amount NUMERIC(40, 18) NOT NULL DEFAULT 0,
    debt_value_usd NUMERIC(30, 8),
    liquidation_ratio NUMERIC(40, 18),
    liquidation_price_usd NUMERIC(30, 8),
    health_factor NUMERIC(40, 18),
    is_healthy BOOLEAN NOT NULL DEFAULT TRUE,
    extra_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_makerdao_current_vault_positions_ilk
        FOREIGN KEY (ilk)
        REFERENCES loan.makerdao_ilks_current (ilk)
        ON DELETE RESTRICT
);
"""

_DDL_SYSTEM_URN_POSITIONS = """
CREATE TABLE IF NOT EXISTS loan.makerdao_system_urn_positions_current (
    position_uid TEXT PRIMARY KEY,
    chain TEXT NOT NULL DEFAULT 'ethereum',
    protocol TEXT NOT NULL DEFAULT 'makerdao',
    position_type TEXT NOT NULL DEFAULT 'system_urn',
    ilk TEXT NOT NULL,
    urn_address TEXT NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    block_timestamp TIMESTAMPTZ NOT NULL,
    block_number BIGINT,
    collateral_symbol TEXT,
    collateral_token_address TEXT,
    collateral_amount NUMERIC(40, 18) NOT NULL DEFAULT 0,
    collateral_value_usd NUMERIC(30, 8),
    debt_symbol TEXT NOT NULL DEFAULT 'DAI',
    debt_token_address TEXT,
    debt_amount NUMERIC(40, 18) NOT NULL DEFAULT 0,
    debt_value_usd NUMERIC(30, 8),
    liquidation_ratio NUMERIC(40, 18),
    liquidation_price_usd NUMERIC(30, 8),
    health_factor NUMERIC(40, 18),
    is_healthy BOOLEAN NOT NULL DEFAULT TRUE,
    extra_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_makerdao_system_urn_positions_current_ilk
        FOREIGN KEY (ilk)
        REFERENCES loan.makerdao_ilks_current (ilk)
        ON DELETE RESTRICT
);
"""

_DDL_POSITION_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS loan.makerdao_position_snapshots (
    vault_uid TEXT NOT NULL,
    tx_hash TEXT NOT NULL,
    chain TEXT NOT NULL DEFAULT 'ethereum',
    protocol TEXT NOT NULL DEFAULT 'makerdao',
    vault_type TEXT NOT NULL DEFAULT 'vault',
    ilk TEXT NOT NULL,
    urn_address TEXT NOT NULL,
    owner_address TEXT,
    proxy_address TEXT,
    block_number BIGINT NOT NULL,
    block_timestamp TIMESTAMPTZ NOT NULL,
    operation_type TEXT,
    collateral_amount NUMERIC(40, 18) NOT NULL DEFAULT 0,
    debt_amount NUMERIC(40, 18) NOT NULL DEFAULT 0,
    collateral_value_usd NUMERIC(30, 8),
    debt_value_usd NUMERIC(30, 8),
    liquidation_price_usd NUMERIC(30, 8),
    health_factor NUMERIC(40, 18),
    is_healthy BOOLEAN NOT NULL DEFAULT TRUE,
    assets_jsonb JSONB NOT NULL DEFAULT '[]'::jsonb,
    extra_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
    brief TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (vault_uid, tx_hash),
    CONSTRAINT fk_makerdao_position_snapshots_vault
        FOREIGN KEY (vault_uid)
        REFERENCES loan.makerdao_current_vault_positions (vault_uid)
        ON DELETE CASCADE
);
"""

_DDL_WATCHER_WATERMARKS = """
CREATE TABLE IF NOT EXISTS loan.makerdao_watcher_watermarks (
    watcher_key TEXT PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cursor TEXT NOT NULL DEFAULT ''
);
"""

_DDL_SET_STORAGE_PLAIN = """
ALTER TABLE loan.makerdao_ilks_current
    ALTER COLUMN gem_address SET STORAGE PLAIN,
    ALTER COLUMN join_address SET STORAGE PLAIN,
    ALTER COLUMN clip_address SET STORAGE PLAIN,
    ALTER COLUMN pip_address SET STORAGE PLAIN;
ALTER TABLE loan.makerdao_current_vault_positions
    ALTER COLUMN urn_address SET STORAGE PLAIN,
    ALTER COLUMN owner_address SET STORAGE PLAIN,
    ALTER COLUMN proxy_address SET STORAGE PLAIN,
    ALTER COLUMN collateral_token_address SET STORAGE PLAIN,
    ALTER COLUMN debt_token_address SET STORAGE PLAIN;
ALTER TABLE loan.makerdao_system_urn_positions_current
    ALTER COLUMN urn_address SET STORAGE PLAIN,
    ALTER COLUMN collateral_token_address SET STORAGE PLAIN,
    ALTER COLUMN debt_token_address SET STORAGE PLAIN;
ALTER TABLE loan.makerdao_position_snapshots
    ALTER COLUMN urn_address SET STORAGE PLAIN,
    ALTER COLUMN owner_address SET STORAGE PLAIN,
    ALTER COLUMN proxy_address SET STORAGE PLAIN;
"""

_DDL_ILKS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_makerdao_ilks_current_updated_at
    ON loan.makerdao_ilks_current (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_makerdao_ilks_current_gem_address
    ON loan.makerdao_ilks_current (gem_address);
"""

_DDL_CURRENT_VAULT_POSITIONS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_makerdao_current_vault_positions_owner
    ON loan.makerdao_current_vault_positions (owner_address);
CREATE INDEX IF NOT EXISTS idx_makerdao_current_vault_positions_urn
    ON loan.makerdao_current_vault_positions (urn_address);
CREATE INDEX IF NOT EXISTS idx_makerdao_current_vault_positions_ilk
    ON loan.makerdao_current_vault_positions (ilk);
CREATE INDEX IF NOT EXISTS idx_makerdao_current_vault_positions_health_factor
    ON loan.makerdao_current_vault_positions (health_factor);
CREATE INDEX IF NOT EXISTS idx_makerdao_current_vault_positions_snapshot_at
    ON loan.makerdao_current_vault_positions (snapshot_at DESC);
"""

_DDL_SYSTEM_URN_POSITIONS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_makerdao_system_urn_positions_current_urn
    ON loan.makerdao_system_urn_positions_current (urn_address);
CREATE INDEX IF NOT EXISTS idx_makerdao_system_urn_positions_current_ilk
    ON loan.makerdao_system_urn_positions_current (ilk);
CREATE INDEX IF NOT EXISTS idx_makerdao_system_urn_positions_current_snapshot_at
    ON loan.makerdao_system_urn_positions_current (snapshot_at DESC);
"""

_DDL_POSITION_SNAPSHOTS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_makerdao_position_snapshots_urn_ts
    ON loan.makerdao_position_snapshots (urn_address, block_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_makerdao_position_snapshots_owner_ts
    ON loan.makerdao_position_snapshots (owner_address, block_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_makerdao_position_snapshots_tx_hash
    ON loan.makerdao_position_snapshots (tx_hash);
"""


async def create_pool(pg: PostgresConfig, timeout: float = 10.0) -> asyncpg.Pool:
    return await create_asyncpg_pool(pg, timeout=timeout, min_size=2, max_size=10)


async def ensure_makerdao_tables(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.fetchval(_DDL_LOCK_SQL, _DDL_LOCK_NAME)
            await conn.execute(_DDL_ILKS)
            await conn.execute(_DDL_CURRENT_VAULT_POSITIONS)
            await conn.execute(_DDL_SYSTEM_URN_POSITIONS)
            await conn.execute(_DDL_POSITION_SNAPSHOTS)
            await conn.execute(_DDL_WATCHER_WATERMARKS)
            await conn.execute(_DDL_SET_STORAGE_PLAIN)
            await conn.execute(_DDL_ILKS_INDEXES)
            await conn.execute(_DDL_CURRENT_VAULT_POSITIONS_INDEXES)
            await conn.execute(_DDL_SYSTEM_URN_POSITIONS_INDEXES)
            await conn.execute(_DDL_POSITION_SNAPSHOTS_INDEXES)
    logger.info("MakerDAO scaffold tables are ready")


async def fetch_ilks(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT
                ilk,
                chain,
                protocol,
                vault_type,
                gem_symbol,
                gem_address,
                join_address,
                clip_address,
                pip_address,
                debt_ceiling,
                liquidation_ratio,
                liquidation_penalty,
                stability_fee,
                dust,
                extra_jsonb,
                created_at,
                updated_at
            FROM loan.makerdao_ilks_current
            ORDER BY ilk
            """
        )


async def fetch_current_vault_positions(
    pool: asyncpg.Pool,
    *,
    address: str,
    vault_id: int | None = None,
    ilk: str | None = None,
) -> list[asyncpg.Record]:
    filters = [
        "(lower(urn_address) = lower($1) OR lower(owner_address) = lower($1) OR lower(proxy_address) = lower($1))"
    ]
    params: list[Any] = [address]
    if vault_id is not None:
        params.append(vault_id)
        filters.append(f"vault_id = ${len(params)}")
    if ilk is not None:
        params.append(ilk)
        filters.append(f"ilk = ${len(params)}")
    where_sql = " AND ".join(filters)

    async with pool.acquire() as conn:
        return await conn.fetch(
            f"""
            SELECT
                vault_uid,
                vault_id,
                chain,
                protocol,
                vault_type,
                ilk,
                urn_address,
                owner_address,
                proxy_address,
                snapshot_at,
                block_timestamp,
                block_number,
                collateral_symbol,
                collateral_token_address,
                collateral_amount,
                collateral_value_usd,
                debt_symbol,
                debt_token_address,
                debt_amount,
                debt_value_usd,
                liquidation_ratio,
                liquidation_price_usd,
                health_factor,
                is_healthy,
                extra_jsonb,
                created_at,
                updated_at
            FROM loan.makerdao_current_vault_positions
            WHERE {where_sql}
            ORDER BY snapshot_at DESC, vault_uid
            """,
            *params,
        )


async def fetch_system_urn_position(
    pool: asyncpg.Pool,
    *,
    urn: str,
    ilk: str | None = None,
) -> asyncpg.Record | None:
    params: list[Any] = [urn]
    ilk_filter = ""
    if ilk:
        params.append(ilk)
        ilk_filter = "AND ilk = $2"

    async with pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            SELECT
                position_uid,
                chain,
                protocol,
                position_type,
                ilk,
                urn_address,
                snapshot_at,
                block_timestamp,
                block_number,
                collateral_symbol,
                collateral_token_address,
                collateral_amount,
                collateral_value_usd,
                debt_symbol,
                debt_token_address,
                debt_amount,
                debt_value_usd,
                liquidation_ratio,
                liquidation_price_usd,
                health_factor,
                is_healthy,
                extra_jsonb,
                created_at,
                updated_at
            FROM loan.makerdao_system_urn_positions_current
            WHERE lower(urn_address) = lower($1)
              {ilk_filter}
            ORDER BY snapshot_at DESC
            LIMIT 1
            """,
            *params,
        )


async def upsert_ilk(pool: asyncpg.Pool, payload: dict[str, Any]) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO loan.makerdao_ilks_current (
                ilk,
                chain,
                protocol,
                vault_type,
                gem_symbol,
                gem_address,
                join_address,
                clip_address,
                pip_address,
                debt_ceiling,
                liquidation_ratio,
                liquidation_penalty,
                stability_fee,
                dust,
                extra_jsonb,
                updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9,
                $10, $11, $12, $13, $14, $15::jsonb, NOW()
            )
            ON CONFLICT (ilk) DO UPDATE SET
                chain = EXCLUDED.chain,
                protocol = EXCLUDED.protocol,
                vault_type = EXCLUDED.vault_type,
                gem_symbol = EXCLUDED.gem_symbol,
                gem_address = EXCLUDED.gem_address,
                join_address = EXCLUDED.join_address,
                clip_address = EXCLUDED.clip_address,
                pip_address = EXCLUDED.pip_address,
                debt_ceiling = EXCLUDED.debt_ceiling,
                liquidation_ratio = EXCLUDED.liquidation_ratio,
                liquidation_penalty = EXCLUDED.liquidation_penalty,
                stability_fee = EXCLUDED.stability_fee,
                dust = EXCLUDED.dust,
                extra_jsonb = EXCLUDED.extra_jsonb,
                updated_at = NOW()
            """,
            payload["ilk"],
            payload.get("chain"),
            payload.get("protocol"),
            payload.get("vault_type"),
            payload.get("gem_symbol"),
            payload.get("gem_address"),
            payload.get("join_address"),
            payload.get("clip_address"),
            payload.get("pip_address"),
            payload.get("debt_ceiling"),
            payload.get("liquidation_ratio"),
            payload.get("liquidation_penalty"),
            payload.get("stability_fee"),
            payload.get("dust"),
            json.dumps(payload.get("extra_jsonb") or {}),
        )


async def upsert_current_vault_position(
    pool: asyncpg.Pool,
    payload: dict[str, Any],
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO loan.makerdao_current_vault_positions (
                vault_uid,
                vault_id,
                chain,
                protocol,
                vault_type,
                ilk,
                urn_address,
                owner_address,
                proxy_address,
                snapshot_at,
                block_timestamp,
                block_number,
                collateral_symbol,
                collateral_token_address,
                collateral_amount,
                collateral_value_usd,
                debt_symbol,
                debt_token_address,
                debt_amount,
                debt_value_usd,
                liquidation_ratio,
                liquidation_price_usd,
                health_factor,
                is_healthy,
                extra_jsonb,
                updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9,
                $10, $11, $12, $13, $14, $15, $16, $17,
                $18, $19, $20, $21, $22, $23, $24, $25::jsonb, NOW()
            )
            ON CONFLICT (vault_uid) DO UPDATE SET
                vault_id = EXCLUDED.vault_id,
                chain = EXCLUDED.chain,
                protocol = EXCLUDED.protocol,
                vault_type = EXCLUDED.vault_type,
                ilk = EXCLUDED.ilk,
                urn_address = EXCLUDED.urn_address,
                owner_address = EXCLUDED.owner_address,
                proxy_address = EXCLUDED.proxy_address,
                snapshot_at = EXCLUDED.snapshot_at,
                block_timestamp = EXCLUDED.block_timestamp,
                block_number = EXCLUDED.block_number,
                collateral_symbol = EXCLUDED.collateral_symbol,
                collateral_token_address = EXCLUDED.collateral_token_address,
                collateral_amount = EXCLUDED.collateral_amount,
                collateral_value_usd = EXCLUDED.collateral_value_usd,
                debt_symbol = EXCLUDED.debt_symbol,
                debt_token_address = EXCLUDED.debt_token_address,
                debt_amount = EXCLUDED.debt_amount,
                debt_value_usd = EXCLUDED.debt_value_usd,
                liquidation_ratio = EXCLUDED.liquidation_ratio,
                liquidation_price_usd = EXCLUDED.liquidation_price_usd,
                health_factor = EXCLUDED.health_factor,
                is_healthy = EXCLUDED.is_healthy,
                extra_jsonb = EXCLUDED.extra_jsonb,
                updated_at = NOW()
            """,
            payload["vault_uid"],
            payload.get("vault_id"),
            payload.get("chain"),
            payload.get("protocol"),
            payload.get("vault_type"),
            payload.get("ilk"),
            payload.get("urn_address"),
            payload.get("owner_address"),
            payload.get("proxy_address"),
            payload["snapshot_at"],
            payload["block_timestamp"],
            payload.get("block_number"),
            payload.get("collateral_symbol"),
            payload.get("collateral_token_address"),
            _decimal(payload.get("collateral_amount")),
            _decimal(payload.get("collateral_value_usd")),
            payload.get("debt_symbol"),
            payload.get("debt_token_address"),
            _decimal(payload.get("debt_amount")),
            _decimal(payload.get("debt_value_usd")),
            _decimal(payload.get("liquidation_ratio")),
            _decimal(payload.get("liquidation_price_usd")),
            _decimal(payload.get("health_factor")),
            bool(payload.get("is_healthy", True)),
            json.dumps(payload.get("extra_jsonb") or {}),
        )


async def upsert_system_urn_position(
    pool: asyncpg.Pool,
    payload: dict[str, Any],
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO loan.makerdao_system_urn_positions_current (
                position_uid,
                chain,
                protocol,
                position_type,
                ilk,
                urn_address,
                snapshot_at,
                block_timestamp,
                block_number,
                collateral_symbol,
                collateral_token_address,
                collateral_amount,
                collateral_value_usd,
                debt_symbol,
                debt_token_address,
                debt_amount,
                debt_value_usd,
                liquidation_ratio,
                liquidation_price_usd,
                health_factor,
                is_healthy,
                extra_jsonb,
                updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9,
                $10, $11, $12, $13, $14, $15, $16, $17,
                $18, $19, $20, $21, $22::jsonb, NOW()
            )
            ON CONFLICT (position_uid) DO UPDATE SET
                chain = EXCLUDED.chain,
                protocol = EXCLUDED.protocol,
                position_type = EXCLUDED.position_type,
                ilk = EXCLUDED.ilk,
                urn_address = EXCLUDED.urn_address,
                snapshot_at = EXCLUDED.snapshot_at,
                block_timestamp = EXCLUDED.block_timestamp,
                block_number = EXCLUDED.block_number,
                collateral_symbol = EXCLUDED.collateral_symbol,
                collateral_token_address = EXCLUDED.collateral_token_address,
                collateral_amount = EXCLUDED.collateral_amount,
                collateral_value_usd = EXCLUDED.collateral_value_usd,
                debt_symbol = EXCLUDED.debt_symbol,
                debt_token_address = EXCLUDED.debt_token_address,
                debt_amount = EXCLUDED.debt_amount,
                debt_value_usd = EXCLUDED.debt_value_usd,
                liquidation_ratio = EXCLUDED.liquidation_ratio,
                liquidation_price_usd = EXCLUDED.liquidation_price_usd,
                health_factor = EXCLUDED.health_factor,
                is_healthy = EXCLUDED.is_healthy,
                extra_jsonb = EXCLUDED.extra_jsonb,
                updated_at = NOW()
            """,
            payload["position_uid"],
            payload.get("chain"),
            payload.get("protocol"),
            payload.get("position_type"),
            payload.get("ilk"),
            payload.get("urn_address"),
            payload["snapshot_at"],
            payload["block_timestamp"],
            payload.get("block_number"),
            payload.get("collateral_symbol"),
            payload.get("collateral_token_address"),
            _decimal(payload.get("collateral_amount")),
            _decimal(payload.get("collateral_value_usd")),
            payload.get("debt_symbol"),
            payload.get("debt_token_address"),
            _decimal(payload.get("debt_amount")),
            _decimal(payload.get("debt_value_usd")),
            _decimal(payload.get("liquidation_ratio")),
            _decimal(payload.get("liquidation_price_usd")),
            _decimal(payload.get("health_factor")),
            bool(payload.get("is_healthy", True)),
            json.dumps(payload.get("extra_jsonb") or {}),
        )


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _record_ts(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone().isoformat().replace("+00:00", "Z")
    raise TypeError(f"Unsupported datetime value: {value!r}")
