"""market_collector.py
──────────────────────────────────────────────────────────────────────────────
Aave 大盘快照采集核心逻辑。

被以下模块共享使用：
  - scripts/collect_market_snapshots.py   CLI 离线批量采集
  - aave_crawler/api/service.py           API 实时按需补采

公开接口
  collect_block_snapshot(w3, pool, protocol, block, semaphore, dry_run)
  ensure_market_snapshot_table(pool, protocol)
  refresh_market_totals(pool, protocol)
  ensure_block_timestamps_table(pool)
  upsert_block_timestamps(pool, pairs)
  _block_at_timestamp(w3, target_ts, pool=None)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import asyncpg
from web3 import AsyncWeb3

from .rpc import (
    CHAINLINK_ETH_USD,
    CHAINLINK_ETH_USD_ABI,
    CONTRACTS_V3,
    DATA_PROVIDER_ABI,
    GET_RESERVE_DATA_ABI_V2,
    GET_RESERVE_DATA_ABI_V3,
    ORACLE_ABI,
    WETH_ADDRESS,
    get_contracts,
)

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────

RAY = Decimal(10**27)
RAY_INT = 10**27


# ── ABI 补充：getReserveData ──────────────────────────────────────────────────
# 已移至 rpc.py（GET_RESERVE_DATA_ABI_V3 / GET_RESERVE_DATA_ABI_V2），从那里导入。

# V3 返回 12 个字段，V2 返回 10 个字段；字段索引见 rpc.py。
_GET_RESERVE_DATA_ABI_V3 = GET_RESERVE_DATA_ABI_V3
_GET_RESERVE_DATA_ABI_V2 = GET_RESERVE_DATA_ABI_V2


# ── DDL ──────────────────────────────────────────────────────────────────────

_DDL_MARKET_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS loan.{table} (
    block_number            BIGINT          NOT NULL,
    block_timestamp         TIMESTAMPTZ     NOT NULL,
    collected_at            TIMESTAMPTZ     NOT NULL,
    token_address           TEXT            NOT NULL,
    symbol                  TEXT            NOT NULL,
    decimals                INTEGER         NOT NULL,

    -- 价格（8 位精度 USD）
    price_usd               NUMERIC(30, 8)  NOT NULL DEFAULT 0,

    -- 供给 / 借贷（链上原始整数，asset decimals）
    total_supply_raw        NUMERIC(40, 0)  NOT NULL DEFAULT 0,
    total_stable_debt_raw   NUMERIC(40, 0)  NOT NULL DEFAULT 0,
    total_variable_debt_raw NUMERIC(40, 0)  NOT NULL DEFAULT 0,

    -- USD 衍生值（8 位精度）
    total_supply_usd        NUMERIC(30, 8)  NOT NULL DEFAULT 0,
    total_debt_usd          NUMERIC(30, 8)  NOT NULL DEFAULT 0,
    available_liquidity_usd NUMERIC(30, 8)  NOT NULL DEFAULT 0,

    -- 利率（ray = 1e27，原始整数；保留以便精确还原 APY）
    liquidity_rate_ray      NUMERIC(40, 0)  NOT NULL DEFAULT 0,
    variable_borrow_rate_ray NUMERIC(40, 0) NOT NULL DEFAULT 0,
    stable_borrow_rate_ray  NUMERIC(40, 0)  NOT NULL DEFAULT 0,

    -- 利用率（0.0000～1.0000，6 位小数）
    utilization_rate        NUMERIC(10, 6)  NOT NULL DEFAULT 0,

    -- 利率累积指数（精算/插值用）
    liquidity_index_ray     NUMERIC(40, 0),
    variable_borrow_index_ray NUMERIC(40, 0),
    last_update_timestamp   TIMESTAMPTZ,

    PRIMARY KEY (block_number, token_address)
);
"""

