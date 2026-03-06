"""
collect_market_snapshots.py
──────────────────────────────────────────────────────────────────────────────
采集 Aave V2 / V3 历史大盘快照，通过 eth_call@block 查询 archive 节点。

每次采集指定区块高度下所有 reserve 的：
  - 总供给 / 总借贷（原始整数 + USD）
  - 存款 / 借款利率（ray 原始值，27 位精度）
  - 资产价格（USD 8 位精度）
  - 利用率（衍生，0.0～1.0）
  - 区块时间戳

结果写入 loan.aave_v2_market_snapshots / loan.aave_v3_market_snapshots，
以 (block_number, token_address) 为主键幂等 UPSERT。

运行方式
    cd backend
    # 采集单个区块
    uv run python scripts/collect_market_snapshots.py -p v3 --block 21000000
    # 采集单个日期（UTC 0 点附近区块）
    uv run python scripts/collect_market_snapshots.py -p v2 -p v3 --date 2024-06-01
    # 采集日期区间（每 7 天一个快照）
    uv run python scripts/collect_market_snapshots.py -p v3 \\
        --from-date 2024-01-01 --to-date 2025-01-01 --step-days 7

选项
    -p / --protocol     v2 | v3，可多次指定（默认 v3）
    --block    N        指定单个区块号（可与 --date 互斥使用）
    --date     DATE     指定日期（UTC 0 点），自动二分搜索最近区块
    --from-date DATE    起始日期（配合 --step-days 生成区间）
    --to-date   DATE    结束日期（默认今天）
    --step-days N       日期步长（天，默认 1）
    --rpc-concurrency N RPC 并发上限（默认 12，archive 节点可适当提高）
    --dry-run           仅打印将要采集的区块/协议，不执行 RPC/写库
    --config   PATH     配置文件路径（默认 config.yaml）
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aave_crawler.config import load_config
from aave_crawler.rpc import (CHAINLINK_ETH_USD, CHAINLINK_ETH_USD_ABI,
                              CONTRACTS_V2, CONTRACTS_V3, DATA_PROVIDER_ABI,
                              ORACLE_ABI, WETH_ADDRESS, ProtocolContracts,
                              build_web3, get_contracts)
from web3 import AsyncWeb3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────

RAY = Decimal(10**27)  # ray 精度基数（利率原始值单位）
RAY_INT = 10**27


# ── ABI 补充：getReserveData ──────────────────────────────────────────────────
# V3 返回 12 个字段（含 unbacked / accruedToTreasuryScaled）
_GET_RESERVE_DATA_ABI_V3: list[dict[str, Any]] = [
    {
        "inputs": [{"name": "asset", "type": "address"}],
        "name": "getReserveData",
        "outputs": [
            {"name": "unbacked",                 "type": "uint256"},
            {"name": "accruedToTreasuryScaled",  "type": "uint256"},
            {"name": "totalAToken",              "type": "uint256"},
            {"name": "totalStableDebt",          "type": "uint256"},
            {"name": "totalVariableDebt",        "type": "uint256"},
            {"name": "liquidityRate",            "type": "uint256"},
            {"name": "variableBorrowRate",       "type": "uint256"},
            {"name": "stableBorrowRate",         "type": "uint256"},
            {"name": "averageStableRate",        "type": "uint256"},
            {"name": "liquidityIndex",           "type": "uint256"},
            {"name": "variableBorrowIndex",      "type": "uint256"},
            {"name": "lastUpdateTimestamp",      "type": "uint40"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

# V2 返回 10 个字段（无 unbacked；供给 = availableLiquidity + 两种债务之和）
_GET_RESERVE_DATA_ABI_V2: list[dict[str, Any]] = [
    {
        "inputs": [{"name": "asset", "type": "address"}],
        "name": "getReserveData",
        "outputs": [
            {"name": "availableLiquidity",      "type": "uint256"},
            {"name": "totalStableDebt",         "type": "uint256"},
            {"name": "totalVariableDebt",       "type": "uint256"},
            {"name": "liquidityRate",           "type": "uint256"},
            {"name": "variableBorrowRate",      "type": "uint256"},
            {"name": "stableBorrowRate",        "type": "uint256"},
            {"name": "averageStableBorrowRate", "type": "uint256"},
            {"name": "liquidityIndex",          "type": "uint256"},
            {"name": "variableBorrowIndex",     "type": "uint256"},
            {"name": "lastUpdateTimestamp",     "type": "uint40"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]


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


def _table_name(protocol: str) -> str:
    base = protocol.split("_")[0].lower()  # v3_borrow → v3
    return f"aave_{base}_market_snapshots"


def _view_name(protocol: str) -> str:
    base = protocol.split("_")[0].lower()
    return f"aave_{base}_market_totals"


# ── DDL：物化视图（按区块汇总全市场） ─────────────────────────────────────────

_DDL_MARKET_TOTALS = """
CREATE MATERIALIZED VIEW IF NOT EXISTS loan.{view} AS
SELECT
    block_number,
    block_timestamp,
    -- 全市场规模
    SUM(total_supply_usd)                           AS tvl_usd,
    SUM(total_debt_usd)                             AS debt_usd,
    SUM(total_supply_usd) - SUM(total_debt_usd)     AS liquidity_usd,
    -- 加权平均利用率（以 total_supply_usd 为权重）
    CASE WHEN SUM(total_supply_usd) > 0
         THEN SUM(utilization_rate * total_supply_usd) / SUM(total_supply_usd)
         ELSE 0
    END                                             AS weighted_utilization,
    -- 加权平均存款利率（APY ≈ liquidity_rate_ray / 1e27，以供给 USD 为权）
    CASE WHEN SUM(total_supply_usd) > 0
         THEN SUM((liquidity_rate_ray::NUMERIC / 1e27) * total_supply_usd)
              / SUM(total_supply_usd)
         ELSE 0
    END                                             AS weighted_supply_apy,
    -- 加权平均浮动借款利率（以债务 USD 为权）
    CASE WHEN SUM(total_debt_usd) > 0
         THEN SUM((variable_borrow_rate_ray::NUMERIC / 1e27) * total_debt_usd)
              / SUM(total_debt_usd)
         ELSE 0
    END                                             AS weighted_borrow_apy,
    -- 采集时间（取该区块所有 reserve 中最新的 collected_at）
    MAX(collected_at)                               AS collected_at
