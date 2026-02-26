"""
数据库层。
- 建立 asyncpg 连接池
- 创建目标表（DDL）
- 读取待处理用户列表
- 写入查询结果（UPSERT 覆盖策略）
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

import asyncpg

from .config import PostgresConfig
from .models import UserPosition

logger = logging.getLogger(__name__)

# ── DDL ──────────────────────────────────────────────────────────────────────

_DDL_POSITIONS = """
CREATE TABLE IF NOT EXISTS loan.aave_v3_eth_positions (
    user_address            TEXT        NOT NULL PRIMARY KEY,
    block_number            BIGINT      NOT NULL,
    scanned_at              TIMESTAMPTZ NOT NULL,
    total_collateral_usd    NUMERIC(20, 8) NOT NULL,
    total_debt_usd          NUMERIC(20, 8) NOT NULL,
    available_borrows_usd   NUMERIC(20, 8) NOT NULL,
    health_factor           NUMERIC(40, 18) NOT NULL,  -- ∞ 时存 1e18（19位整数位），需 40 总精度
    ltv                     NUMERIC(8, 4)   NOT NULL,   -- basis points / 10000
    liq_threshold           NUMERIC(8, 4)   NOT NULL    -- basis points / 10000
);
"""

_DDL_RESERVE_POSITIONS = """
CREATE TABLE IF NOT EXISTS loan.aave_v3_eth_reserve_positions (
    user_address        TEXT        NOT NULL,
    token_address       TEXT        NOT NULL,
    symbol              TEXT        NOT NULL,
    block_number        BIGINT      NOT NULL,
    scanned_at          TIMESTAMPTZ NOT NULL,
    decimals            INTEGER     NOT NULL,
    price_usd           NUMERIC(20, 8)  NOT NULL,
    supply_raw          NUMERIC(40, 0)  NOT NULL,
    supply_usd          NUMERIC(20, 8)  NOT NULL,
    stable_debt_raw     NUMERIC(40, 0)  NOT NULL,
    variable_debt_raw   NUMERIC(40, 0)  NOT NULL,
    total_debt_usd      NUMERIC(20, 8)  NOT NULL,
    use_as_collateral   BOOLEAN     NOT NULL,
    PRIMARY KEY (user_address, token_address)
);
"""

# ── 连接池 ────────────────────────────────────────────────────────────────────

async def create_pool(pg: PostgresConfig) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn=pg.dsn, min_size=2, max_size=10)
    logger.info("PostgreSQL 连接池已创建：%s:%d/%s", pg.host, pg.port, pg.database)
    return pool  # type: ignore[return-value]


async def ensure_tables(pool: asyncpg.Pool) -> None:
    """若目标表不存在则自动创建；若 health_factor 列精度不足则自动升级（幂等）"""
    async with pool.acquire() as conn:
        await conn.execute(_DDL_POSITIONS)
        await conn.execute(_DDL_RESERVE_POSITIONS)
        # 修复旧表 health_factor 列精度不足（NUMERIC(30,18) → NUMERIC(40,18)）
        await conn.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'loan'
                      AND table_name   = 'aave_v3_eth_positions'
                      AND column_name  = 'health_factor'
                      AND numeric_precision < 40
                ) THEN
                    ALTER TABLE loan.aave_v3_eth_positions
                        ALTER COLUMN health_factor TYPE NUMERIC(40, 18);
                END IF;
            END$$;
        """)
    logger.info("目标表已就绪：aave_v3_eth_positions, aave_v3_eth_reserve_positions")


# ── 读取用户地址 ──────────────────────────────────────────────────────────────

async def fetch_user_addresses(
    pool: asyncpg.Pool,
    schema: str = "loan",
    table: str = "all_aave_eth_users",
    address_column: str = "walletaddress",
    limit: int | None = None,
) -> list[str]:
    """从源表读取所有待查询的用户地址"""
    q = f'SELECT "{address_column}" FROM {schema}."{table}"'
    if limit:
        q += f" LIMIT {limit}"
    rows = await pool.fetch(q)
    addresses = [str(row[address_column]) for row in rows]
    logger.info("读取到 %d 个用户地址", len(addresses))
    return addresses


# ── 写入（UPSERT 覆盖策略） ───────────────────────────────────────────────────