_UPSERT_SQL = """
INSERT INTO loan.{table} (
    block_number, block_timestamp, collected_at, token_address, symbol, decimals,
    price_usd,
    total_supply_raw, total_stable_debt_raw, total_variable_debt_raw,
    total_supply_usd, total_debt_usd, available_liquidity_usd,
    liquidity_rate_ray, variable_borrow_rate_ray, stable_borrow_rate_ray,
    utilization_rate,
    liquidity_index_ray, variable_borrow_index_ray, last_update_timestamp
) VALUES (
    $1, $2, $3, $4, $5, $6,
    $7,
    $8, $9, $10,
    $11, $12, $13,
    $14, $15, $16,
    $17,
    $18, $19, $20
)
ON CONFLICT (block_number, token_address) DO UPDATE SET
    block_timestamp          = EXCLUDED.block_timestamp,
    collected_at             = EXCLUDED.collected_at,
    symbol                   = EXCLUDED.symbol,
    decimals                 = EXCLUDED.decimals,
    price_usd                = EXCLUDED.price_usd,
    total_supply_raw         = EXCLUDED.total_supply_raw,
    total_stable_debt_raw    = EXCLUDED.total_stable_debt_raw,
    total_variable_debt_raw  = EXCLUDED.total_variable_debt_raw,
    total_supply_usd         = EXCLUDED.total_supply_usd,
    total_debt_usd           = EXCLUDED.total_debt_usd,
    available_liquidity_usd  = EXCLUDED.available_liquidity_usd,
    liquidity_rate_ray       = EXCLUDED.liquidity_rate_ray,
    variable_borrow_rate_ray = EXCLUDED.variable_borrow_rate_ray,
    stable_borrow_rate_ray   = EXCLUDED.stable_borrow_rate_ray,
    utilization_rate         = EXCLUDED.utilization_rate,
    liquidity_index_ray      = EXCLUDED.liquidity_index_ray,
    variable_borrow_index_ray = EXCLUDED.variable_borrow_index_ray,
    last_update_timestamp    = EXCLUDED.last_update_timestamp;
"""

# ── 旧物化视图迁移：若存在物化视图则删除，普通表保留 ────────────────────────────
# 通过 pg_class.relkind 判断对象类型（'m'=物化视图，'r'=普通表），避免跨类型 DROP 报错
_DDL_DROP_TOTALS_VIEW = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'loan' AND c.relname = '{view}' AND c.relkind = 'm'
    ) THEN
        EXECUTE 'DROP MATERIALIZED VIEW loan.{view}';
    END IF;
END$$;
"""

_DDL_MARKET_TOTALS = """
CREATE TABLE IF NOT EXISTS loan.{view} (
    block_number             BIGINT          NOT NULL PRIMARY KEY,
    block_timestamp          TIMESTAMPTZ     NOT NULL,
    tvl_usd                  NUMERIC(30,8)   NOT NULL DEFAULT 0,
    debt_usd                 NUMERIC(30,8)   NOT NULL DEFAULT 0,
    liquidity_usd            NUMERIC(30,8)   NOT NULL DEFAULT 0,
    weighted_utilization     NUMERIC(20,8)   NOT NULL DEFAULT 0,
    weighted_supply_apy      NUMERIC(20,8)   NOT NULL DEFAULT 0,
    weighted_borrow_apy      NUMERIC(20,8)   NOT NULL DEFAULT 0,
    collected_at             TIMESTAMPTZ     NOT NULL
);
"""

_DDL_TOTALS_TS_INDEX = """
CREATE INDEX IF NOT EXISTS {view}_ts_idx
    ON loan.{view} (block_timestamp);
"""

# 滚动增量更新：将 snapshots 中尚未汇总的区块聚合写入 totals 表
_UPSERT_TOTALS_SQL = """
INSERT INTO loan.{view} (
    block_number, block_timestamp,
    tvl_usd, debt_usd, liquidity_usd,
    weighted_utilization, weighted_supply_apy, weighted_borrow_apy,
    collected_at
)
SELECT
    s.block_number,
    s.block_timestamp,
    SUM(s.total_supply_usd),
    SUM(s.total_debt_usd),
    SUM(s.total_supply_usd) - SUM(s.total_debt_usd),
    CASE WHEN SUM(s.total_supply_usd) > 0
         THEN SUM(s.utilization_rate * s.total_supply_usd) / SUM(s.total_supply_usd)
         ELSE 0 END,
    CASE WHEN SUM(s.total_supply_usd) > 0
         THEN SUM((s.liquidity_rate_ray::NUMERIC / 1e27) * s.total_supply_usd)
              / SUM(s.total_supply_usd)
         ELSE 0 END,
    CASE WHEN SUM(s.total_debt_usd) > 0
         THEN SUM((s.variable_borrow_rate_ray::NUMERIC / 1e27) * s.total_debt_usd)
              / SUM(s.total_debt_usd)
         ELSE 0 END,
    MAX(s.collected_at)