FROM loan.{table}
GROUP BY block_number, block_timestamp
ORDER BY block_number;
"""

# 物化视图刷新（CONCURRENTLY 要求存在唯一索引，首次创建后再建索引；
# 首次采集时 CONCURRENTLY 尚不可用，改用普通 REFRESH）
_DDL_TOTALS_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS {view}_block_idx
    ON loan.{view} (block_number);
"""

# 物化视图 block_timestamp 索引（时间范围查询入口）
_DDL_TOTALS_TS_INDEX = """
CREATE INDEX IF NOT EXISTS {view}_ts_idx
    ON loan.{view} (block_timestamp);
"""

# ── DDL：区块时间缓存表 ───────────────────────────────────────────────────────
# 全局共用，与协议无关；用于：
#   1. 跳过重复的二分搜索 RPC（date→block）
#   2. 为外部查询提供 timestamp ↔ block_number 映射

_DDL_BLOCK_TIMESTAMPS = """
CREATE TABLE IF NOT EXISTS loan.eth_block_timestamps (
    block_number    BIGINT      NOT NULL PRIMARY KEY,
    block_timestamp TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS eth_block_timestamps_ts_idx
    ON loan.eth_block_timestamps (block_timestamp);
"""


# ── 区块时间 → 区块号（二分搜索） ────────────────────────────────────────────

