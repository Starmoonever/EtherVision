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

# ── 协议表名配置 ────────────────────────────────────────────────────────────────
from dataclasses import dataclass


@dataclass
class ProtocolTables:
    """一套 Aave 协议对应的数据库表名配置。"""
    positions: str           # 主仓位汇总表
    reserve_positions: str   # 资产明细表
    source_table: str        # 用户地址来源表
    source_schema: str = "loan"
    address_column: str = "walletAddress"
    amount_column: str = "wethAmount_ETH"
    side: str = "collateral"  # "collateral"（ETH 抵押被清算）或 "borrow"（ETH 借入被清算）


# ── 抵押方向（ETH 下跌风险）────────────────────────────────────────────────────
TABLES_V3 = ProtocolTables(
    positions="aave_v3_eth_positions_collateral",
    reserve_positions="aave_v3_eth_reserve_positions_collateral",
    source_table="aave_v3_eth_weth_collateral",
    side="collateral",
)

TABLES_V2 = ProtocolTables(
    positions="aave_v2_eth_positions_collateral",
    reserve_positions="aave_v2_eth_reserve_positions_collateral",
    source_table="aave_v2_eth_weth_collateral",
    side="collateral",
)

# ── 借贷方向（ETH 上涨风险）────────────────────────────────────────────────────
TABLES_V3_BORROW = ProtocolTables(
    positions="aave_v3_eth_positions_borrow",
    reserve_positions="aave_v3_eth_reserve_positions_borrow",
    source_table="aave_v3_eth_weth_borrow",
    amount_column="borrowedWeth_ETH",
    side="borrow",
)

TABLES_V2_BORROW = ProtocolTables(
    positions="aave_v2_eth_positions_borrow",
    reserve_positions="aave_v2_eth_reserve_positions_borrow",
    source_table="aave_v2_eth_weth_borrow",
    amount_column="borrowedWeth_ETH",
    side="borrow",
)

_PROTOCOL_TABLES: dict[str, ProtocolTables] = {
    "v3": TABLES_V3,
    "v2": TABLES_V2,
    "v3_borrow": TABLES_V3_BORROW,
    "v2_borrow": TABLES_V2_BORROW,
}


def get_tables(protocol: str = "v3") -> ProtocolTables:
    t = _PROTOCOL_TABLES.get(protocol.lower())
    if t is None:
        raise ValueError(f"不支持的协议: {protocol!r}，可选: v2, v3, v3_borrow, v2_borrow")
    return t

# ── DDL ──────────────────────────────────────────────────────────────────────

_DDL_POSITIONS = """
CREATE TABLE IF NOT EXISTS loan.{positions} (
    user_address            TEXT        NOT NULL PRIMARY KEY,
    block_number            BIGINT      NOT NULL,
    scanned_at              TIMESTAMPTZ NOT NULL,
    total_collateral_usd    NUMERIC(30, 8) NOT NULL,
    total_debt_usd          NUMERIC(30, 8) NOT NULL,
    available_borrows_usd   NUMERIC(30, 8) NOT NULL,
    health_factor           NUMERIC(40, 18) NOT NULL,  -- ∞ 时存 1e18（19位整数位），需 40 总精度
    ltv                     NUMERIC(8, 4)   NOT NULL,   -- basis points / 10000
    liq_threshold           NUMERIC(8, 4)   NOT NULL,   -- basis points / 10000
    liq_price               NUMERIC(30, 8)  NOT NULL DEFAULT 0  -- ETH 清算触发价（USD）；0 表示无债务或无法计算
);
"""