def _raw_to_decimal(raw: int, decimals: int) -> Decimal:
    """链上原始整数 → Decimal，用于 NUMERIC 列"""
    return Decimal(raw) / Decimal(10 ** decimals)


def _price_decimal(price_raw: int) -> Decimal:
    """Oracle 价格：8 位精度"""
    return _raw_to_decimal(price_raw, 8)


async def upsert_positions(pool: asyncpg.Pool, positions: list[UserPosition]) -> None:
    """
    批量 UPSERT 仓位数据。
    策略：覆盖（ON CONFLICT DO UPDATE），reserve_positions 先删再插保证数据干净。
    每个用户在同一个事务内完成，保证 summary 与明细一致。
    """
    now = datetime.now(tz=timezone.utc)

    _SQL_UPSERT_POS = """
        INSERT INTO loan.aave_v3_eth_positions
            (user_address, block_number, scanned_at,
             total_collateral_usd, total_debt_usd, available_borrows_usd,
             health_factor, ltv, liq_threshold)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT (user_address) DO UPDATE SET
            block_number          = EXCLUDED.block_number,
            scanned_at            = EXCLUDED.scanned_at,
            total_collateral_usd  = EXCLUDED.total_collateral_usd,
            total_debt_usd        = EXCLUDED.total_debt_usd,
            available_borrows_usd = EXCLUDED.available_borrows_usd,
            health_factor         = EXCLUDED.health_factor,
            ltv                   = EXCLUDED.ltv,
            liq_threshold         = EXCLUDED.liq_threshold;
    """

    _SQL_DELETE_RESERVES = """
        DELETE FROM loan.aave_v3_eth_reserve_positions
        WHERE user_address = $1;
    """

    _SQL_INSERT_RESERVE = """
        INSERT INTO loan.aave_v3_eth_reserve_positions
            (user_address, token_address, symbol, block_number, scanned_at,
             decimals, price_usd, supply_raw, supply_usd,
             stable_debt_raw, variable_debt_raw, total_debt_usd,
             use_as_collateral)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13);
    """

    # MAX_UINT256：healthFactor = ∞ 时的值，存为极大数或特定标志值
    _MAX_HF = Decimal("1e18")   # 存为 1e18 表示无穷（UI 层特判）

    async with pool.acquire() as conn:
        async with conn.transaction():
            for pos in positions:
                s = pos.summary

                # health_factor：max uint256 表示无限，存为约定值 1e18
                _MAX_UINT256 = (1 << 256) - 1
                hf_raw = s.health_factor
                if hf_raw >= _MAX_UINT256:
                    hf_decimal = _MAX_HF
                else:
                    hf_decimal = _raw_to_decimal(hf_raw, 18)

                useraddr = pos.user_address.lower()

                await conn.execute(
                    _SQL_UPSERT_POS,
                    useraddr,
                    pos.block_number,
                    now,
                    _raw_to_decimal(s.total_collateral_base, 8),
                    _raw_to_decimal(s.total_debt_base, 8),
                    _raw_to_decimal(s.available_borrows_base, 8),
                    hf_decimal,
                    Decimal(s.ltv) / Decimal(10000),
                    Decimal(s.current_liquidation_threshold) / Decimal(10000),
                )

                # 明细：先删该用户所有行，再批量插入最新快照
                await conn.execute(_SQL_DELETE_RESERVES, useraddr)

                reserve_rows = []
                for r in pos.reserves:
                    price = _price_decimal(r.price_raw)
                    supply_dec = _raw_to_decimal(r.supply_raw, r.decimals)
                    stable_dec = _raw_to_decimal(r.stable_debt_raw, r.decimals)
                    variable_dec = _raw_to_decimal(r.variable_debt_raw, r.decimals)
                    total_debt = stable_dec + variable_dec
                    reserve_rows.append((
                        useraddr,
                        r.token_address.lower(),
                        r.symbol,
                        pos.block_number,
                        now,
                        r.decimals,
                        price,
                        Decimal(r.supply_raw),
                        supply_dec * price,
                        Decimal(r.stable_debt_raw),
                        Decimal(r.variable_debt_raw),
                        total_debt * price,
                        r.usage_as_collateral_enabled,
                    ))

                if reserve_rows:
                    await conn.executemany(_SQL_INSERT_RESERVE, reserve_rows)

    logger.debug("UPSERT 完成：%d 个用户", len(positions))