async def _block_at_timestamp(w3: AsyncWeb3, target_ts: int) -> int:
    """
    二分搜索：返回时间戳 >= target_ts 的最小区块号。
    以 post-Merge 约 12s/块、genesis 2015-07-30 为初始估算，之后快速收敛（~15 次 RPC）。
    """
    GENESIS_TS = 1438269988  # 以太坊 genesis 时间戳
    MERGE_BLOCK = 15_537_393  # The Merge（2022-09-15）
    MERGE_TS = 1663224162

    latest_block = await w3.eth.get_block("latest")
    latest_num: int = latest_block["number"]
    latest_ts: int = latest_block["timestamp"]

    if target_ts >= latest_ts:
        return latest_num

    # 初始估算（clamp 到 latest_num，避免近期日期因出块时间略快/慢导致越界）
    if target_ts >= MERGE_TS:
        est = MERGE_BLOCK + (target_ts - MERGE_TS) // 12
    else:
        est = max(1, (target_ts - GENESIS_TS) * 1000 // 13_500)  # pre-Merge ~13.5s
    est = min(est, latest_num)

    lo = max(1, est - 500)
    hi = min(latest_num, est + 500)

    # 扩展区间直到确实包含目标时间戳
    for _ in range(6):
        lo_ts = (await w3.eth.get_block(lo))["timestamp"]
        hi_ts = (await w3.eth.get_block(hi))["timestamp"]
        if lo_ts <= target_ts <= hi_ts:
            break
        if target_ts < lo_ts:
            lo = max(1, lo - (hi - lo))
        else:
            hi = min(latest_num, hi + (hi - lo))

    # 标准二分
    while lo < hi:
        mid = (lo + hi) // 2
        mid_ts = (await w3.eth.get_block(mid))["timestamp"]
        if mid_ts < target_ts:
            lo = mid + 1
        else:
            hi = mid

    return lo


async def _date_to_block(
    w3: AsyncWeb3,
    date_str: str,
    pool: "asyncpg.Pool | None" = None,
) -> int:
    """将 'YYYY-MM-DD'（UTC 0 点）转换为最近区块号。

    若提供 pool，先从 eth_block_timestamps 缓存表查询（误差窗口 ±10 分钟），
    命中则跳过二分搜索；未命中则执行 RPC 搜索后写入缓存。
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    ts = int(dt.timestamp())

    if pool is not None:
        # 查缓存：找 block_timestamp 最接近 UTC 0 点且在 ±10 分钟内的区块
        row = await pool.fetchrow(
            """
            SELECT block_number, block_timestamp
            FROM loan.eth_block_timestamps
            WHERE block_timestamp BETWEEN $1 AND $2
            ORDER BY ABS(EXTRACT(EPOCH FROM (block_timestamp - $3))) ASC
            LIMIT 1
            """,
            dt - timedelta(minutes=10),
            dt + timedelta(minutes=10),
            dt,
        )
        if row:
            logger.info(
                "日期 %s → 区块 %d (缓存命中，block_ts=%s)",
                date_str, row["block_number"], row["block_timestamp"].isoformat(),
            )
            return int(row["block_number"])

    block = await _block_at_timestamp(w3, ts)
    block_meta = await w3.eth.get_block(block)
    block_ts = datetime.fromtimestamp(int(block_meta["timestamp"]), tz=timezone.utc)
    logger.info("日期 %s (unix=%d) → 区块 %d (block_ts=%s)", date_str, ts, block, block_ts.isoformat())

    if pool is not None:
        await upsert_block_timestamps(pool, [(block, block_ts)])

    return block


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
            rd, price_raw = await asyncio.gather(rd_task, px_task, return_exceptions=True)
        except Exception as exc:
            logger.debug("reserve %s(%s) block=%d 异常: %s", symbol, token_address, block, exc)
            return None

    if isinstance(rd, Exception):
        logger.debug("getReserveData 失败 %s: %s", symbol, rd)
        return None
    price_int: int = int(price_raw) if (not isinstance(price_raw, Exception) and price_raw) else 0

    if is_v2:
        # V2：(availableLiquidity, totalStableDebt, totalVariableDebt,
        #       liquidityRate, variableBorrowRate, stableBorrowRate,
        #       averageStableBorrowRate, liquidityIndex, variableBorrowIndex,
        #       lastUpdateTimestamp)
        avail_liq        = int(rd[0])
        total_stable     = int(rd[1])
        total_variable   = int(rd[2])
        liquidity_rate   = int(rd[3])
        variable_rate    = int(rd[4])
        stable_rate      = int(rd[5])
        liquidity_index  = int(rd[7])
        variable_index   = int(rd[8])
        last_update_ts   = int(rd[9])
        # V2 全部供给 = 池内剩余 + 全部债务
        total_supply     = avail_liq + total_stable + total_variable
    else:
        # V3：(unbacked, accruedToTreasuryScaled, totalAToken,
        #       totalStableDebt, totalVariableDebt,
        #       liquidityRate, variableBorrowRate, stableBorrowRate,
        #       averageStableRate, liquidityIndex, variableBorrowIndex,
        #       lastUpdateTimestamp)
        total_supply     = int(rd[2])
        total_stable     = int(rd[3])
        total_variable   = int(rd[4])
        liquidity_rate   = int(rd[5])
        variable_rate    = int(rd[6])
        stable_rate      = int(rd[7])
        liquidity_index  = int(rd[9])
        variable_index   = int(rd[10])
        last_update_ts   = int(rd[11])

    return {
        "token_address":    token_address.lower(),
        "symbol":           symbol,
        "price_raw":        price_int,
        "total_supply_raw": total_supply,
        "total_stable_raw": total_stable,
        "total_variable_raw": total_variable,
        "liquidity_rate":   liquidity_rate,
        "variable_rate":    variable_rate,
        "stable_rate":      stable_rate,
        "liquidity_index":  liquidity_index,
        "variable_index":   variable_index,
        "last_update_ts":   last_update_ts,
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

    # 获取区块时间戳
    block_meta = await w3.eth.get_block(block)
    block_ts = datetime.fromtimestamp(int(block_meta["timestamp"]), tz=timezone.utc)
    collected_at = datetime.now(tz=timezone.utc)

    # 获取所有 reserve 列表（at block）
    dp_contract = w3.eth.contract(
        address=contracts.data_provider, abi=DATA_PROVIDER_ABI
    )
    raw_reserves = await dp_contract.functions.getAllReservesTokens().call(
        block_identifier=block
    )
    reserve_tokens = [(r[0], r[1]) for r in raw_reserves]  # (symbol, address)
    logger.info("[%s] block=%d  reserve 数量: %d", protocol, block, len(reserve_tokens))

    # 获取 reserve 配置（主要用于 decimals；可不指定 block，配置极少变）
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
            decimals_map[addr.lower()] = int(cfg[0])
        else:
            decimals_map[addr.lower()] = 18  # fallback

    # 选择对应版本的 getReserveData ABI
    data_abi = DATA_PROVIDER_ABI + (
        _GET_RESERVE_DATA_ABI_V2 if is_v2 else _GET_RESERVE_DATA_ABI_V3
    )
    data_contract = w3.eth.contract(address=contracts.data_provider, abi=data_abi)
    oracle_contract = w3.eth.contract(address=contracts.oracle, abi=ORACLE_ABI)

    # 并发采集所有 reserve 大盘数据
    tasks = [
        _fetch_reserve_data_one(
            data_contract, oracle_contract,
            addr, sym, block, semaphore, is_v2
        )
        for sym, addr in reserve_tokens
    ]
    results = await asyncio.gather(*tasks)

    # V2 需要将 ETH 计价价格归一化为 USD
    eth_usd_raw: int = 0
    if is_v2:
        eth_usd_raw = await _fetch_eth_usd_price(w3, block)
        if eth_usd_raw == 0:
            logger.warning(
                "[v2] block=%d 无法获取 ETH/USD 价格，USD 金额将为 0", block
            )

    if dry_run:
        valid = [r for r in results if r is not None]
        logger.info(
            "[%s][dry-run] block=%d  有效 reserve=%d，跳过写库",
            protocol, block, len(valid),
        )
        return len(valid)

    # 写库
    rows: list[tuple] = []
    for item in results:
        if item is None:
            continue

        addr   = item["token_address"]
        sym    = item["symbol"]
        dec    = decimals_map.get(addr, 18)
        dec_factor = Decimal(10**dec)

        # 价格：V2 转换 ETH→USD，V3 直接使用
        price_raw = item["price_raw"]
        if is_v2 and eth_usd_raw > 0:
            # oracle_price(ETH/18dec) * eth_usd(USD/8dec) / 1e18 → USD/8dec
            price_usd_raw = (price_raw * eth_usd_raw) // (10**18)
        else:
            price_usd_raw = price_raw  # V3 USD/8dec

        price_usd = Decimal(price_usd_raw) / Decimal(10**8)

        supply_raw   = item["total_supply_raw"]
        stable_raw   = item["total_stable_raw"]
        variable_raw = item["total_variable_raw"]
        total_debt_raw = stable_raw + variable_raw

        # USD 换算（price_usd * amount / 10^decimals）
        supply_usd   = price_usd * Decimal(supply_raw) / dec_factor
        debt_usd     = price_usd * Decimal(total_debt_raw) / dec_factor
        avail_liq_usd = supply_usd - debt_usd

        # 利用率 = 总债务 / 总供给（避免除零）
        if supply_raw > 0:
            util = Decimal(total_debt_raw) / Decimal(supply_raw)
        else:
            util = Decimal(0)

        # last_update_timestamp（链上 unix → timestamptz）
        lut = datetime.fromtimestamp(item["last_update_ts"], tz=timezone.utc) \
            if item["last_update_ts"] > 0 else None

        rows.append((
            block,                              # $1
            block_ts,                           # $2
            collected_at,                       # $3
            addr,                               # $4
            sym,                                # $5
            dec,                                # $6
            price_usd.quantize(Decimal("1e-8")),# $7  price_usd
            supply_raw,                         # $8  total_supply_raw
            stable_raw,                         # $9  total_stable_debt_raw
            variable_raw,                       # $10 total_variable_debt_raw
            supply_usd.quantize(Decimal("1e-8")),       # $11 total_supply_usd
            debt_usd.quantize(Decimal("1e-8")),         # $12 total_debt_usd
            max(avail_liq_usd, Decimal(0)).quantize(Decimal("1e-8")),  # $13
            item["liquidity_rate"],             # $14 liquidity_rate_ray
            item["variable_rate"],              # $15 variable_borrow_rate_ray
            item["stable_rate"],                # $16 stable_borrow_rate_ray
            util.quantize(Decimal("1e-6")),     # $17 utilization_rate
            item["liquidity_index"],            # $18 liquidity_index_ray
            item["variable_index"],             # $19 variable_borrow_index_ray
            lut,                                # $20 last_update_timestamp
        ))

    if rows:
        sql = _UPSERT_SQL.format(table=table)
        async with pool.acquire() as conn:
            await conn.executemany(sql, rows)
        logger.info(
            "[%s] block=%d  写入 %d 条 reserve 快照 (block_ts=%s)",
            protocol, block, len(rows), block_ts.isoformat(),
        )
        # 顺手写入区块时间缓存
        await upsert_block_timestamps(pool, [(block, block_ts)])
    else:
        logger.warning("[%s] block=%d  无有效数据，跳过写库", protocol, block)

    return len(rows)


# ── 表初始化 ──────────────────────────────────────────────────────────────────

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


async def ensure_market_snapshot_table(pool: asyncpg.Pool, protocol: str) -> None:
    table = _table_name(protocol)
    view  = _view_name(protocol)
    async with pool.acquire() as conn:
        # 1. 明细表
        await conn.execute(_DDL_MARKET_SNAPSHOTS.format(table=table))
        # 2. 物化视图（幂等：IF NOT EXISTS）
        await conn.execute(_DDL_MARKET_TOTALS.format(table=table, view=view))
        # 3. block_number 唯一索引（支持 REFRESH CONCURRENTLY）
        await conn.execute(_DDL_TOTALS_INDEX.format(view=view))
        # 4. block_timestamp 索引（时间范围查询）
        await conn.execute(_DDL_TOTALS_TS_INDEX.format(view=view))
    logger.info("表 loan.%s 及物化视图 loan.%s 已就绪", table, view)


async def refresh_market_totals(pool: asyncpg.Pool, protocol: str) -> None:
    """刷新物化视图（在每次写入新快照后调用）。"""
    view = _view_name(protocol)
    async with pool.acquire() as conn:
        # 有唯一索引时可用 CONCURRENTLY（不锁读）
        try:
            await conn.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY loan.{view};")
            logger.info("物化视图 loan.%s 已刷新（CONCURRENTLY）", view)
        except Exception:
            # 索引尚未建立时降级
            await conn.execute(f"REFRESH MATERIALIZED VIEW loan.{view};")
            logger.info("物化视图 loan.%s 已刷新", view)


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="采集 Aave V2/V3 历史大盘快照（eth_call@block）"
    )
    p.add_argument(
        "-p", "--protocol",
        dest="protocols",
        action="append",
        default=[],
        choices=["v2", "v3"],
        metavar="PROTOCOL",
        help="v2 | v3，可多次指定（默认 v3）",
    )
    # 区块来源（三选其一）
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--block", type=int, help="指定单个区块号")
    group.add_argument("--date", type=str, metavar="YYYY-MM-DD", help="指定日期（UTC 0 点）")
    group.add_argument("--from-date", type=str, metavar="YYYY-MM-DD",
                       help="起始日期（配合 --step-days）")

    p.add_argument("--to-date",   type=str, default="", metavar="YYYY-MM-DD",
                   help="结束日期（默认今天，配合 --from-date）")
    p.add_argument("--step-days", type=int, default=1,
                   help="日期步长（天，默认 1）")
    p.add_argument("--rpc-concurrency", type=int, default=12,
                   help="RPC 并发上限（默认 12）")
    p.add_argument("--dry-run", action="store_true",
                   help="仅打印将要采集的区块/协议，不执行 RPC/写库")
    p.add_argument("--config", type=str, default="",
                   help="配置文件路径（默认 config.yaml）")
    return p.parse_args()


async def _main() -> None:
    args = _parse_args()

    protocols = args.protocols or ["v3"]
    cfg = load_config(args.config or None)

    # 调整日志级别
    logging.getLogger().setLevel(getattr(logging, cfg.log_level.upper(), logging.INFO))

    # 构建 Web3（所有协议共用同一 RPC 连接，因为都在 Ethereum Mainnet）
    w3 = await build_web3(cfg)
    semaphore = asyncio.Semaphore(args.rpc_concurrency)

    # 提前创建 DB 连接池（date→block 缓存查询需要）
    pool = await asyncpg.create_pool(dsn=cfg.postgres.dsn, min_size=2, max_size=5)
    try:
        # 确保缓存表存在（全局，与协议无关，只建一次）
        await ensure_block_timestamps_table(pool)

        # 确定目标区块列表
        target_blocks: list[int] = []

        if args.block is not None:
            target_blocks = [args.block]

        elif args.date:
            target_blocks = [await _date_to_block(w3, args.date, pool)]

        else:  # args.from_date
            end_str = args.to_date or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            start_dt = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end_dt   = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            step     = timedelta(days=args.step_days)

            date_list: list[str] = []
            cur = start_dt
            while cur <= end_dt:
                date_list.append(cur.strftime("%Y-%m-%d"))
                cur += step

            logger.info("日期区间 %s → %s，步长 %d 天，共 %d 个时间点",
                        args.from_date, end_str, args.step_days, len(date_list))

            # 串行将日期转换为区块号（缓存命中时跳过 RPC 二分搜索）
            for d in date_list:
                target_blocks.append(await _date_to_block(w3, d, pool))

        logger.info("目标区块: %s", target_blocks)
        logger.info("目标协议: %s", protocols)

        if args.dry_run:
            logger.info("[dry-run] 模式，不执行 RPC 采集，退出。")
            for prot in protocols:
                for blk in target_blocks:
                    logger.info("[dry-run] protocol=%s  block=%d", prot, blk)
            return

        # 确保协议明细表及物化视图存在
        for prot in protocols:
            await ensure_market_snapshot_table(pool, prot)

        # 逐区块、逐协议采集
        total_written = 0
        for blk in target_blocks:
            for prot in protocols:
                written = await collect_block_snapshot(
                    w3, pool, prot, blk, semaphore, dry_run=False
                )
                total_written += written

        # 所有区块写入完成后统一刷新物化视图
        for prot in protocols:
            await refresh_market_totals(pool, prot)

        logger.info("采集完成，共写入 %d 条 reserve 快照记录。", total_written)
    finally:
        await pool.close()  # type: ignore[union-attr]


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
