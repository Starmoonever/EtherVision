"""
backfill_daily_scaled_fields.py
────────────────────────────────────────────────────────────────────────────────
为 loan.aave_{v2|v3}_eth_daily_reserve_positions 中旧行（scaled 字段为 0 但
supply/variable_debt 非零的行）批量回填 4 个 scaled 字段：

    scaled_supply_raw         = TRUNC(supply_raw * 1e27 / liquidity_index)
    scaled_variable_debt_raw  = TRUNC(variable_debt_raw * 1e27 / variable_borrow_index)
    principal_stable_debt_raw = 0  （V3 已废弃；V2 当前无持仓）
    stable_borrow_rate_raw    = 0  （同上）

利率指数来自 loan.aave_{v2|v3}_market_snapshots：
  - V3：按 block_number 精确匹配（两表使用同一区块，一对一）
  - V2：nearest-neighbor 匹配（两者区块偏差 ~1000 块，引入约 1e-6 额外误差，可忽略）

注意：历史上持有稳定债务的仓位（V2 2021~2023 年部分用户）无法从现有 DB 字段推导
stable debt 的 scaled 值，需 RPC 重查。本脚本统一写 0；Phase 5 对账时若发现
stable_debt_raw > 0 且 principal_stable_debt_raw = 0 的行，可单独走 RPC 补全。

幂等安全：仅处理 scaled_supply_raw = 0 AND scaled_variable_debt_raw = 0
且 (supply_raw > 0 OR variable_debt_raw > 0) 的行，可重复运行。

用法：
    uv run python scripts/backfill_daily_scaled_fields.py
    uv run python scripts/backfill_daily_scaled_fields.py --protocol v2
    uv run python scripts/backfill_daily_scaled_fields.py --protocol v3 --dry-run
    uv run python scripts/backfill_daily_scaled_fields.py --start 2023-01-27 --end 2024-12-31
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

import asyncpg
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aave_crawler.config import load_config  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── SQL ────────────────────────────────────────────────────────────────────────

# 待处理日期列表（供用户预览和进度控制）
_SQL_PENDING_DATES = """
SELECT DISTINCT snapshot_date
FROM loan."{res_table}"
WHERE scaled_supply_raw = 0
  AND scaled_variable_debt_raw = 0
  AND (supply_raw > 0 OR variable_debt_raw > 0)
  {date_filter}
ORDER BY snapshot_date
"""

# 待处理行数（总计）
_SQL_PENDING_COUNT = """
SELECT COUNT(*)
FROM loan."{res_table}"
WHERE scaled_supply_raw = 0
  AND scaled_variable_debt_raw = 0
  AND (supply_raw > 0 OR variable_debt_raw > 0)
  {date_filter}
"""

# V3：按 block_number 精确匹配 market_snapshots（同一 UTC 00:00 区块）
_SQL_UPDATE_V3 = """
UPDATE loan."aave_v3_eth_daily_reserve_positions" AS p
SET
    scaled_supply_raw = CASE
        WHEN ms.liquidity_index_ray > 0
        THEN TRUNC(p.supply_raw::NUMERIC * 1000000000000000000000000000
                   / ms.liquidity_index_ray)
        ELSE 0
    END,
    scaled_variable_debt_raw = CASE
        WHEN ms.variable_borrow_index_ray > 0
        THEN TRUNC(p.variable_debt_raw::NUMERIC * 1000000000000000000000000000
                   / ms.variable_borrow_index_ray)
        ELSE 0
    END
FROM loan."aave_v3_market_snapshots" AS ms
WHERE p.snapshot_date = $1
  AND ms.block_number = p.block_number
  AND ms.token_address = p.token_address
  AND ms.liquidity_index_ray IS NOT NULL
  AND p.scaled_supply_raw = 0
  AND p.scaled_variable_debt_raw = 0
  AND (p.supply_raw > 0 OR p.variable_debt_raw > 0)
"""

# V2：nearest-neighbor 匹配（CROSS JOIN LATERAL，按 ABS(block_diff) 升序取最近块）
# 因同一 snapshot_date 所有行共用一个 block_number，CTE 中 unique_pairs 行数 = token 数。
_SQL_UPDATE_V2 = """
WITH unique_pairs AS (
    SELECT DISTINCT block_number, token_address
    FROM loan."aave_v2_eth_daily_reserve_positions"
    WHERE snapshot_date = $1
      AND scaled_supply_raw = 0
      AND scaled_variable_debt_raw = 0
      AND (supply_raw > 0 OR variable_debt_raw > 0)
),
nearest_idx AS (
    SELECT
        up.block_number AS pos_block,
        up.token_address,
        ms.liquidity_index_ray,
        ms.variable_borrow_index_ray
    FROM unique_pairs up
    CROSS JOIN LATERAL (
        SELECT liquidity_index_ray, variable_borrow_index_ray
        FROM loan."aave_v2_market_snapshots"
        WHERE token_address = up.token_address
          AND liquidity_index_ray IS NOT NULL
        ORDER BY ABS(block_number::BIGINT - up.block_number::BIGINT) ASC
        LIMIT 1
    ) ms
)
UPDATE loan."aave_v2_eth_daily_reserve_positions" AS p
SET
    scaled_supply_raw = CASE
        WHEN ni.liquidity_index_ray > 0
        THEN TRUNC(p.supply_raw::NUMERIC * 1000000000000000000000000000
                   / ni.liquidity_index_ray)
        ELSE 0
    END,
    scaled_variable_debt_raw = CASE
        WHEN ni.variable_borrow_index_ray > 0
        THEN TRUNC(p.variable_debt_raw::NUMERIC * 1000000000000000000000000000
                   / ni.variable_borrow_index_ray)
        ELSE 0
    END
