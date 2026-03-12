"""daily_collector.py — 日级仓位快照采集。

为每个自然日（UTC 00:00:00 对应的链上区块）采集全量用户仓位，
写入统一的日级快照表（collateral / borrow 两端合并为一张表）：

    loan.aave_v{2|3}_eth_daily_positions
    loan.aave_v{2|3}_eth_daily_reserve_positions

用户来源：positions_collateral UNION positions_borrow（当前有仓位的全部用户）
区块定位：market_collector._block_at_timestamp（二分搜索 + DB 缩界）
仓位查询：rpc.fetch_user_position_at_block（eth_call at block，需 archive 节点）
计算逻辑：复用 db 中的 _calc_liq_price / _calc_liq_price_rise 等包内函数
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import cast

import asyncpg
from tqdm import tqdm
from web3 import AsyncWeb3

from .config import AppConfig
from .constants import MAX_HF, MAX_UINT256

# 包内私有计算函数（同包直接引用，避免重复实现）
from .db import (
    _calc_eth_collateral,
    _calc_liq_price,
    _calc_liq_price_rise,
    _calc_weth_debt,
    _get_weth_price,
)
from .market_collector import _block_at_timestamp
from .models import UserPosition
from .rpc import (
    EMPTY_POSITION,
    ProtocolContracts,
    build_web3,
    fetch_block_prices,
    fetch_user_position_at_block,
    get_all_reserve_tokens,
    get_contracts,
    get_reserve_config,
)
from .utils import raw_to_decimal

logger = logging.getLogger(__name__)


# ── 表名配置 ──────────────────────────────────────────────────────────────────


@dataclass
class DailyTables:
    """一套协议的日级快照表配置。"""

    positions: str  # 日级汇总表
    reserve_positions: str  # 日级 reserve 明细表
    src_col: str  # 用户来源：collateral 侧当前仓位表
    src_bor: str  # 用户来源：borrow 侧当前仓位表


DAILY_TABLES_V3 = DailyTables(
    positions="aave_v3_eth_daily_positions",
    reserve_positions="aave_v3_eth_daily_reserve_positions",
    src_col="aave_v3_eth_positions_collateral",
    src_bor="aave_v3_eth_positions_borrow",
)

DAILY_TABLES_V2 = DailyTables(
    positions="aave_v2_eth_daily_positions",
    reserve_positions="aave_v2_eth_daily_reserve_positions",
    src_col="aave_v2_eth_positions_collateral",
    src_bor="aave_v2_eth_positions_borrow",
)

_DAILY_TABLES: dict[str, DailyTables] = {
    "v3": DAILY_TABLES_V3,
    "v2": DAILY_TABLES_V2,
}


def get_daily_tables(protocol: str) -> DailyTables:
    t = _DAILY_TABLES.get(protocol.lower())
    if t is None:
        raise ValueError(f"不支持的协议: {protocol!r}，可选: v2, v3")
    return t


# ── DDL ──────────────────────────────────────────────────────────────────────

_DDL_DAILY_POSITIONS = """
CREATE TABLE IF NOT EXISTS loan."{table}" (
    snapshot_date           DATE            NOT NULL,
    user_address            TEXT            NOT NULL,
    block_number            BIGINT          NOT NULL,
    block_timestamp         TIMESTAMPTZ     NOT NULL,
    total_collateral_usd    NUMERIC(30, 8)  NOT NULL,
    total_debt_usd          NUMERIC(30, 8)  NOT NULL,
    available_borrows_usd   NUMERIC(30, 8)  NOT NULL,
    health_factor           NUMERIC(40, 18) NOT NULL,  -- MAX_HF=1e18 表示无债务（∞）
    ltv                     NUMERIC(8, 4)   NOT NULL,
    liq_threshold           NUMERIC(8, 4)   NOT NULL,
    liq_price               NUMERIC(30, 8)  NOT NULL DEFAULT 0,  -- ETH 下跌清算触发价
    liq_price_rise          NUMERIC(30, 8)  NOT NULL DEFAULT 0,  -- ETH 上涨清算触发价
    eth_collateral_amount   NUMERIC(30, 8)  NOT NULL DEFAULT 0,
    eth_collateral_usd      NUMERIC(30, 8)  NOT NULL DEFAULT 0,
    weth_debt_raw           NUMERIC(40, 0)  NOT NULL DEFAULT 0,
    weth_debt_usd           NUMERIC(30, 8)  NOT NULL DEFAULT 0,
    eth_price_usd           NUMERIC(30, 8)  NOT NULL DEFAULT 0,  -- 当日 ETH/USD
    collected_at            TIMESTAMPTZ     NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, user_address)
);
CREATE INDEX IF NOT EXISTS "{table}_user_date_idx"
    ON loan."{table}" (user_address, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS "{table}_date_liq_price_idx"
    ON loan."{table}" (snapshot_date, liq_price)
    WHERE liq_price > 0;
CREATE INDEX IF NOT EXISTS "{table}_date_liq_rise_idx"
    ON loan."{table}" (snapshot_date, liq_price_rise)
    WHERE liq_price_rise > 0;
"""

_DDL_DAILY_RESERVE_POSITIONS = """
CREATE TABLE IF NOT EXISTS loan."{table}" (
    snapshot_date       DATE            NOT NULL,
    user_address        TEXT            NOT NULL,
    token_address       TEXT            NOT NULL,
    block_number        BIGINT          NOT NULL,
    block_timestamp     TIMESTAMPTZ     NOT NULL,
    symbol              TEXT            NOT NULL,
    decimals            INTEGER         NOT NULL,
    price_usd           NUMERIC(30, 8)  NOT NULL,
    supply_raw          NUMERIC(40, 0)  NOT NULL,
    supply_usd          NUMERIC(30, 8)  NOT NULL,
    stable_debt_raw     NUMERIC(40, 0)  NOT NULL,
    variable_debt_raw   NUMERIC(40, 0)  NOT NULL,
    total_debt_usd      NUMERIC(30, 8)  NOT NULL,
    use_as_collateral   BOOLEAN         NOT NULL,
    PRIMARY KEY (snapshot_date, user_address, token_address)
);
CREATE INDEX IF NOT EXISTS "{table}_user_date_idx"
    ON loan."{table}" (user_address, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS "{table}_date_symbol_idx"
    ON loan."{table}" (snapshot_date, symbol);
"""


async def ensure_daily_tables(pool: asyncpg.Pool, protocol: str) -> None:
    """建日级快照表（幂等）。"""
    tables = get_daily_tables(protocol)
    async with pool.acquire() as conn:
        await conn.execute(_DDL_DAILY_POSITIONS.format(table=tables.positions))
        await conn.execute(
            _DDL_DAILY_RESERVE_POSITIONS.format(table=tables.reserve_positions)
        )
    logger.info("日级快照表已就绪：%s, %s", tables.positions, tables.reserve_positions)


# ── 用户列表 ──────────────────────────────────────────────────────────────────


async def fetch_daily_users(pool: asyncpg.Pool, protocol: str) -> list[str]:
    """从 positions_collateral ∪ positions_borrow 获取去重用户列表。

    这两张表的 user_address 已是小写，无需额外 lower()。
    """
    tables = get_daily_tables(protocol)
    sql = f"""
        SELECT DISTINCT user_address FROM loan."{tables.src_col}"
        UNION
        SELECT DISTINCT user_address FROM loan."{tables.src_bor}"
    """
    rows = await pool.fetch(sql)
    users = [r["user_address"] for r in rows]
    logger.info(
        "日级采集用户列表：%d 个（来源：%s ∪ %s）",
        len(users),
        tables.src_col,
        tables.src_bor,
    )
    return users


# ── 已完成日期 ─────────────────────────────────────────────────────────────────


async def get_collected_users(
    pool: asyncpg.Pool, protocol: str, snapshot_date: date
) -> set[str]:
    """返回指定日期已采集的用户地址集合（用于用户粒度断点续传）。"""
    tables = get_daily_tables(protocol)
    rows = await pool.fetch(
        f'SELECT user_address FROM loan."{tables.positions}" WHERE snapshot_date = $1',
        snapshot_date,
    )
    return {r["user_address"] for r in rows}


# ── UPSERT ────────────────────────────────────────────────────────────────────

_DAILY_POS_COLUMNS = (
    "snapshot_date",
    "user_address",
    "block_number",
    "block_timestamp",
    "total_collateral_usd",
    "total_debt_usd",
    "available_borrows_usd",
    "health_factor",
    "ltv",
    "liq_threshold",
    "liq_price",
    "liq_price_rise",
    "eth_collateral_amount",
    "eth_collateral_usd",
    "weth_debt_raw",
    "weth_debt_usd",
    "eth_price_usd",
    "collected_at",
)

_DAILY_RES_COLUMNS = (
    "snapshot_date",
    "user_address",
    "token_address",
    "block_number",
    "block_timestamp",
    "symbol",
    "decimals",
    "price_usd",
    "supply_raw",
    "supply_usd",
    "stable_debt_raw",
    "variable_debt_raw",
    "total_debt_usd",
    "use_as_collateral",
)

_UPSERT_DAILY_POS_TMPL = """
INSERT INTO loan."{table}" ({cols})
VALUES ({placeholders})
ON CONFLICT (snapshot_date, user_address) DO UPDATE SET
    block_number          = EXCLUDED.block_number,
    block_timestamp       = EXCLUDED.block_timestamp,
    total_collateral_usd  = EXCLUDED.total_collateral_usd,
    total_debt_usd        = EXCLUDED.total_debt_usd,
    available_borrows_usd = EXCLUDED.available_borrows_usd,
    health_factor         = EXCLUDED.health_factor,
    ltv                   = EXCLUDED.ltv,
    liq_threshold         = EXCLUDED.liq_threshold,
    liq_price             = EXCLUDED.liq_price,
    liq_price_rise        = EXCLUDED.liq_price_rise,
    eth_collateral_amount = EXCLUDED.eth_collateral_amount,
    eth_collateral_usd    = EXCLUDED.eth_collateral_usd,
    weth_debt_raw         = EXCLUDED.weth_debt_raw,
    weth_debt_usd         = EXCLUDED.weth_debt_usd,
    eth_price_usd         = EXCLUDED.eth_price_usd,
    collected_at          = EXCLUDED.collected_at
"""


def _build_upsert_sql(table: str) -> str:
    cols = ", ".join(f'"{c}"' for c in _DAILY_POS_COLUMNS)
    placeholders = ", ".join(f"${i + 1}" for i in range(len(_DAILY_POS_COLUMNS)))
    return _UPSERT_DAILY_POS_TMPL.format(
        table=table, cols=cols, placeholders=placeholders
    )


async def upsert_daily_positions(
    pool: asyncpg.Pool,
    batch: list[tuple[UserPosition, int]],  # (position, eth_price_raw / 8-dec)
    snapshot_date: date,
    block_number: int,
    block_timestamp: datetime,
    protocol: str,
) -> None:
    """批量 UPSERT 一天的仓位数据（汇总 + reserve 明细）。

    明细写入策略：先 DELETE (snapshot_date, user_address) 旧行，再 COPY 新行。
    与现有 upsert_positions 保持一致，避免陈旧 token 行残留。
    整批在同一事务内完成，保证汇总与明细一致。
    """
    tables = get_daily_tables(protocol)
    now = datetime.now(tz=timezone.utc)
    upsert_sql = _build_upsert_sql(tables.positions)

    summary_rows: list[tuple] = []
    all_user_addrs: list[str] = []
    all_reserve_rows: list[tuple] = []

    for pos, eth_price_raw in batch:
        s = pos.summary
        hf_raw = s.health_factor
        hf_dec = MAX_HF if hf_raw >= MAX_UINT256 else raw_to_decimal(hf_raw, 18)

        # eth_price_raw 来自 fetch_user_position_at_block，已是 8 位精度 USD 整数
        eth_price_dec = Decimal(eth_price_raw) / Decimal(10**8)
        if eth_price_dec == 0:
            # fallback：从 reserves 中查找 ETH 系资产价格
            eth_price_dec = _get_weth_price(pos)

        useraddr = pos.user_address.lower()
        all_user_addrs.append(useraddr)

        eth_col_amount, eth_col_usd = _calc_eth_collateral(pos)
        weth_debt_raw_dec, weth_debt_usd = _calc_weth_debt(pos)

        summary_rows.append(
            (
                snapshot_date,
                useraddr,
                block_number,
                block_timestamp,
                raw_to_decimal(s.total_collateral_base, 8),
                raw_to_decimal(s.total_debt_base, 8),
                raw_to_decimal(s.available_borrows_base, 8),
                hf_dec,
                Decimal(s.ltv) / Decimal(10000),
                Decimal(s.current_liquidation_threshold) / Decimal(10000),
                _calc_liq_price(pos, eth_price_dec),
                _calc_liq_price_rise(pos, eth_price_dec),
                eth_col_amount,
                eth_col_usd,
                weth_debt_raw_dec,
                weth_debt_usd,
                eth_price_dec,
                now,
            )
        )

        for r in pos.reserves:
            price = raw_to_decimal(r.price_raw, 8)
            supply_dec = raw_to_decimal(r.supply_raw, r.decimals)
            stable_dec = raw_to_decimal(r.stable_debt_raw, r.decimals)
            variable_dec = raw_to_decimal(r.variable_debt_raw, r.decimals)
            all_reserve_rows.append(
                (
                    snapshot_date,
                    useraddr,
                    r.token_address.lower(),
                    block_number,
                    block_timestamp,
                    r.symbol,
                    r.decimals,
                    price,
                    Decimal(r.supply_raw),
                    supply_dec * price,
                    Decimal(r.stable_debt_raw),
                    Decimal(r.variable_debt_raw),
                    (stable_dec + variable_dec) * price,
                    r.usage_as_collateral_enabled,
                )
            )

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. UPSERT 汇总行
            await conn.executemany(upsert_sql, summary_rows)

            # 2. DELETE 本批用户当天旧 reserve 行，再 COPY 新数据
            if all_user_addrs:
                await conn.execute(
                    f'DELETE FROM loan."{tables.reserve_positions}"'
                    f" WHERE snapshot_date = $1 AND user_address = ANY($2)",
                    snapshot_date,
                    all_user_addrs,
                )
            if all_reserve_rows:
                await conn.copy_records_to_table(
                    tables.reserve_positions,
                    schema_name="loan",
                    records=all_reserve_rows,
                    columns=list(_DAILY_RES_COLUMNS),
                )

    logger.debug(
        "UPSERT 完成：%d 条汇总 + %d 条 reserve（%s, block=%d）",
        len(summary_rows),
        len(all_reserve_rows),
        snapshot_date,
        block_number,
    )


# ── 预取公共数据 ──────────────────────────────────────────────────────────────


async def _load_token_config(w3: AsyncWeb3, contracts: ProtocolContracts) -> tuple:
    """预取 reserve token 列表和配置（不含价格，价格在 fetch_user_position_at_block 中按块实时查）。

    token 列表和配置在 30 天内基本稳定，只在首次采集时拉取一次。
    """
    reserve_tokens = await get_all_reserve_tokens(w3, contracts)
    addresses = [rt.token_address for rt in reserve_tokens]
    configs_list = await asyncio.gather(
        *[get_reserve_config(w3, a, contracts) for a in addresses],
        return_exceptions=True,
    )
    reserve_configs = {
        a: c for a, c in zip(addresses, configs_list) if not isinstance(c, Exception)
    }
    logger.info("已加载 %d 个 reserve token 配置", len(reserve_tokens))
    return reserve_tokens, reserve_configs


# ── 主流程 ────────────────────────────────────────────────────────────────────


async def run_daily_collector(
    cfg: AppConfig,
    pool: asyncpg.Pool,
    *,
    start_date: date,
    end_date: date,
    protocol: str = "v3",
    dry_run: bool = False,
    skip_existing: bool = False,
) -> None:
    """日级仓位采集主入口。

    :param start_date:    采集起始日期（含，UTC）
    :param end_date:      采集结束日期（含，UTC）
    :param protocol:      协议版本：v2 或 v3
    :param dry_run:       只查询，不写入数据库
    :param skip_existing: 跳过已有完整数据的日期（--skip-existing 断点续传）
    """
    w3 = await build_web3(cfg)
    contracts = get_contracts(protocol)

    await ensure_daily_tables(pool, protocol)

    reserve_tokens, reserve_configs = await _load_token_config(w3, contracts)

    users = await fetch_daily_users(pool, protocol)
    if not users:
        logger.warning("用户列表为空，退出")
        return

    # 生成日期序列
    days: list[date] = []
    cur = start_date
    while cur <= end_date:
        days.append(cur)
        cur += timedelta(days=1)

    if skip_existing:
        logger.info("--skip-existing：启用用户粒度断点续传，每天开始前查询已采集用户")

    if not days:
        logger.info("所有日期均已采集，退出")
        return

    logger.info(
        "开始日级采集：%s → %s，共 %d 天，%d 个用户，协议 %s%s",
        days[0],
        days[-1],
        len(days),
        len(users),
        protocol.upper(),
        "（dry-run）" if dry_run else "",
    )

    # 并发预取所有天的区块号（_block_at_timestamp 内部有 DB 缩界 + 二分搜索，IO 密集）
    day_timestamps = [
        int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
        for d in days
    ]
    block_numbers: list[int] = list(
        await asyncio.gather(
            *[_block_at_timestamp(w3, ts, pool) for ts in day_timestamps]
        )
    )

    token_addresses = [rt.token_address for rt in reserve_tokens]

    for day, block_number in zip(days, block_numbers):
        raw_block = await w3.eth.get_block(block_number)
        block_ts_raw: int = raw_block["timestamp"]  # type: ignore[typeddict-item]
        block_ts = datetime.fromtimestamp(block_ts_raw, tz=timezone.utc)

        logger.info(
            "日期 %s → block #%d（区块时间 %s UTC）",
            day,
            block_number,
            block_ts.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        # 预取本块所有资产价格（每块只查一次，所有用户共用）
        block_prices = await fetch_block_prices(
            w3, contracts, token_addresses, block_number
        )
        if not block_prices:
            logger.warning(
                "日期 %s block #%d 价格预取失败，跳过本日", day, block_number
            )
            continue

        # --skip-existing：排除当天已采集用户，避免重复 RPC 调用
        day_users = users
        if skip_existing:
            collected = await get_collected_users(pool, protocol, day)
            if collected:
                day_users = [u for u in users if u not in collected]
                logger.info(
                    "日期 %s：已采集 %d 用户，本次跳过，剩余 %d 用户待采集",
                    day,
                    len(collected),
                    len(day_users),
                )
                if not day_users:
                    logger.info("日期 %s 已全部采集，跳过", day)
                    continue

        semaphore = asyncio.Semaphore(cfg.crawler.concurrency)
        all_tasks = [
            asyncio.ensure_future(
                fetch_user_position_at_block(
                    w3,
                    addr,
                    reserve_tokens,
                    reserve_configs,
                    block_number,
                    semaphore,
                    contracts,
                    block_prices=block_prices,
                )
            )
            for addr in day_users
        ]

        pending: list[tuple[UserPosition, int]] = []
        ok = skip_count = fail = 0
        db_task: asyncio.Task | None = None

        with tqdm(total=len(day_users), desc=str(day), unit="user") as pbar:
            for coro in asyncio.as_completed(all_tasks):
                result = await coro
                pbar.update(1)

                if result is EMPTY_POSITION:
                    skip_count += 1
                    continue
                if result is None:
                    fail += 1
                    continue

                pos, eth_price_raw = cast(tuple, result)
                ok += 1
                pending.append((pos, eth_price_raw))

                if len(pending) >= cfg.crawler.batch_size:
                    if db_task is not None:
                        await db_task
                    if not dry_run:
                        db_task = asyncio.ensure_future(
                            upsert_daily_positions(
                                pool,
                                list(pending),
                                day,
                                block_number,
                                block_ts,
                                protocol,
                            )
                        )
                    pending.clear()

            if db_task is not None:
                await db_task
            if pending and not dry_run:
                await upsert_daily_positions(
                    pool, pending, day, block_number, block_ts, protocol
                )

        logger.info(
            "日期 %s 采集完成：有仓位 %d，无仓位(已平仓) %d，RPC失败 %d",
            day,
            ok,
            skip_count,
            fail,
        )

    logger.info("日级采集全部完成：%s → %s", start_date, end_date)
