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
from collections import defaultdict
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
from .market_collector import _block_at_timestamp, upsert_block_timestamps
from .models import AccountSummary, UserPosition
from .rpc import (
    EMPTY_POSITION,
    ProtocolContracts,
    ReserveIndex,
    build_web3,
    fetch_batch_account_summaries,
    fetch_block_prices,
    fetch_reserve_indices,
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


# ── Reserve Indices（从 market_snapshots 读取） ───────────────────────────────


async def load_reserve_indices_from_db(
    pool: asyncpg.Pool,
    block_number: int,
    protocol: str,
) -> dict[str, ReserveIndex]:
    """从 market_snapshots 按 block_number 精确读取所有 reserve 的利率指数（0 次 RPC）。

    返回 dict[token_address_lower, ReserveIndex]。
    若 market_collector 尚未为该 block 写入快照，返回空字典（调用方应降级为 RPC）。
    """
    base = protocol.split("_")[0].lower()
    table = f"aave_{base}_market_snapshots"
    rows = await pool.fetch(
        f"""
        SELECT token_address, liquidity_index_ray, variable_borrow_index_ray,
               liquidity_rate_ray, variable_borrow_rate_ray
        FROM loan."{table}"
        WHERE block_number = $1
          AND liquidity_index_ray IS NOT NULL
        """,
        block_number,
    )
    return {
        r["token_address"]: ReserveIndex(
            token_address=r["token_address"],
            liquidity_index=int(r["liquidity_index_ray"]),
            variable_borrow_index=int(r["variable_borrow_index_ray"]),
            liquidity_rate=int(r["liquidity_rate_ray"]),
            variable_borrow_rate=int(r["variable_borrow_rate_ray"]),
        )
        for r in rows
    }


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
    "scaled_supply_raw",
    "scaled_variable_debt_raw",
    "principal_stable_debt_raw",
    "stable_borrow_rate_raw",
)