_DDL_BORROW_POSITIONS = """
CREATE TABLE IF NOT EXISTS loan.{positions} (
    user_address            TEXT            NOT NULL PRIMARY KEY,
    block_number            BIGINT          NOT NULL,
    scanned_at              TIMESTAMPTZ     NOT NULL,
    total_collateral_usd    NUMERIC(30, 8)  NOT NULL,
    total_debt_usd          NUMERIC(30, 8)  NOT NULL,
    available_borrows_usd   NUMERIC(30, 8)  NOT NULL,
    health_factor           NUMERIC(40, 18) NOT NULL,  -- ∞ 时存 1e18
    ltv                     NUMERIC(8, 4)   NOT NULL,
    liq_threshold           NUMERIC(8, 4)   NOT NULL,
    liq_price               NUMERIC(30, 8)  NOT NULL DEFAULT 0,  -- ETH 下跌触发价（用户同时有 ETH 抵押时有意义）
    weth_debt_raw           NUMERIC(40, 0)  NOT NULL DEFAULT 0,  -- ETH 系负债合计（原始 wei）
    weth_debt_usd           NUMERIC(30, 8)  NOT NULL DEFAULT 0,  -- ETH 系负债合计 USD（扫描时刻价格）
    liq_price_rise          NUMERIC(30, 8)  NOT NULL DEFAULT 0   -- ETH 上涨触发清算价（USD）；0 表示无上涨清算风险
);
"""

_DDL_RESERVE_POSITIONS = """
CREATE TABLE IF NOT EXISTS loan.{reserve_positions} (
    user_address        TEXT        NOT NULL,
    token_address       TEXT        NOT NULL,
    symbol              TEXT        NOT NULL,
    block_number        BIGINT      NOT NULL,
    scanned_at          TIMESTAMPTZ NOT NULL,
    decimals            INTEGER     NOT NULL,
    price_usd           NUMERIC(30, 8)  NOT NULL,
    supply_raw          NUMERIC(40, 0)  NOT NULL,
    supply_usd          NUMERIC(30, 8)  NOT NULL,
    stable_debt_raw     NUMERIC(40, 0)  NOT NULL,
    variable_debt_raw   NUMERIC(40, 0)  NOT NULL,
    total_debt_usd      NUMERIC(30, 8)  NOT NULL,
    use_as_collateral   BOOLEAN     NOT NULL,
    PRIMARY KEY (user_address, token_address)
);
"""

# ── 连接池 ────────────────────────────────────────────────────────────────────

async def create_pool(pg: PostgresConfig) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn=pg.dsn, min_size=2, max_size=10)
    logger.info("PostgreSQL 连接池已创建：%s:%d/%s", pg.host, pg.port, pg.database)
    return pool  # type: ignore[return-value]