FROM nearest_idx ni
WHERE p.snapshot_date = $1
  AND p.block_number = ni.pos_block
  AND p.token_address = ni.token_address
  AND p.scaled_supply_raw = 0
  AND p.scaled_variable_debt_raw = 0
  AND (p.supply_raw > 0 OR p.variable_debt_raw > 0)
"""

_UPDATE_SQL: dict[str, str] = {"v3": _SQL_UPDATE_V3, "v2": _SQL_UPDATE_V2}
_RES_TABLES: dict[str, str] = {
    "v3": "aave_v3_eth_daily_reserve_positions",
    "v2": "aave_v2_eth_daily_reserve_positions",
}


# ── 主逻辑 ─────────────────────────────────────────────────────────────────────


async def backfill_protocol(
    pool: asyncpg.Pool,
    protocol: str,
    start_date: date | None,
    end_date: date | None,
    dry_run: bool,
) -> None:
    res_table = _RES_TABLES[protocol]
    update_sql = _UPDATE_SQL[protocol]

    # 构建日期过滤条件（用字符串拼接，日期值通过 Python 传入）
    date_clauses: list[str] = []
    if start_date:
        date_clauses.append(f"AND snapshot_date >= '{start_date}'")
    if end_date:
        date_clauses.append(f"AND snapshot_date <= '{end_date}'")
    date_filter = " ".join(date_clauses)

    # 查询待处理行数和日期列表
    pending_count: int = await pool.fetchval(
        _SQL_PENDING_COUNT.format(res_table=res_table, date_filter=date_filter)
    )
    if pending_count == 0:
        logger.info("[%s] 无待回填行，跳过", protocol.upper())
        return

    pending_dates: list[date] = [
        r["snapshot_date"]
        for r in await pool.fetch(
            _SQL_PENDING_DATES.format(res_table=res_table, date_filter=date_filter)
        )
    ]

    logger.info(
        "[%s] 待回填：%d 行，跨 %d 个快照日期（%s → %s）%s",
        protocol.upper(),
        pending_count,
        len(pending_dates),
        pending_dates[0] if pending_dates else "-",
        pending_dates[-1] if pending_dates else "-",
        "  [dry-run]" if dry_run else "",
    )

    total_updated = 0
    total_no_index = 0  # 因 market_snapshots 无对应 index 而跳过的日期

    with tqdm(
        total=len(pending_dates),
        desc=f"{protocol.upper()} 回填",
        unit="day",
    ) as pbar:
        for snapshot_date in pending_dates:
            if dry_run:
                # dry-run：只统计当天待处理行数，不执行 UPDATE
                count = await pool.fetchval(
                    f"""
                    SELECT COUNT(*) FROM loan."{res_table}"
                    WHERE snapshot_date = $1
                      AND scaled_supply_raw = 0
                      AND scaled_variable_debt_raw = 0
                      AND (supply_raw > 0 OR variable_debt_raw > 0)
                    """,
                    snapshot_date,
                )
                total_updated += count
                pbar.set_postfix({"date": str(snapshot_date), "rows": count})
            else:
                result = await pool.execute(update_sql, snapshot_date)
                # asyncpg execute() 返回 "UPDATE N" 字符串
                n = int(result.split()[-1])
                if n == 0:
                    total_no_index += 1
                    logger.debug(
                        "[%s] %s：0 行更新（market_snapshots 无对应 index）",
                        protocol.upper(),
                        snapshot_date,
                    )
                else:
                    total_updated += n
                pbar.set_postfix(
                    {"date": str(snapshot_date), "updated": n if not dry_run else "?"}
                )

            pbar.update(1)

    label = "[DRY-RUN] " if dry_run else ""
    logger.info(
        "%s[%s] 回填完成：%s %d 行，%d 天无 index 数据（market_snapshots 缺口）",
        label,
        protocol.upper(),
        "待更新" if dry_run else "已更新",
        total_updated,
        total_no_index,
    )


async def run(
    protocols: list[str],
    start_date: date | None,
    end_date: date | None,
    dry_run: bool,
) -> None:
    cfg = load_config()
    pool = await asyncpg.create_pool(
        host=cfg.postgres.host,
        port=cfg.postgres.port,
        user=cfg.postgres.user,
        password=cfg.postgres.password,
        database=cfg.postgres.database,
        min_size=1,
        max_size=3,
    )
    try:
        for protocol in protocols:
            await backfill_protocol(pool, protocol, start_date, end_date, dry_run)
    finally:
        await pool.close()


# ── CLI ────────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="回填 daily_reserve_positions 的 scaled_* 历史字段（纯 DB，无 RPC）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  uv run python scripts/backfill_daily_scaled_fields.py
  uv run python scripts/backfill_daily_scaled_fields.py --protocol v2
  uv run python scripts/backfill_daily_scaled_fields.py --protocol v3 --dry-run
  uv run python scripts/backfill_daily_scaled_fields.py --start 2023-01-27 --end 2024-06-30
        """,
    )
    p.add_argument(
        "--protocol",
        "-p",
        choices=["v2", "v3"],
        action="append",
        dest="protocols",
        metavar="PROTOCOL",
        help="协议版本（v2 / v3），可多次指定；默认同时处理 v2 和 v3",
    )
    p.add_argument(
        "--start",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="起始日期（含），默认不限",
    )
    p.add_argument(
        "--end",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="结束日期（含），默认不限",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计待处理行数，不执行 UPDATE",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    protocols: list[str] = args.protocols or ["v3", "v2"]
    asyncio.run(run(protocols, args.start, args.end, args.dry_run))


if __name__ == "__main__":
    main()