async def upsert_daily_positions(
    pool: asyncpg.Pool,
    batch: list[tuple[UserPosition, int]],  # (position, eth_price_raw / 8-dec)
    snapshot_date: date,
    block_number: int,
    block_timestamp: datetime,
    protocol: str,
    reserve_indices: "dict[str, ReserveIndex] | None" = None,
) -> None:
    """批量写入一天的仓位数据（汇总 + reserve 明细）。

    汇总行和明细行均采用 DELETE + COPY 策略（COPY 协议比 executemany ON CONFLICT 快 10–50×）：
      1. DELETE 本批用户当天旧汇总行
      2. COPY 新汇总行
      3. DELETE 本批用户当天旧 reserve 行
      4. COPY 新 reserve 行
    整批在同一事务内完成，保证汇总与明细一致。

    reserve_indices: 当日 reserve 利率指数（来自 market_snapshots），
    用于计算 scaled_supply_raw = supply_raw * 1e27 // liquidity_index。
    传 None 时 scaled_supply_raw 写入 0（向后兼容旧调用路径）。
    """
    tables = get_daily_tables(protocol)
    now = datetime.now(tz=timezone.utc)

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

            # scaled_supply_raw = supply_raw * 1e27 // liquidity_index
            idx = (reserve_indices or {}).get(r.token_address.lower())
            if idx and idx.liquidity_index > 0:
                scaled_supply = (
                    Decimal(r.supply_raw)
                    * Decimal(10**27)
                    // Decimal(idx.liquidity_index)
                )
            else:
                scaled_supply = Decimal(0)

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
                    scaled_supply,
                    Decimal(r.scaled_variable_debt_raw),
                    Decimal(r.principal_stable_debt_raw),
                    Decimal(r.stable_borrow_rate),
                )
            )

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. DELETE + COPY 汇总行（COPY 协议比 executemany ON CONFLICT 快 10–50×）
            if all_user_addrs:
                await conn.execute(
                    f'DELETE FROM loan."{tables.positions}"'
                    f" WHERE snapshot_date = $1 AND user_address = ANY($2)",
                    snapshot_date,
                    all_user_addrs,
                )
            if summary_rows:
                await conn.copy_records_to_table(
                    tables.positions,
                    schema_name="loan",
                    records=summary_rows,
                    columns=list(_DAILY_POS_COLUMNS),
                )

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

    # 并发预取所有天的区块时间戳和价格
    # 用独立信号量限制预取阶段的并发度（fetch_block_prices 内部已并发 N 个 getAssetPrice）
    _PREFETCH_CONCURRENCY = max(1, cfg.crawler.concurrency // 4)
    _prefetch_sem = asyncio.Semaphore(_PREFETCH_CONCURRENCY)

    async def _fetch_day_meta(block_num: int) -> tuple[datetime, dict[str, int]]:
        async with _prefetch_sem:
            raw_block = await w3.eth.get_block(block_num)
            ts = datetime.fromtimestamp(
                raw_block["timestamp"],  # type: ignore[typeddict-item]
                tz=timezone.utc,
            )
            prices = await fetch_block_prices(w3, contracts, token_addresses, block_num)
        return ts, prices

    logger.info(
        "并发预取 %d 天的区块时间戳和价格（预取并发度 %d）...",
        len(days),
        _PREFETCH_CONCURRENCY,
    )
    day_metas: list[tuple[datetime, dict[str, int]]] = list(
        await asyncio.gather(*[_fetch_day_meta(bn) for bn in block_numbers])
    )

    # Step 4：--skip-existing 批量预加载所有待处理天的已完成用户（一次 IN 查询）
    collected_by_day: defaultdict[date, set[str]] = defaultdict(set)
    if skip_existing:
        tables = get_daily_tables(protocol)
        rows = await pool.fetch(
            f'SELECT snapshot_date, user_address FROM loan."{tables.positions}"'
            f" WHERE snapshot_date = ANY($1::date[])",
            days,
        )
        for r in rows:
            collected_by_day[r["snapshot_date"]].add(r["user_address"])
        logger.info(
            "--skip-existing：预加载 %d 天的已采集用户（共 %d 条记录）",
            len(collected_by_day),
            len(rows),
        )

    for day, block_number, (block_ts, block_prices) in zip(
        days, block_numbers, day_metas
    ):
        if not block_prices:
            logger.warning(
                "日期 %s block #%d 价格预取失败，跳过本日", day, block_number
            )
            continue

        logger.info(
            "日期 %s → block #%d（区块时间 %s UTC）",
            day,
            block_number,
            block_ts.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        # ── Step A：读取当日 reserve indices（优先 DB，降级 RPC）────────────────
        reserve_indices = await load_reserve_indices_from_db(
            pool, block_number, protocol
        )
        if reserve_indices:
            logger.debug(
                "日期 %s Step A：从 market_snapshots 加载 %d 个 reserve index（block=%d）",
                day,
                len(reserve_indices),
                block_number,
            )
        else:
            logger.info(
                "日期 %s Step A：market_snapshots 无 block=%d 数据，降级为 RPC 获取 index",
                day,
                block_number,
            )
            reserve_indices = await fetch_reserve_indices(
                w3, contracts, token_addresses, block_number
            )
            logger.info(
                "日期 %s Step A RPC 降级：获取 %d 个 reserve index",
                day,
                len(reserve_indices),
            )

        # --skip-existing：使用预加载字典，无需再查数据库
        day_users = users
        if skip_existing:
            collected = collected_by_day.get(day, set())
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

        # ── Phase 1：Multicall3 批量筛选活跃用户 ──────────────────────────────
        _PHASE1_BATCH_SIZE = 50
        phase1_sem = asyncio.Semaphore(max(1, cfg.crawler.concurrency // 5))

        batches = [
            day_users[i : i + _PHASE1_BATCH_SIZE]
            for i in range(0, len(day_users), _PHASE1_BATCH_SIZE)
        ]
        logger.info(
            "日期 %s Phase1：%d 用户分 %d 批（每批 %d）筛选活跃仓位...",
            day,
            len(day_users),
            len(batches),
            _PHASE1_BATCH_SIZE,
        )

        batch_results: list[list | BaseException] = list(
            await asyncio.gather(
                *[
                    fetch_batch_account_summaries(
                        w3, contracts, batch, block_number, phase1_sem
                    )
                    for batch in batches
                ],
                return_exceptions=True,
            )
        )

        active_users: list[tuple[str, AccountSummary]] = []
        phase1_skip = phase1_fail = 0
        for batch, result in zip(batches, batch_results):
            if isinstance(result, BaseException):
                logger.warning("Phase1 batch 失败：%s", result)
                phase1_fail += len(batch)
                continue
            for addr, summary in zip(batch, result):
                if summary is None:
                    phase1_fail += 1
                elif (
                    summary.total_collateral_base == 0 and summary.total_debt_base == 0
                ):
                    phase1_skip += 1
                else:
                    active_users.append((addr, summary))

        logger.info(
            "日期 %s Phase1 完成：活跃 %d，无仓位 %d，失败 %d",
            day,
            len(active_users),
            phase1_skip,
            phase1_fail,
        )

        # ── Phase 2：仅对活跃用户查 reserve 余额并写库 ────────────────────────
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
                    account_summary=summary,
                )
            )
            for addr, summary in active_users
        ]

        pending: list[tuple[UserPosition, int]] = []
        ok = fail = 0
        db_tasks: list[asyncio.Task] = []
        _MAX_DB_TASKS = 2

        with tqdm(total=len(active_users), desc=f"{day}[采]", unit="user") as pbar:
            for coro in asyncio.as_completed(all_tasks):
                result = await coro
                pbar.update(1)

                if result is EMPTY_POSITION:
                    # Phase1 已过滤，防御性处理
                    continue
                if result is None:
                    fail += 1
                    continue

                pos, eth_price_raw = cast(tuple, result)
                ok += 1
                pending.append((pos, eth_price_raw))

                if len(pending) >= cfg.crawler.batch_size:
                    if not dry_run:
                        # 若已有 _MAX_DB_TASKS 个写入任务在飞行，等待最早的一个完成
                        db_tasks = [t for t in db_tasks if not t.done()]
                        if len(db_tasks) >= _MAX_DB_TASKS:
                            await db_tasks[0]
                            db_tasks.pop(0)
                        db_tasks.append(
                            asyncio.ensure_future(
                                upsert_daily_positions(
                                    pool,
                                    list(pending),
                                    day,
                                    block_number,
                                    block_ts,
                                    protocol,
                                    reserve_indices,
                                )
                            )
                        )
                    pending.clear()

            # 等待所有飞行中的写入任务完成，再提交最后一批
            if db_tasks:
                await asyncio.gather(*db_tasks)
            if pending and not dry_run:
                await upsert_daily_positions(
                    pool,
                    pending,
                    day,
                    block_number,
                    block_ts,
                    protocol,
                    reserve_indices,
                )

        logger.info(
            "日期 %s 采集完成：有仓位 %d，无仓位(已平仓) %d，失败 %d（Phase1: %d，Phase2: %d）",
            day,
            ok,
            phase1_skip,
            phase1_fail + fail,
            phase1_fail,
            fail,
        )

    # Step 5：回写成功采集天的区块时间戳，缩小后续 _block_at_timestamp 二分搜索区间
    if not dry_run:
        valid_pairs = [
            (bn, ts)
            for bn, (ts, prices) in zip(block_numbers, day_metas)
            if prices  # 仅写入价格预取成功（实际处理）的天
        ]
        if valid_pairs:
            await upsert_block_timestamps(pool, valid_pairs)
            logger.debug("回写区块时间戳缓存：%d 条", len(valid_pairs))

    logger.info("日级采集全部完成：%s → %s", start_date, end_date)
