"""
fix_v2_positions.py
──────────────────────────────────────────────────────────────────────────────
修复 V2 仓位表中因 oracle 价格未归一化（ETH/18dec 当作 USD/8dec 使用）
导致的数值膨胀问题。

膨胀倍数约 330 万倍（ETH≈$3000 时）：
  真实 $0.30  → 腐败 total_collateral_usd ≈ $1e6
  真实 $3000  → 腐败 total_collateral_usd ≈ $1e10
  WETH 真实价 ≈ $3000 → 腐败 price_usd ≈ 1e10

受影响的表（daily_positions 使用 fetch_block_prices 已正确归一化，无需修复）：
  - loan.aave_v2_eth_positions_collateral         — 检测 total_collateral_usd > 1e6
  - loan.aave_v2_eth_positions_borrow             — 同上
  - loan.aave_v2_eth_reserve_positions_collateral — 检测 price_usd > 1e5
  - loan.aave_v2_eth_reserve_positions_borrow     — 同上

两级检测策略：
  1. 通过 positions 主表找到腐败用户 → 删除其 positions 行 + reserve 明细行
  2. 直接扫描 reserve 表中残留的腐败 price_usd 行（对应 positions 已被重爬覆盖的情况）

运行方式
    cd backend
    uv run python scripts/fix_v2_positions.py [--config config.yaml] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aave_crawler.config import load_config  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 阈值 ──────────────────────────────────────────────────────────────────────

# positions 主表：USD 总抵押品阈值
# 膨胀倍数 ~330万；真实 $0.30 → 腐败 $1e6，所以 $1e6 可覆盖几乎所有腐败行
COLLATERAL_USD_THRESHOLD = Decimal("1e6")

# reserve 明细表：单资产 price_usd 阈值
# 任何资产真实价格均低于 $100,000（含 WBTC）；腐败后 WETH 约为 $1e10
PRICE_USD_THRESHOLD = Decimal("1e5")

# ── 表配置 ────────────────────────────────────────────────────────────────────

# (positions 表, reserve_positions 表, 描述)
_PROTOCOL_TABLES: list[tuple[str, str, str]] = [
    (
        "aave_v2_eth_positions_collateral",
        "aave_v2_eth_reserve_positions_collateral",
        "collateral",
    ),
    (
        "aave_v2_eth_positions_borrow",
        "aave_v2_eth_reserve_positions_borrow",
        "borrow",
    ),
]

# ── SQL ───────────────────────────────────────────────────────────────────────

_SQL_POS_COUNT = 'SELECT COUNT(*) FROM loan."{t}" WHERE total_collateral_usd > $1'
_SQL_POS_SAMPLE = """
    SELECT user_address, total_collateral_usd, total_debt_usd, liq_price, scanned_at
    FROM loan."{t}"
    WHERE total_collateral_usd > $1
    ORDER BY total_collateral_usd DESC
    LIMIT 5
"""
_SQL_POS_CORRUPT_USERS = """
    SELECT user_address FROM loan."{t}" WHERE total_collateral_usd > $1
"""
_SQL_POS_DELETE = """
    DELETE FROM loan."{t}" WHERE total_collateral_usd > $1 RETURNING user_address
"""

_SQL_RES_COUNT = 'SELECT COUNT(*) FROM loan."{t}" WHERE price_usd > $1'
_SQL_RES_SAMPLE = """
    SELECT user_address, symbol, price_usd, supply_usd, total_debt_usd
    FROM loan."{t}"
    WHERE price_usd > $1
    ORDER BY price_usd DESC
    LIMIT 5
"""
_SQL_RES_DELETE_BY_USERS = 'DELETE FROM loan."{t}" WHERE user_address = ANY($1::text[])'
_SQL_RES_DELETE_ORPHAN = """
    DELETE FROM loan."{t}" WHERE price_usd > $1 RETURNING user_address