FROM loan.{table} s
WHERE NOT EXISTS (
    SELECT 1 FROM loan.{view} t WHERE t.block_number = s.block_number
)
GROUP BY s.block_number, s.block_timestamp
ON CONFLICT (block_number) DO NOTHING;
"""

_DDL_BLOCK_TIMESTAMPS = """
CREATE TABLE IF NOT EXISTS loan.eth_block_timestamps (
    block_number    BIGINT      NOT NULL PRIMARY KEY,
    block_timestamp TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS eth_block_timestamps_ts_idx
    ON loan.eth_block_timestamps (block_timestamp);
"""


# ── 表名辅助 ──────────────────────────────────────────────────────────────────


def _table_name(protocol: str) -> str:
    base = protocol.split("_")[0].lower()
    return f"aave_{base}_market_snapshots"


def _view_name(protocol: str) -> str:
    base = protocol.split("_")[0].lower()
    return f"aave_{base}_market_totals"


# ── 区块时间戳缓存 ────────────────────────────────────────────────────────────


async def ensure_block_timestamps_table(pool: asyncpg.Pool) -> None:
    """创建全局区块时间缓存表（protocol 无关，只需调用一次）。"""
    async with pool.acquire() as conn:
        await conn.execute(_DDL_BLOCK_TIMESTAMPS)
    logger.info("表 loan.eth_block_timestamps 已就绪")


async def upsert_block_timestamps(
    pool: asyncpg.Pool,
    pairs: list[tuple[int, datetime]],
) -> None:
    """批量写入 (block_number, block_timestamp)，已存在则跳过（DO NOTHING）。"""
    if not pairs:
        return
    sql = """
        INSERT INTO loan.eth_block_timestamps (block_number, block_timestamp)
        VALUES ($1, $2)
        ON CONFLICT (block_number) DO NOTHING;
    """
    async with pool.acquire() as conn:
        await conn.executemany(sql, pairs)


# ── 区块时间 → 区块号（二分搜索） ────────────────────────────────────────────


async def _block_at_timestamp(
    w3: AsyncWeb3,
    target_ts: int,
    pool: asyncpg.Pool | None = None,
) -> int:
    """
    二分搜索：返回时间戳 >= target_ts 的最小区块号。

    若提供 pool，优先从 eth_block_timestamps 查最近的上下界缩小搜索区间（
    数据库里的记录越密集，lo/hi 越近，RPC 调用次数越少），找不到双侧界时
    退回固定步长估算（post-Merge 约 12s/块，~15 次 RPC）。
    """
    GENESIS_TS = 1438269988
    MERGE_BLOCK = 15_537_393
    MERGE_TS = 1663224162

    latest_block = await w3.eth.get_block("latest")
    # BlockData 中 number/timestamp 在 web3.py 中定义为可选，但在 latest 块中总是存在
    latest_num: int = latest_block["number"]  # type: ignore[typeddict-item]
    latest_ts: int = latest_block["timestamp"]  # type: ignore[typeddict-item]

    if target_ts >= latest_ts:
        return latest_num

    # ── DB 辅助缩界：用已知的最近上/下界区块代替常数估算器 ──────────────────
    if pool is not None:
        target_dt = datetime.fromtimestamp(target_ts, tz=timezone.utc)
        lo_row, hi_row = await asyncio.gather(
            pool.fetchrow(
                "SELECT block_number FROM loan.eth_block_timestamps"
                " WHERE block_timestamp <= $1 ORDER BY block_timestamp DESC LIMIT 1",
                target_dt,
            ),
            pool.fetchrow(
                "SELECT block_number FROM loan.eth_block_timestamps"
                " WHERE block_timestamp >= $1 ORDER BY block_timestamp ASC LIMIT 1",
                target_dt,
            ),
        )
        if lo_row and hi_row:
            lo = int(lo_row["block_number"])
            hi = int(hi_row["block_number"])
            if lo == hi:
                return lo
            logger.debug(
                "DB 辅助缩界: target=%d  lo_block=%d  hi_block=%d  span=%d",
                target_ts,
                lo,
                hi,
                hi - lo,
            )
            # 区间已由数据库保证包含目标，直接二分即可
            while lo < hi:
                mid = (lo + hi) // 2
                mid_ts: int = (await w3.eth.get_block(mid))["timestamp"]  # type: ignore[typeddict-item]
                if mid_ts < target_ts:
                    lo = mid + 1
                else:
                    hi = mid
            return lo

    # ── 回退：常数估算器 + 区间扩展 ──────────────────────────────────────────
    if target_ts >= MERGE_TS:
        est = MERGE_BLOCK + (target_ts - MERGE_TS) // 12
    else:
        est = max(1, (target_ts - GENESIS_TS) * 1000 // 13_500)
    est = min(est, latest_num)

    lo = max(1, est - 500)
    hi = min(latest_num, est + 500)

    for _ in range(6):
        lo_ts: int = (await w3.eth.get_block(lo))["timestamp"]  # type: ignore[typeddict-item]
        hi_ts: int = (await w3.eth.get_block(hi))["timestamp"]  # type: ignore[typeddict-item]
        if lo_ts <= target_ts <= hi_ts:
            break
        if target_ts < lo_ts:
            lo = max(1, lo - (hi - lo))
        else:
            hi = min(latest_num, hi + (hi - lo))

    while lo < hi:
        mid = (lo + hi) // 2
        mid_ts: int = (await w3.eth.get_block(mid))["timestamp"]  # type: ignore[typeddict-item]
        if mid_ts < target_ts:
            lo = mid + 1
        else:
            hi = mid

    return lo


# ── 链上数据采集 ──────────────────────────────────────────────────────────────


async def _fetch_eth_usd_price(w3: AsyncWeb3, block: int) -> int:
    """通过 Chainlink ETH/USD 聚合器获取 ETH 价格（8 位精度 USD 原始整数）。"""
    try:
        cl = w3.eth.contract(address=CHAINLINK_ETH_USD, abi=CHAINLINK_ETH_USD_ABI)
        rd = await cl.functions.latestRoundData().call(block_identifier=block)
        if rd[1] > 0:
            return int(rd[1])
    except Exception as exc:
        logger.debug("Chainlink ETH/USD 查询失败 block=%d: %s", block, exc)

    # 降级：V3 Aave oracle
    try:
        oracle = w3.eth.contract(address=CONTRACTS_V3.oracle, abi=ORACLE_ABI)
        price = await oracle.functions.getAssetPrice(WETH_ADDRESS).call(
            block_identifier=block
        )
        if price > 0:
            return int(price)
    except Exception as exc:
        logger.warning("V3 Oracle ETH/USD 也失败 block=%d: %s", block, exc)

    return 0


async def _fetch_reserve_data_one(
    data_contract: Any,
    oracle_contract: Any,
    token_address: str,
    symbol: str,
    block: int,
    semaphore: asyncio.Semaphore,
    is_v2: bool,
) -> dict | None:
    """并发采集单个 reserve 的大盘数据（getReserveData + getAssetPrice）。"""
    addr_cs = AsyncWeb3.to_checksum_address(token_address)
    async with semaphore:
        try:
            rd_task = data_contract.functions.getReserveData(addr_cs).call(
                block_identifier=block
            )
            px_task = oracle_contract.functions.getAssetPrice(addr_cs).call(
                block_identifier=block
            )
            rd, price_raw = await asyncio.gather(
                rd_task, px_task, return_exceptions=True
            )
        except Exception as exc:
            logger.debug(
                "reserve %s(%s) block=%d 异常: %s", symbol, token_address, block, exc
            )
            return None

    if isinstance(rd, Exception):
        logger.debug("getReserveData 失败 %s: %s", symbol, rd)
        return None
    price_int: int = (
        int(price_raw) if (not isinstance(price_raw, Exception) and price_raw) else 0
    )

    if is_v2:
        avail_liq = int(rd[0])
        total_stable = int(rd[1])
        total_variable = int(rd[2])
        liquidity_rate = int(rd[3])
        variable_rate = int(rd[4])
        stable_rate = int(rd[5])
        liquidity_index = int(rd[7])
        variable_index = int(rd[8])
        last_update_ts = int(rd[9])
        total_supply = avail_liq + total_stable + total_variable
    else:
        total_supply = int(rd[2])
        total_stable = int(rd[3])
        total_variable = int(rd[4])
        liquidity_rate = int(rd[5])
        variable_rate = int(rd[6])
        stable_rate = int(rd[7])
        liquidity_index = int(rd[9])
        variable_index = int(rd[10])
        last_update_ts = int(rd[11])

    return {
        "token_address": token_address.lower(),
        "symbol": symbol,
        "price_raw": price_int,
        "total_supply_raw": total_supply,
        "total_stable_raw": total_stable,
        "total_variable_raw": total_variable,
        "liquidity_rate": liquidity_rate,
        "variable_rate": variable_rate,
        "stable_rate": stable_rate,
        "liquidity_index": liquidity_index,
        "variable_index": variable_index,
        "last_update_ts": last_update_ts,
    }


async def collect_block_snapshot(
    w3: AsyncWeb3,
    pool: asyncpg.Pool,
    protocol: str,
    block: int,
    semaphore: asyncio.Semaphore,
    dry_run: bool = False,
) -> int:
    """
    采集一个区块的大盘快照并写库。
    返回成功写入的 reserve 数量。
    """
    contracts = get_contracts(protocol)
    is_v2 = contracts.oracle_price_in_eth
    table = _table_name(protocol)

    logger.info("[%s] 开始采集 block=%d", protocol, block)

    block_meta = await w3.eth.get_block(block)
    block_ts = datetime.fromtimestamp(int(block_meta["timestamp"]), tz=timezone.utc)  # type: ignore[typeddict-item]
    collected_at = datetime.now(tz=timezone.utc)

    dp_contract = w3.eth.contract(
        address=contracts.data_provider, abi=DATA_PROVIDER_ABI
    )
    raw_reserves = await dp_contract.functions.getAllReservesTokens().call(
        block_identifier=block
    )
    reserve_tokens = [(r[0], r[1]) for r in raw_reserves]  # (symbol, address)
    logger.info("[%s] block=%d  reserve 数量: %d", protocol, block, len(reserve_tokens))

    cfg_tasks = [
        dp_contract.functions.getReserveConfigurationData(
            AsyncWeb3.to_checksum_address(addr)
        ).call(block_identifier=block)
        for _sym, addr in reserve_tokens
    ]
    cfg_results = await asyncio.gather(*cfg_tasks, return_exceptions=True)
    decimals_map: dict[str, int] = {}
    for (_sym, addr), cfg in zip(reserve_tokens, cfg_results):
        if not isinstance(cfg, Exception):
            decimals_map[addr.lower()] = int(cfg[0])  # type: ignore[index]
        else:
            decimals_map[addr.lower()] = 18

    data_abi = DATA_PROVIDER_ABI + (
        _GET_RESERVE_DATA_ABI_V2 if is_v2 else _GET_RESERVE_DATA_ABI_V3
    )
    data_contract = w3.eth.contract(address=contracts.data_provider, abi=data_abi)
    oracle_contract = w3.eth.contract(address=contracts.oracle, abi=ORACLE_ABI)

    tasks = [
        _fetch_reserve_data_one(
            data_contract, oracle_contract, addr, sym, block, semaphore, is_v2
        )
        for sym, addr in reserve_tokens
    ]
    results = await asyncio.gather(*tasks)

    eth_usd_raw: int = 0
    if is_v2:
        eth_usd_raw = await _fetch_eth_usd_price(w3, block)
        if eth_usd_raw == 0:
            logger.warning("[v2] block=%d 无法获取 ETH/USD 价格，USD 金额将为 0", block)

    if dry_run:
        valid = [r for r in results if r is not None]
        logger.info(
            "[%s][dry-run] block=%d  有效 reserve=%d，跳过写库",
            protocol,
            block,
            len(valid),
        )
        return len(valid)

    rows: list[tuple] = []
    for item in results:
        if item is None:
            continue

        addr = item["token_address"]
        dec = decimals_map.get(addr, 18)
        dec_factor = Decimal(10**dec)

        price_raw = item["price_raw"]
        if is_v2 and eth_usd_raw > 0:
            price_usd_raw = (price_raw * eth_usd_raw) // (10**18)
        else:
            price_usd_raw = price_raw

        price_usd = Decimal(price_usd_raw) / Decimal(10**8)

        supply_raw = item["total_supply_raw"]
        stable_raw = item["total_stable_raw"]
        variable_raw = item["total_variable_raw"]
        total_debt_raw = stable_raw + variable_raw

        supply_usd = price_usd * Decimal(supply_raw) / dec_factor
        debt_usd = price_usd * Decimal(total_debt_raw) / dec_factor
        avail_liq_usd = supply_usd - debt_usd

        util = (
            Decimal(total_debt_raw) / Decimal(supply_raw)
            if supply_raw > 0
            else Decimal(0)
        )

        lut = (
            datetime.fromtimestamp(item["last_update_ts"], tz=timezone.utc)
            if item["last_update_ts"] > 0
            else None
        )

        rows.append(
            (
                block,
                block_ts,
                collected_at,
                addr,
                item["symbol"],
                dec,
                price_usd.quantize(Decimal("1e-8")),
                supply_raw,
                stable_raw,
                variable_raw,
                supply_usd.quantize(Decimal("1e-8")),
                debt_usd.quantize(Decimal("1e-8")),
                max(avail_liq_usd, Decimal(0)).quantize(Decimal("1e-8")),
                item["liquidity_rate"],
                item["variable_rate"],
                item["stable_rate"],
                util.quantize(Decimal("1e-6")),
                item["liquidity_index"],
                item["variable_index"],
                lut,
            )
        )

    if rows:
        sql = _UPSERT_SQL.format(table=table)
        async with pool.acquire() as conn:
            await conn.executemany(sql, rows)
        logger.info(
            "[%s] block=%d  写入 %d 条 reserve 快照 (block_ts=%s)",
            protocol,
            block,
            len(rows),
            block_ts.isoformat(),
        )
        await upsert_block_timestamps(pool, [(block, block_ts)])
    else:
        logger.warning("[%s] block=%d  无有效数据，跳过写库", protocol, block)

    return len(rows)


# ── 表初始化 ──────────────────────────────────────────────────────────────────


async def ensure_market_snapshot_table(pool: asyncpg.Pool, protocol: str) -> None:
    table = _table_name(protocol)
    totals = _view_name(protocol)
    async with pool.acquire() as conn:
        await conn.execute(_DDL_MARKET_SNAPSHOTS.format(table=table))
        # 迁移：若旧物化视图存在则先删除（CREATE TABLE 与 CREATE MATERIALIZED VIEW 同名会冲突）
        await conn.execute(_DDL_DROP_TOTALS_VIEW.format(view=totals))
        await conn.execute(_DDL_MARKET_TOTALS.format(view=totals))
        await conn.execute(_DDL_TOTALS_TS_INDEX.format(view=totals))
    logger.info("表 loan.%s 及汇总表 loan.%s 已就绪", table, totals)


async def refresh_market_totals(pool: asyncpg.Pool, protocol: str) -> None:
    """将 market_snapshots 中新增的区块增量写入 market_totals 汇总表（滚动更新）。"""
    totals = _view_name(protocol)
    table = _table_name(protocol)
    sql = _UPSERT_TOTALS_SQL.format(view=totals, table=table)
    async with pool.acquire() as conn:
        result = await conn.execute(sql)
    logger.info("汇总表 loan.%s 滚动更新完成: %s", totals, result)
