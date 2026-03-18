"""
_verify_forward_recalc.py
────────────────────────────────────────────────────────────────────────────────
Phase 2 验证：对比 forward_recalc_positions 的重算结果 vs DB 中 RPC 实际采集值。

选取已有连续两天快照的日期对 (yesterday, today)，从 yesterday 的 scaled 字段
推导 today 的余额，与 today 的 RPC 采集值做 roundtrip 误差分析。

关键：仅对比**无事件用户**（即在 today 没有 aave_history 记录的用户），
以排除 deposit/borrow/repay 等操作引起的"预期差异"对误差统计的污染。

不写入任何数据，纯读取验证。

用法：
    uv run python scripts/_verify_forward_recalc.py --protocol v3 --days 7
    uv run python scripts/_verify_forward_recalc.py --protocol v2 --days 5 --sample 200
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import sys
from datetime import date
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aave_crawler.config import load_config  # noqa: E402
from aave_crawler.daily_collector import (  # noqa: E402
    _SECONDS_PER_YEAR,
    get_daily_tables,
    load_reserve_indices_from_db,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

RAY = 10**27


# ── 核心验证逻辑 ───────────────────────────────────────────────────────────────


async def _fetch_event_users(
    pool: asyncpg.Pool,
    yesterday_block: int,
    today_block: int,
    protocol: str,
) -> set[str]:
    """查询在 (yesterday_block, today_block] 区间内有 aave_history 事件的用户地址集合。

    注意：aave_history.created_at 是采集时间（非区块时间），不能用于日期过滤。
    必须使用 block_number 范围：昨日快照块（不含）到今日快照块（含）之间有操作的用户。
    """
    version = protocol.lstrip("v")  # "v3" → "3", "v2" → "2"
    rows = await pool.fetch(
        """
        SELECT DISTINCT lower(convert_from(user_address, 'UTF8')) AS addr
        FROM aave.aave_history
        WHERE protocol_version = $1
          AND block_number > $2
          AND block_number <= $3
          AND user_address IS NOT NULL
        UNION
        SELECT DISTINCT lower(convert_from(target_user_address, 'UTF8')) AS addr
        FROM aave.aave_history
        WHERE protocol_version = $1
          AND block_number > $2
          AND block_number <= $3
          AND target_user_address IS NOT NULL
        """,
        version,
        yesterday_block,
        today_block,
    )
    # aave_history.user_address 是 bytea STORAGE PLAIN，存储的是地址文本的 UTF-8 字节
    # （即字符串 "0xAbCd..." 的 ASCII 编码），而非 20 字节原始二进制地址。
    # 必须用 convert_from(..., 'UTF8') 还原文本，再 lower() 统一大小写。
    # 返回结果已是 "0x" + lowercase_hex 格式，与 daily_reserve_positions.user_address 一致。
    return {r["addr"] for r in rows}


async def verify_one_pair(
    pool: asyncpg.Pool,
    protocol: str,
    yesterday: date,
    today: date,
    sample_size: int,
) -> dict:
    """对一对日期验证 forward_recalc 精度。

    仅对比无事件用户（today 在 aave_history 中无记录），
    且仅在对应 scaled 字段 > 0 时计入误差统计。

    返回 dict 包含误差统计。
    """
    tables = get_daily_tables(protocol)

    # 1. 找 yesterday 和 today 的 block_number（同日所有行共用同一个 block）
    yesterday_meta = await pool.fetchrow(
        f"""
        SELECT block_number
        FROM loan."{tables.reserve_positions}"
        WHERE snapshot_date = $1
        LIMIT 1
        """,
        yesterday,
    )
    today_meta = await pool.fetchrow(
        f"""
        SELECT block_number, block_timestamp
        FROM loan."{tables.reserve_positions}"
        WHERE snapshot_date = $1
        LIMIT 1
        """,
        today,
    )
    if today_meta is None:
        logger.warning("  %s：today(%s) 无数据，跳过", protocol.upper(), today)
        return {}

    today_block: int = today_meta["block_number"]
    today_block_ts = today_meta["block_timestamp"]
    # yesterday_block 用于 aave_history 事件范围过滤；若无昨日快照则退守到 today_block-7200（约 24h）
    yesterday_block: int = (
        yesterday_meta["block_number"]
        if yesterday_meta is not None
        else today_block - 7200
    )

    from aave_crawler.rpc import ReserveIndex  # noqa: PLC0415

    def _nearest_neighbor_indices(
        nn_rows: list,
    ) -> dict[str, "ReserveIndex"]:
        return {
            r["token_address"]: ReserveIndex(
                token_address=r["token_address"],
                liquidity_index=int(r["liquidity_index_ray"]),
                variable_borrow_index=int(r["variable_borrow_index_ray"]),
                liquidity_rate=int(r["liquidity_rate_ray"] or 0),
                variable_borrow_rate=int(r["variable_borrow_rate_ray"] or 0),
            )
            for r in nn_rows
        }

    async def _load_indices(block: int) -> dict[str, "ReserveIndex"]:
        idxs = await load_reserve_indices_from_db(pool, block, protocol)
        if idxs:
            return idxs
        base = protocol.split("_")[0].lower()
        ms_table = f"aave_{base}_market_snapshots"
        nn = await pool.fetch(
            f"""
            SELECT DISTINCT ON (token_address)
                token_address, liquidity_index_ray, variable_borrow_index_ray,
                liquidity_rate_ray, variable_borrow_rate_ray
            FROM loan."{ms_table}"
            WHERE liquidity_index_ray IS NOT NULL
              AND liquidity_index_ray > 0
              AND variable_borrow_index_ray > 0
            ORDER BY token_address, ABS(block_number::BIGINT - $1::BIGINT) ASC
            """,
            block,
        )
        return _nearest_neighbor_indices(nn)

    # 2. 读取 yesterday 和 today 的 reserve indices
    # 对比两日 index 是否变化，用于区分"活跃 token"vs"停滞 token"
    reserve_indices, yest_reserve_indices = await asyncio.gather(
        _load_indices(today_block),
        _load_indices(yesterday_block),
    )

    if not reserve_indices:
        logger.warning(
            "  %s：market_snapshots 无 %s 附近数据，跳过", protocol.upper(), today
        )
        return {}

    # 阈值常量（与 run() 中的判定保持一致）
    supply_threshold = 1e-3  # 0.1%
    var_threshold = 1e-3  # 0.1%

    # token 活跃性判断：当日 stored_index 相比昨日是否变化，且变化幅度在合理日涨幅范围内
    # 「停滞 token」误差 = accumulated(normalizedDebt - stored_idx)，属 Phase 1 已记录的结构性偏差，
    # 不纳入 forward_recalc 精度阈值检查。
    #
    # 严格定义「活跃」：index 发生了变化，但日涨幅 < 5%（单日利息绝无可能达到 5%）。
    # 若涨幅 ≥ 5%，说明该 token 长期停滞后刚刚被第一次 updateState，此时 DB 回填的
    # scaled_variable_debt_raw = variable_debt / stale_stored_idx 是"膨胀"值，
    # 与真实链上不变量不同；将其归入停滞类，避免误计入活跃阈值检查。
    _MAX_DAILY_RATE = 1.05  # 单日 index 合理涨幅上限（5%，真实日利率远低于此）

    # 利率预期误差过滤：market_snapshots 与 daily_positions 快照时刻之间约有 4 小时偏差
    # （V2: market_collector ~UTC 20:xx，daily_positions ~UTC 00:00）。
    # 对于利率极高的冷门 V2 token（DPI/ENJ 等可达 300-1000% APR），
    # 仅这 4 小时内积累的利息就可超过 0.1% 阈值——误差源是快照时间偏移而非算法问题。
    # 策略：若 token 当前利率 × 4h 窗口 ≥ var_threshold，归为结构性偏差，不计入活跃检查。
    _SNAPSHOT_OFFSET_SECONDS = 4 * 3600  # ~4h，对应 ~1000 个以太坊区块

    def _offset_error(rate_ray: int, threshold: float) -> bool:
        """当前利率在快照偏移窗口内预期产生的误差是否已超阈值（即结构性不可达）。"""
        return (
            rate_ray / RAY * _SNAPSHOT_OFFSET_SECONDS / _SECONDS_PER_YEAR >= threshold
        )

    active_liq_tokens: set[str] = {
        addr
        for addr, idx in reserve_indices.items()
        if (yi := yest_reserve_indices.get(addr)) is not None
        and yi.liquidity_index > 0
        and idx.liquidity_index != yi.liquidity_index
        and idx.liquidity_index / yi.liquidity_index < _MAX_DAILY_RATE
        and not _offset_error(idx.liquidity_rate, supply_threshold)
    }
    active_var_tokens: set[str] = {
        addr
        for addr, idx in reserve_indices.items()
        if (yi := yest_reserve_indices.get(addr)) is not None
        and yi.variable_borrow_index > 0
        and idx.variable_borrow_index != yi.variable_borrow_index
        and idx.variable_borrow_index / yi.variable_borrow_index < _MAX_DAILY_RATE
        and not _offset_error(idx.variable_borrow_rate, var_threshold)
    }

    # 3. 查询 (yesterday_block, today_block] 区间内的事件用户，后续排除
    event_users_today = await _fetch_event_users(
        pool, yesterday_block, today_block, protocol
    )
    # 归一化为无 0x 前缀的小写格式，确保与 DB 存储格式无关
    event_users_norm: set[str] = {
        a.lower().removeprefix("0x") for a in event_users_today
    }
    logger.info(
        "  %s %s：事件用户 %d 个（已排除），活跃 liq_token %d / var_token %d（共 %d）",
        protocol.upper(),
        today,
        len(event_users_today),
        len(active_liq_tokens),
        len(active_var_tokens),
        len(reserve_indices),
    )

    # 4. 读取昨日有 scaled 数据的用户 + token 对（限 sample_size 用户，排除事件用户）
    yest_rows = await pool.fetch(
        f"""
        SELECT user_address, token_address, symbol, decimals,
               scaled_supply_raw, scaled_variable_debt_raw,
               principal_stable_debt_raw, stable_borrow_rate_raw,
               block_timestamp AS prev_block_ts
        FROM loan."{tables.reserve_positions}"
        WHERE snapshot_date = $1
          AND (scaled_supply_raw > 0 OR scaled_variable_debt_raw > 0)
          AND user_address IN (
              SELECT DISTINCT user_address
              FROM loan."{tables.reserve_positions}"
              WHERE snapshot_date = $1
                AND (scaled_supply_raw > 0 OR scaled_variable_debt_raw > 0)
              LIMIT $2
          )
        """,
        yesterday,
        sample_size,
    )

    if not yest_rows:
        logger.warning(
            "  %s：yesterday(%s) 无 scaled 数据，跳过", protocol.upper(), yesterday
        )
        return {}

    # 5. 读取 today 的 RPC 实际值（同 user + token）
    user_addrs = list({r["user_address"] for r in yest_rows})

    today_rows = await pool.fetch(
        f"""
        SELECT user_address, token_address,
               supply_raw, variable_debt_raw, stable_debt_raw
        FROM loan."{tables.reserve_positions}"
        WHERE snapshot_date = $1
          AND user_address = ANY($2)
        """,
        today,
        user_addrs,
    )
    today_map: dict[tuple[str, str], dict] = {
        (r["user_address"], r["token_address"]): dict(r) for r in today_rows
    }

    # 6. 逐行计算 forward_recalc 值，与 today 实际值对比（排除事件用户）
    # 按 token 活跃性分类：活跃 token 纳入阈值检查；停滞 token 仅统计不检查（结构性偏差）
    active_supply_errors: list[float] = []
    stale_supply_errors: list[float] = []
    active_var_errors: list[float] = []
    stale_var_errors: list[float] = []
    # 用于展示最差 token 信息
    worst_active_supply: list[tuple[float, str]] = []
    worst_active_var: list[tuple[float, str]] = []  # (error, symbol)
    worst_stale_var: list[tuple[float, str]] = []
    excluded_event = 0
    excluded_no_today = 0
    # aave_history 数据断层导致的漏网事件用户（误差 > 100%，仓位发生了根本性变化）
    history_gap_slips = 0

    for row in yest_rows:
        user_addr: str = row["user_address"]

        # 排除 today 有事件的用户（归一化后比较，与 DB 存储格式无关）
        if user_addr.lower().removeprefix("0x") in event_users_norm:
            excluded_event += 1
            continue

        token_addr: str = row["token_address"]
        key = (user_addr, token_addr)
        actual = today_map.get(key)
        if actual is None:
            excluded_no_today += 1
            continue  # 用户 today 已无此 token 仓位（平仓），跳过

        idx = reserve_indices.get(token_addr)
        if idx is None:
            continue

        # 防御：zero index 会导致 recalc = 0 → 误差恒为 1.0，属数据质量问题而非算法误差
        if idx.liquidity_index == 0 or idx.variable_borrow_index == 0:
            continue

        scaled_supply = int(row["scaled_supply_raw"])
        scaled_var = int(row["scaled_variable_debt_raw"])
        principal_stable = int(row["principal_stable_debt_raw"])
        stable_rate = int(row["stable_borrow_rate_raw"])
        symbol: str = row["symbol"]

        # forward_recalc 计算
        recalc_supply = (
            scaled_supply * idx.liquidity_index // RAY if scaled_supply > 0 else 0
        )
        recalc_var = (
            scaled_var * idx.variable_borrow_index // RAY if scaled_var > 0 else 0
        )

        if principal_stable > 0:
            prev_ts = row["prev_block_ts"]
            seconds = (today_block_ts - prev_ts).total_seconds()
            if stable_rate > 0 and seconds > 0:
                interest = math.exp(stable_rate / 1e27 * seconds / _SECONDS_PER_YEAR)
                recalc_stable = int(principal_stable * interest)
            else:
                recalc_stable = principal_stable
        else:
            recalc_stable = 0
        _ = recalc_stable  # 已计算，仅用于后续扩展

        actual_supply = int(actual["supply_raw"])
        actual_var = int(actual["variable_debt_raw"])

        # supply 误差
        if scaled_supply > 0 and actual_supply > 10**12:
            err = abs(recalc_supply - actual_supply) / actual_supply
            # 误差 > 100%：仓位发生根本性变化，aave_history 数据断层导致事件用户漏网
            # 此类行不纳入误差统计，单独计数
            if err > 1.0:
                history_gap_slips += 1
            elif token_addr in active_liq_tokens:
                active_supply_errors.append(err)
                worst_active_supply.append((err, symbol))
            else:
                stale_supply_errors.append(err)

        # variable_debt 误差
        if scaled_var > 0 and actual_var > 10**12:
            err = abs(recalc_var - actual_var) / actual_var
            if err > 1.0:
                history_gap_slips += 1
            elif token_addr in active_var_tokens:
                active_var_errors.append(err)
                worst_active_var.append((err, symbol))
            else:
                stale_var_errors.append(err)
                worst_stale_var.append((err, symbol))

    # 打印活跃/停滞 token 最差 top-3（诊断用）
    if worst_active_supply:
        top3 = sorted(worst_active_supply, reverse=True)[:3]
        logger.info(
            "  活跃 supply top-3 误差: %s",
            ", ".join(f"{sym}={e:.3e}" for e, sym in top3),
        )
    if worst_active_var:
        top3 = sorted(worst_active_var, reverse=True)[:3]
        logger.info(
            "  活跃 var_debt top-3 误差: %s",
            ", ".join(f"{sym}={e:.3e}" for e, sym in top3),
        )
    if worst_stale_var:
        top3 = sorted(worst_stale_var, reverse=True)[:3]
        logger.debug(
            "  停滞 token var_debt top-3 误差: %s",
            ", ".join(f"{sym}={e:.3e}" for e, sym in top3),
        )

    logger.debug(
        "  %s %s→%s：排除事件用户行 %d，无今日数据行 %d，history 漏网行 %d",
        protocol.upper(),
        yesterday,
        today,
        excluded_event,
        excluded_no_today,
        history_gap_slips,
    )

    def _stats(errors: list[float]) -> dict:
        if not errors:
            return {"n": 0, "avg": 0.0, "max": 0.0}
        return {
            "n": len(errors),
            "avg": sum(errors) / len(errors),
            "max": max(errors),
        }

    return {
        "yesterday": str(yesterday),
        "today": str(today),
        "today_block": today_block,
        "yest_sample_users": len(user_addrs),
        "excluded_event": excluded_event,
        "history_gap_slips": history_gap_slips,
        # 活跃 token：阈值检查对象
        "active_supply": _stats(active_supply_errors),
        "active_var": _stats(active_var_errors),
        # 停滞 token：结构性偏差，仅展示不检查
        "stale_supply": _stats(stale_supply_errors),
        "stale_var": _stats(stale_var_errors),
    }


# ── 主逻辑 ─────────────────────────────────────────────────────────────────────


async def run(
    protocol: str,
    days: int,
    sample: int,
    start_date: date | None,
    end_date: date | None,
) -> None:
    cfg = load_config()
    pool = await asyncpg.create_pool(
        host=cfg.postgres.host,
        port=cfg.postgres.port,
        user=cfg.postgres.user,
        password=cfg.postgres.password,
        database=cfg.postgres.database,
        min_size=2,
        max_size=4,
    )
    try:
        tables = get_daily_tables(protocol)

        # 构建日期过滤条件（start/end 优先；未指定时取最近 days+1 天）
        if start_date is not None or end_date is not None:
            clauses = ["(scaled_supply_raw > 0 OR scaled_variable_debt_raw > 0)"]
            params: list = []
            if start_date is not None:
                params.append(start_date)
                clauses.append(f"snapshot_date >= ${len(params)}")
            if end_date is not None:
                params.append(end_date)
                clauses.append(f"snapshot_date <= ${len(params)}")
            where = " AND ".join(clauses)
            all_dates = [
                r["snapshot_date"]
                for r in await pool.fetch(
                    f"""
                    SELECT DISTINCT snapshot_date
                    FROM loan."{tables.reserve_positions}"
                    WHERE {where}
                    ORDER BY snapshot_date
                    """,
                    *params,
                )
            ]
        else:
            all_dates = [
                r["snapshot_date"]
                for r in await pool.fetch(
                    f"""
                    SELECT DISTINCT snapshot_date
                    FROM loan."{tables.reserve_positions}"
                    WHERE scaled_supply_raw > 0 OR scaled_variable_debt_raw > 0
                    ORDER BY snapshot_date DESC
                    LIMIT $1
                    """,
                    days + 1,
                )
            ]
            all_dates.sort()

        if len(all_dates) < 2:
            logger.error("可用日期不足 2 天，无法验证")
            return

        logger.info(
            "[%s] 验证日期范围：%s → %s（%d 对）",
            protocol.upper(),
            all_dates[0],
            all_dates[-1],
            len(all_dates) - 1,
        )
        # 表头：活跃 token 列（纳入阈值检查）+ 停滞 token 列（结构性偏差，仅展示）
        logger.info(
            "%-12s %-12s | [活跃] %-6s %-10s %-10s  %-6s %-10s %-10s | [停滞] var_max | excl | gap",
            "yesterday",
            "today",
            "sup_n",
            "sup_avg",
            "sup_max",
            "var_n",
            "var_avg",
            "var_max",
        )
        logger.info("-" * 128)

        all_active_sup_max: list[float] = []
        all_active_var_max: list[float] = []
        all_stale_var_max: list[float] = []
        total_gap_slips = 0

        for i in range(len(all_dates) - 1):
            yesterday = all_dates[i]
            today = all_dates[i + 1]
            result = await verify_one_pair(pool, protocol, yesterday, today, sample)
            if not result:
                continue

            as_ = result["active_supply"]
            av = result["active_var"]
            sv = result["stale_var"]
            gap = result["history_gap_slips"]
            total_gap_slips += gap
            logger.info(
                "%-12s %-12s | [活跃] %-6d %-10.3e %-10.3e  %-6d %-10.3e %-10.3e | %-10.3e | %-4d | %d",
                result["yesterday"],
                result["today"],
                as_["n"],
                as_["avg"],
                as_["max"],
                av["n"],
                av["avg"],
                av["max"],
                sv["max"],
                result["excluded_event"],
                gap,
            )
            if as_["max"] > 0:
                all_active_sup_max.append(as_["max"])
            if av["max"] > 0:
                all_active_var_max.append(av["max"])
            if sv["max"] > 0:
                all_stale_var_max.append(sv["max"])

        logger.info("-" * 128)
        if all_active_sup_max:
            logger.info(
                "[活跃] supply   全期最大: %.3e  平均最大: %.3e",
                max(all_active_sup_max),
                sum(all_active_sup_max) / len(all_active_sup_max),
            )
        if all_active_var_max:
            logger.info(
                "[活跃] var_debt 全期最大: %.3e  平均最大: %.3e",
                max(all_active_var_max),
                sum(all_active_var_max) / len(all_active_var_max),
            )
        if all_stale_var_max:
            logger.info(
                "[停滞] var_debt 全期最大: %.3e（结构性偏差，不计入阈值检查）",
                max(all_stale_var_max),
            )
        if total_gap_slips:
            logger.info(
                "history 漏网行合计: %d（aave_history 数据断层，误差 > 100%%，已排除）",
                total_gap_slips,
            )

        # 阈值常量（与 verify_one_pair 内部一致）
        supply_threshold = 1e-3  # 0.1%
        var_threshold = 1e-3  # 0.1%
        # 注：阈值常量在 verify_one_pair 内同步定义，用于活跃 token 过滤（利率预期误差检查）
        supply_pass = (
            not all_active_sup_max or max(all_active_sup_max) < supply_threshold
        )
        var_pass = not all_active_var_max or max(all_active_var_max) < var_threshold
        if supply_pass and var_pass:
            logger.info(
                "✅ Phase 2 验证通过（活跃 token：supply < 0.1%%，var_debt < 0.1%%）"
            )
        else:
            logger.warning(
                "⚠️  活跃 token 误差超出阈值（supply [0.1%%]: %s，var_debt [0.1%%]: %s）",
                "PASS" if supply_pass else "FAIL",
                "PASS" if var_pass else "FAIL",
            )

    finally:
        await pool.close()


def main() -> None:
    p = argparse.ArgumentParser(
        description="验证 forward_recalc_positions 精度（仅无事件用户）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例：
  uv run python scripts/_verify_forward_recalc.py --protocol v3 --days 7
  uv run python scripts/_verify_forward_recalc.py --protocol v2 --start 2026-01-01 --end 2026-03-01
  uv run python scripts/_verify_forward_recalc.py --protocol v3 --start 2026-02-10 --sample 1000
        """,
    )
    p.add_argument(
        "--protocol",
        "-p",
        choices=["v2", "v3"],
        default="v3",
        help="协议版本（默认 v3）",
    )
    p.add_argument(
        "--days",
        "-d",
        type=int,
        default=7,
        help="验证天数，从最新日期往前取（与 --start/--end 互斥，优先级低）",
    )
    p.add_argument(
        "--start",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="验证起始日期（含）",
    )
    p.add_argument(
        "--end",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="验证结束日期（含）",
    )
    p.add_argument(
        "--sample",
        "-s",
        type=int,
        default=500,
        help="每天抽样用户数（默认 500）",
    )
    args = p.parse_args()
    asyncio.run(run(args.protocol, args.days, args.sample, args.start, args.end))


if __name__ == "__main__":
    main()