async def ensure_tables(pool: asyncpg.Pool, tables: ProtocolTables = TABLES_V3) -> None:
    """若目标表不存在则自动创建；幂等迁移旧表（精度升级、新增列、重命名）"""
    pos = tables.positions
    res = tables.reserve_positions
    async with pool.acquire() as conn:
        # ── 幂等重命名：将旧表名（无 _collateral 后缀）迁移到新名 ──────────────
        # 仅对 collateral 表执行，borrow 表是全新建的
        if tables.side == "collateral":
            old_pos = pos.replace("_collateral", "")
            old_res = res.replace("_collateral", "")
            if old_pos != pos:
                await conn.execute(f"""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'loan' AND table_name = '{old_pos}'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'loan' AND table_name = '{pos}'
                        ) THEN
                            ALTER TABLE loan."{old_pos}" RENAME TO "{pos}";
                        END IF;
                    END$$;
                """)
            if old_res != res:
                await conn.execute(f"""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'loan' AND table_name = '{old_res}'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'loan' AND table_name = '{res}'
                        ) THEN
                            ALTER TABLE loan."{old_res}" RENAME TO "{res}";
                        END IF;
                    END$$;
                """)
        # ── 建表（如不存在）─────────────────────────────────────────────────────
        if tables.side == "borrow":
            await conn.execute(_DDL_BORROW_POSITIONS.format(positions=pos))
        else:
            await conn.execute(_DDL_POSITIONS.format(positions=pos))
        await conn.execute(_DDL_RESERVE_POSITIONS.format(reserve_positions=res))
        # ── 以下迁移步骤仅适用于 collateral 表（borrow 表是全新建的）────────────
        if tables.side == "collateral":
            # 修复旧表 health_factor 列精度不足（NUMERIC(30,18) → NUMERIC(40,18)）
            await conn.execute(f"""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'loan'
                          AND table_name   = '{pos}'
                          AND column_name  = 'health_factor'
                          AND numeric_precision < 40
                    ) THEN
                        ALTER TABLE loan."{pos}"
                            ALTER COLUMN health_factor TYPE NUMERIC(40, 18);
                    END IF;
                END$$;
            """)
            # 为旧表添加 liq_price 列
            await conn.execute(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'loan'
                          AND table_name   = '{pos}'
                          AND column_name  = 'liq_price'
                    ) THEN
                        ALTER TABLE loan."{pos}"
                            ADD COLUMN liq_price NUMERIC(30, 8) NOT NULL DEFAULT 0;
                    END IF;
                END$$;
            """)
            # 将 liq_price 精度从NUMERIC(20,8)升级为NUMERIC(30,8)
            await conn.execute(f"""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'loan'
                          AND table_name   = '{pos}'
                          AND column_name  = 'liq_price'
                          AND numeric_precision < 30
                    ) THEN
                        ALTER TABLE loan."{pos}"
                            ALTER COLUMN liq_price TYPE NUMERIC(30, 8);
                    END IF;
                END$$;
            """)
            # 将 positions 表的 USD 列精度从 NUMERIC(20,8) 升级为 NUMERIC(30,8)
            for _col in ("total_collateral_usd", "total_debt_usd", "available_borrows_usd"):
                await conn.execute(f"""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = 'loan'
                              AND table_name   = '{pos}'
                              AND column_name  = '{_col}'
                              AND numeric_precision < 30
                        ) THEN
                            ALTER TABLE loan."{pos}"
                                ALTER COLUMN "{_col}" TYPE NUMERIC(30, 8);
                        END IF;
                    END$$;
                """)
        # reserve_positions 精度迁移对两种 side 均执行
        for _col in ("price_usd", "supply_usd", "total_debt_usd"):
            await conn.execute(f"""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'loan'
                          AND table_name   = '{res}'
                          AND column_name  = '{_col}'
                          AND numeric_precision < 30
                    ) THEN
                        ALTER TABLE loan."{res}"
                            ALTER COLUMN "{_col}" TYPE NUMERIC(30, 8);
                    END IF;
                END$$;
            """)
    logger.info("目标表已就绪：%s, %s", pos, res)


# ── 辅助：liq_price 计算 ─────────────────────────────────────────────────────

# ETH 系资产符号（与 service.py simulate SQL 保持一致）
# 注意：比较时统一用 r.symbol.upper()，所以这里存全大写；每当新增 ETH LST/LRT 时需同步维护
_ETH_SYMBOLS: frozenset[str] = frozenset({"WETH", "ETH", "CBETH", "WSTETH", "RETH", "WEETH", "EZETH", "RSETH", "OSETH", "ETHX"})


def _calc_liq_price(pos: UserPosition) -> Decimal:
    """计算 ETH 清算触发价。

    正确公式（HF = 1 时触发清算）：
        eth_amount × P × liq_threshold_ETH + Σ(other_i_USD × liq_threshold_i) = total_debt
        => P = (total_debt - Σ(other_i_USD × liq_threshold_i)) / (eth_amount × liq_threshold_ETH)

    每个资产使用其自身的 liquidation_threshold（来自 ReservePosition.liquidation_threshold）。
    以下情况返回 0：无债务、ETH liq_threshold=0、无 ETH 系抵押品。
    超出 ETH 合理价格上限（1000 万 USD）时截断，避免极端仓位溢出数据库列。
    """
    _LIQ_PRICE_CAP = Decimal("9999999.99999999")  # ~1000 万 USD，ETH 实际不可达

    s = pos.summary
    total_debt = _raw_to_decimal(s.total_debt_base, 8)

    if total_debt == 0:
        return Decimal("0")

    # 找第一个 ETH 系抵押品，取其独立 liq_threshold
    eth_reserve = None
    for r in pos.reserves:
        if r.symbol.upper() in _ETH_SYMBOLS and r.usage_as_collateral_enabled and r.supply_raw > 0:
            eth_reserve = r
            break

    if eth_reserve is None:
        return Decimal("0")

    eth_liq_threshold = Decimal(eth_reserve.liquidation_threshold) / Decimal(10000)
    if eth_liq_threshold == 0:
        return Decimal("0")

    eth_amount = _raw_to_decimal(eth_reserve.supply_raw, eth_reserve.decimals)
    if eth_amount == 0:
        return Decimal("0")

    # 其他（非 ETH）抵押品的安全垫，使用各自独立 liq_threshold
    other_safe = Decimal("0")
    for r in pos.reserves:
        if r.symbol.upper() in _ETH_SYMBOLS:
            continue
        if not r.usage_as_collateral_enabled or r.supply_raw == 0:
            continue
        r_liq_threshold = Decimal(r.liquidation_threshold) / Decimal(10000)
        if r_liq_threshold == 0:
            continue
        amount = _raw_to_decimal(r.supply_raw, r.decimals)
        price = _raw_to_decimal(r.price_raw, 8)
        other_safe += amount * price * r_liq_threshold

    numerator = total_debt - other_safe
    if numerator <= 0:
        # 其他抵押品已足够覆盖债务，ETH 降到 0 也不触发清算
        return Decimal("0")

    liq_price = numerator / (eth_amount * eth_liq_threshold)
    return min(liq_price, _LIQ_PRICE_CAP)


def _calc_liq_price_rise(pos: UserPosition) -> Decimal:
    """计算 ETH 上涨触发清算价（借入 WETH 场景）。

    场景：用户以稳定币/其他资产为抵押品，借入了 WETH（负债）。
    当 ETH 价格上涨时，WETH 债务的 USD 价值增大，最终超过抵押品安全边际，触发清算。

    公式（HF = 1 时触发，设 P = 未来 ETH 价格，P_now = 当前 ETH 价格）：
        ETH系抵押品贡献（USD） × P/P_now × θ + C_fixed = ETH系负债贡献（USD） × P/P_now + D_fixed
        => P = P_now × (D_fixed - C_fixed) / (eth_debt_usd_sum - eth_col_theta_usd_sum)

    其中：
        eth_debt_usd_sum     = Σ(ETH系负债 USD，按当前价格）
        eth_col_theta_usd_sum= Σ(ETH系抵押品 USD × 各自 liq_threshold）
        C_fixed              = Σ(非ETH抵押品 USD × 各自 liq_threshold）
        D_fixed              = Σ(非ETH负债 USD）

    分母 <= 0 → 净多 ETH（ETH 上涨有益）→ 无上涨清算风险 → 返回 0
    P_rise <= 0 或无 ETH 系负债 → 返回 0
    """
    _LIQ_PRICE_CAP = Decimal("9999999.99999999")

    s = pos.summary
    total_debt = _raw_to_decimal(s.total_debt_base, 8)
    if total_debt == 0:
        return Decimal("0")

    # 寻找 ETH 系资产的参考价格（用于换算 P_now）
    eth_price_now: Decimal | None = None
    for r in pos.reserves:
        if r.symbol.upper() in _ETH_SYMBOLS and r.price_raw > 0:
            eth_price_now = _raw_to_decimal(r.price_raw, 8)
            break
    if eth_price_now is None or eth_price_now == 0:
        return Decimal("0")

    # 分类汇总各项
    eth_debt_usd_sum = Decimal("0")      # ETH 系负债 USD（按当前价格）
    eth_col_theta_usd_sum = Decimal("0") # ETH 系抵押品 USD × liq_threshold
    d_fixed = Decimal("0")              # 非 ETH 负债 USD
    c_fixed = Decimal("0")              # 非 ETH 抵押品 USD × liq_threshold

    for r in pos.reserves:
        price = _raw_to_decimal(r.price_raw, 8)
        stable_amount = _raw_to_decimal(r.stable_debt_raw, r.decimals)
        variable_amount = _raw_to_decimal(r.variable_debt_raw, r.decimals)
        debt_amount = stable_amount + variable_amount
        supply_amount = _raw_to_decimal(r.supply_raw, r.decimals)

        if r.symbol.upper() in _ETH_SYMBOLS:
            # ETH 系：负债端
            if debt_amount > 0:
                eth_debt_usd_sum += debt_amount * price
            # ETH 系：抵押品端
            if supply_amount > 0 and r.usage_as_collateral_enabled:
                r_liq_threshold = Decimal(r.liquidation_threshold) / Decimal(10000)
                eth_col_theta_usd_sum += supply_amount * price * r_liq_threshold
        else:
            # 非 ETH 系：负债端
            if debt_amount > 0:
                d_fixed += debt_amount * price
            # 非 ETH 系：抵押品端
            if supply_amount > 0 and r.usage_as_collateral_enabled:
                r_liq_threshold = Decimal(r.liquidation_threshold) / Decimal(10000)
                c_fixed += supply_amount * price * r_liq_threshold

    if eth_debt_usd_sum == 0:
        # 没有 ETH 系负债，无上涨清算风险
        return Decimal("0")

    # 正确推导（HF=1，设 x = P/P_now）：
    #   (eth_col_theta_usd × x) + C_fixed = (eth_debt_usd × x) + D_fixed
    #   (eth_col_theta_usd - eth_debt_usd) × x = D_fixed - C_fixed
    #   x = (D_fixed - C_fixed) / (eth_col_theta_usd - eth_debt_usd)
    #   P_rise = P_now × x
    #
    # denom > 0：ETH 抵押品（加权）> ETH 债务 → ETH 上涨有益 → 无上涨清算风险
    # denom < 0：ETH 债务 > ETH 抵押品（加权） → ETH 上涨增大净负债 → 存在上涨清算风险
    denom = eth_col_theta_usd_sum - eth_debt_usd_sum
    if denom >= 0:
        return Decimal("0")

    numerator_usd = d_fixed - c_fixed
    # 纯做空用户：numerator = 非ETH债务 - 非ETH抵押品安全垫 < 0，denom < 0 → P_rise > 0 ✓
    liq_price_rise = eth_price_now * numerator_usd / denom
    if liq_price_rise <= 0:
        return Decimal("0")

    # 安全检查：E-Mode 用户使用更高的 liq_threshold（链上值），而 r.liquidation_threshold 来自
    # getReserveConfigurationData（普通配置，不含 E-Mode）。当 E-Mode 使阈值更高时，真实
    # denom 可能 >= 0，但我们误算为 < 0，导致 P_rise < P_now（已低于当前价格）。
    # 此类结果与 HF > 1 矛盾，应视为无上涨清算风险，返回 0。
    if liq_price_rise < eth_price_now:
        return Decimal("0")

    return min(liq_price_rise, _LIQ_PRICE_CAP)


def _calc_weth_debt(pos: UserPosition) -> tuple[Decimal, Decimal]:
    """计算 ETH 系负债汇总（raw wei 合计, USD 合计）。"""
    weth_debt_raw = Decimal("0")
    weth_debt_usd = Decimal("0")
    for r in pos.reserves:
        if r.symbol.upper() not in _ETH_SYMBOLS:
            continue
        debt_raw = r.variable_debt_raw + r.stable_debt_raw
        if debt_raw == 0:
            continue
        price = _raw_to_decimal(r.price_raw, 8)
        amount = _raw_to_decimal(debt_raw, r.decimals)
        weth_debt_raw += Decimal(debt_raw)
        weth_debt_usd += amount * price
    return weth_debt_raw, weth_debt_usd


# ── 读取用户地址 ──────────────────────────────────────────────────────────────

async def fetch_user_addresses(
    pool: asyncpg.Pool,
    tables: ProtocolTables = TABLES_V3,
    limit: int | None = None,
    incremental: bool = False,
    target_tables: ProtocolTables | None = None,
) -> list[str]:
    """从源表读取所有待查询的用户地址，跳过 amount_column = 0 的行。

    :param incremental:    True 时只返回目标仓位表中尚不存在的地址（增量模式）。
    :param target_tables:  增量模式下的目标表配置；默认与 tables 相同。
    """
    schema = tables.source_schema
    table = tables.source_table
    address_column = tables.address_column
    amount_column = tables.amount_column
    where_parts = []
    if amount_column:
        where_parts.append(f'"{amount_column}" > 0')
    if incremental:
        tgt = target_tables if target_tables is not None else tables
        where_parts.append(
            f'LOWER("{address_column}") NOT IN '
            f'(SELECT user_address FROM loan."{tgt.positions}")'
        )
    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    limit_clause = f"LIMIT {limit}" if limit else ""
    q = f'SELECT "{address_column}" FROM {schema}."{table}" {where} {limit_clause}'.strip()
    rows = await pool.fetch(q)
    addresses = [str(row[address_column]) for row in rows]
    mode_desc = "增量" if incremental else "全量"
    logger.info("读取到 %d 个用户地址（%s模式，已过滤 %s = 0 的行）", len(addresses), mode_desc, amount_column)
    return addresses


# ── 写入（UPSERT 覆盖策略） ───────────────────────────────────────────────────

def _raw_to_decimal(raw: int, decimals: int) -> Decimal:
    """链上原始整数 → Decimal，用于 NUMERIC 列"""
    return Decimal(raw) / Decimal(10 ** decimals)


def _price_decimal(price_raw: int) -> Decimal:
    """Oracle 价格：8 位精度"""
    return _raw_to_decimal(price_raw, 8)


async def upsert_positions(pool: asyncpg.Pool, positions: list[UserPosition], tables: ProtocolTables = TABLES_V3) -> None:
    """
    批量 UPSERT 仓位数据（高性能版）。

    策略：
    1. executemany 批量 UPSERT 所有用户 summary（一次 round-trip）
    2. DELETE ... WHERE user_address = ANY($1) 一次清空整批的明细旧数据
    3. copy_records_to_table 使用 PostgreSQL COPY 协议批量写入明细（比 executemany 快 10-50x）
    整批在同一个事务内完成，保证 summary 与明细一致。
    """
    pos_table = tables.positions
    res_table = tables.reserve_positions
    now = datetime.now(tz=timezone.utc)
    _MAX_HF = Decimal("1e18")
    _MAX_UINT256 = (1 << 256) - 1

    is_borrow = tables.side == "borrow"

    if is_borrow:
        _SQL_UPSERT_POS = f"""
            INSERT INTO loan."{pos_table}"
                (user_address, block_number, scanned_at,
                 total_collateral_usd, total_debt_usd, available_borrows_usd,
                 health_factor, ltv, liq_threshold,
                 liq_price, weth_debt_raw, weth_debt_usd, liq_price_rise)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT (user_address) DO UPDATE SET
                block_number          = EXCLUDED.block_number,
                scanned_at            = EXCLUDED.scanned_at,
                total_collateral_usd  = EXCLUDED.total_collateral_usd,
                total_debt_usd        = EXCLUDED.total_debt_usd,
                available_borrows_usd = EXCLUDED.available_borrows_usd,
                health_factor         = EXCLUDED.health_factor,
                ltv                   = EXCLUDED.ltv,
                liq_threshold         = EXCLUDED.liq_threshold,
                liq_price             = EXCLUDED.liq_price,
                weth_debt_raw         = EXCLUDED.weth_debt_raw,
                weth_debt_usd         = EXCLUDED.weth_debt_usd,
                liq_price_rise        = EXCLUDED.liq_price_rise;
        """
    else:
        _SQL_UPSERT_POS = f"""
            INSERT INTO loan."{pos_table}"
                (user_address, block_number, scanned_at,
                 total_collateral_usd, total_debt_usd, available_borrows_usd,
                 health_factor, ltv, liq_threshold, liq_price)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (user_address) DO UPDATE SET
                block_number          = EXCLUDED.block_number,
                scanned_at            = EXCLUDED.scanned_at,
                total_collateral_usd  = EXCLUDED.total_collateral_usd,
                total_debt_usd        = EXCLUDED.total_debt_usd,
                available_borrows_usd = EXCLUDED.available_borrows_usd,
                health_factor         = EXCLUDED.health_factor,
                ltv                   = EXCLUDED.ltv,
                liq_threshold         = EXCLUDED.liq_threshold,
                liq_price             = EXCLUDED.liq_price;
        """

    # ── 1. 构建所有 summary 行 ──────────────────────────────────────────────
    summary_rows: list[tuple] = []
    for pos in positions:
        s = pos.summary
        hf_raw = s.health_factor
        hf_decimal = _MAX_HF if hf_raw >= _MAX_UINT256 else _raw_to_decimal(hf_raw, 18)
        useraddr = pos.user_address.lower()
        base_row = (
            useraddr,
            pos.block_number,
            now,
            _raw_to_decimal(s.total_collateral_base, 8),
            _raw_to_decimal(s.total_debt_base, 8),
            _raw_to_decimal(s.available_borrows_base, 8),
            hf_decimal,
            Decimal(s.ltv) / Decimal(10000),
            Decimal(s.current_liquidation_threshold) / Decimal(10000),
            _calc_liq_price(pos),
        )
        if is_borrow:
            weth_debt_raw, weth_debt_usd = _calc_weth_debt(pos)
            summary_rows.append(base_row + (weth_debt_raw, weth_debt_usd, _calc_liq_price_rise(pos)))
        else:
            summary_rows.append(base_row)

    # ── 2. 构建所有明细行 ────────────────────────────────────────────────────
    all_user_addrs = [pos.user_address.lower() for pos in positions]
    all_reserve_rows: list[tuple] = []
    for pos in positions:
        useraddr = pos.user_address.lower()
        for r in pos.reserves:
            price = _price_decimal(r.price_raw)
            supply_dec = _raw_to_decimal(r.supply_raw, r.decimals)
            stable_dec = _raw_to_decimal(r.stable_debt_raw, r.decimals)
            variable_dec = _raw_to_decimal(r.variable_debt_raw, r.decimals)
            all_reserve_rows.append((
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
                (stable_dec + variable_dec) * price,
                r.usage_as_collateral_enabled,
            ))

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. 一次 executemany UPSERT 所有 summary
            await conn.executemany(_SQL_UPSERT_POS, summary_rows)

            # 2. 一条语句删除整批用户的旧明细
            await conn.execute(
                f'DELETE FROM loan."{res_table}" WHERE user_address = ANY($1::text[])',
                all_user_addrs,
            )

            # 3. COPY 协议批量写入所有明细（最快写入方式）
            if all_reserve_rows:
                await conn.copy_records_to_table(
                    res_table,
                    schema_name="loan",
                    records=all_reserve_rows,
                    columns=[
                        "user_address", "token_address", "symbol",
                        "block_number", "scanned_at", "decimals",
                        "price_usd", "supply_raw", "supply_usd",
                        "stable_debt_raw", "variable_debt_raw", "total_debt_usd",
                        "use_as_collateral",
                    ],
                )

    logger.debug("UPSERT 完成：%d 个用户，%d 条明细", len(positions), len(all_reserve_rows))