"""


# ── 诊断 ──────────────────────────────────────────────────────────────────────


async def diagnose(conn: Any, threshold_usd: Decimal, threshold_price: Decimal) -> None:
    """统计并展示各表中的异常行。"""
    for pos_table, res_table, side in _PROTOCOL_TABLES:
        # ── positions 主表 ───────────────────────────────────────────────────
        pos_cnt: int = (
            await conn.fetchval(_SQL_POS_COUNT.format(t=pos_table), threshold_usd) or 0
        )
        logger.info(
            "[%s] %-50s  腐败行: %d  (total_collateral_usd > %s)",
            side,
            pos_table,
            pos_cnt,
            threshold_usd,
        )
        if pos_cnt > 0:
            for r in await conn.fetch(
                _SQL_POS_SAMPLE.format(t=pos_table), threshold_usd
            ):
                logger.info(
                    "    user=%-42s  col_usd=%-25s  liq=%-15s  at=%s",
                    r["user_address"],
                    r["total_collateral_usd"],
                    r["liq_price"],
                    r["scanned_at"],
                )

        # ── reserve 明细表 ───────────────────────────────────────────────────
        res_cnt: int = (
            await conn.fetchval(_SQL_RES_COUNT.format(t=res_table), threshold_price)
            or 0
        )
        logger.info(
            "[%s] %-50s  腐败行: %d  (price_usd > %s)",
            side,
            res_table,
            res_cnt,
            threshold_price,
        )
        if res_cnt > 0:
            for r in await conn.fetch(
                _SQL_RES_SAMPLE.format(t=res_table), threshold_price
            ):
                logger.info(
                    "    user=%-42s  symbol=%-10s  price_usd=%-20s  supply_usd=%s",
                    r["user_address"],
                    r["symbol"],
                    r["price_usd"],
                    r["supply_usd"],
                )


# ── 清理 ──────────────────────────────────────────────────────────────────────


async def clean(conn: Any, threshold_usd: Decimal, threshold_price: Decimal) -> None:
    """
    两级删除（单事务）：
      1. 通过 positions 主表找到腐败用户，删除其 positions 行 + 对应 reserve 明细
      2. 直接删除 reserve 表中残留的腐败 price_usd 行（positions 已被重爬覆盖的情况）
    """
    async with conn.transaction():
        for pos_table, res_table, side in _PROTOCOL_TABLES:
            # 第 1 级：通过 positions 主表
            corrupt_users: list[str] = [
                r["user_address"]
                for r in await conn.fetch(
                    _SQL_POS_CORRUPT_USERS.format(t=pos_table), threshold_usd
                )
            ]
            if corrupt_users:
                res_del = await conn.execute(
                    _SQL_RES_DELETE_BY_USERS.format(t=res_table), corrupt_users
                )
                pos_del = await conn.execute(
                    _SQL_POS_DELETE.format(t=pos_table), threshold_usd
                )
                logger.info(
                    "[%s] 第1级 — 删除 positions %s 行，reserve %s 行",
                    side,
                    pos_del.split()[-1],
                    res_del.split()[-1],
                )
            else:
                logger.info("[%s] 第1级 — positions 主表无腐败行", side)

            # 第 2 级：直接扫描 reserve 表残留腐败 price_usd
            orphan_rows = await conn.fetch(
                _SQL_RES_DELETE_ORPHAN.format(t=res_table), threshold_price
            )
            if orphan_rows:
                orphan_users = {r["user_address"] for r in orphan_rows}
                logger.info(
                    "[%s] 第2级 — 删除 reserve 孤立腐败行 %d 条，涉及用户 %d 个",
                    side,
                    len(orphan_rows),
                    len(orphan_users),
                )
            else:
                logger.info("[%s] 第2级 — reserve 表无残留腐败行", side)


# ── 主逻辑 ────────────────────────────────────────────────────────────────────


async def run(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    ssl_val: bool | str = False if cfg.postgres.ssl == "disable" else cfg.postgres.ssl
    pool = await asyncpg.create_pool(
        cfg.postgres.dsn, ssl=ssl_val, min_size=1, max_size=3
    )

    try:
        async with pool.acquire() as conn:
            logger.info(
                "检测阈值 — positions: total_collateral_usd > %s  |  reserve: price_usd > %s",
                COLLATERAL_USD_THRESHOLD,
                PRICE_USD_THRESHOLD,
            )
            await diagnose(conn, COLLATERAL_USD_THRESHOLD, PRICE_USD_THRESHOLD)

            if args.dry_run:
                logger.info("[dry-run] 跳过删除步骤。")
                return

            logger.info("开始清理腐败数据...")
            await clean(conn, COLLATERAL_USD_THRESHOLD, PRICE_USD_THRESHOLD)
            logger.info("清理完成。")

        logger.info("")
        logger.info("=" * 70)
        logger.info("请重新运行 V2 爬虫以补回正确数据：")
        logger.info("  uv run aave-crawler sync-addresses -p v2")
        logger.info("  uv run aave-crawler sync-addresses -p v2_borrow")
        logger.info("  uv run aave-crawler crawl -p v2")
        logger.info("  uv run aave-crawler crawl -p v2_borrow")
        logger.info("=" * 70)

    finally:
        await pool.close()


# ── CLI ──────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="检测并删除 V2 仓位表中因 oracle 价格未归一化导致的腐败数据"
    )
    p.add_argument(
        "--config", default="config.yaml", help="配置文件路径（默认 config.yaml）"
    )
    p.add_argument("--dry-run", action="store_true", help="仅打印异常统计，不执行删除")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
