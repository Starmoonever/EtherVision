"""
migrate_market_totals.py
──────────────────────────────────────────────────────────────────────────────
将旧物化视图 loan.aave_v{2|3}_market_totals 迁移为普通汇总表，
并从 loan.aave_v{2|3}_market_snapshots 全量回填数据。

执行步骤（每个协议）：
  1. DROP MATERIALIZED VIEW IF EXISTS  —— 删除旧物化视图（若已是普通表则跳过）
  2. CREATE TABLE IF NOT EXISTS        —— 建新汇总表
  3. INSERT ... WHERE NOT EXISTS       —— 从 snapshots 聚合回填全部区块

运行方式
    cd backend
    uv run python scripts/migrate_market_totals.py
    uv run python scripts/migrate_market_totals.py --protocol v3
    uv run python scripts/migrate_market_totals.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aave_crawler.config import load_config
from aave_crawler.market_collector import (_table_name, _view_name,
                                           ensure_market_snapshot_table,
                                           refresh_market_totals)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def _count_rows(pool: asyncpg.Pool, table: str) -> int:
    row = await pool.fetchrow(f"SELECT COUNT(*) AS n FROM loan.{table}")
    return int(row["n"]) if row else 0


async def _migrate_protocol(pool: asyncpg.Pool, protocol: str, dry_run: bool) -> None:
    totals = _view_name(protocol)
    snapshots = _table_name(protocol)

    # 检查 snapshots 表是否存在
    exists = await pool.fetchval(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'loan' AND table_name = $1
        )
        """,
        snapshots,
    )
    if not exists:
        logger.warning("[%s] 源表 loan.%s 不存在，跳过", protocol, snapshots)
        return

    snap_rows = await _count_rows(pool, snapshots)
    # 每个区块有多条 reserve 行，区块数 ≈ snap_rows / reserve_count
    distinct_blocks = await pool.fetchval(
        f"SELECT COUNT(DISTINCT block_number) FROM loan.{snapshots}"
    )
    logger.info(
        "[%s] loan.%s: %d 条 reserve 行，共 %d 个区块",
        protocol, snapshots, snap_rows, distinct_blocks,
    )

    if dry_run:
        logger.info("[%s] [dry-run] 跳过实际迁移", protocol)
        return

    # 1 & 2: 删旧物化视图 + 建新汇总表（内部幂等）
    logger.info("[%s] 初始化汇总表 loan.%s …", protocol, totals)
    await ensure_market_snapshot_table(pool, protocol)

    # 3: 全量回填
    logger.info("[%s] 开始回填 loan.%s …", protocol, totals)
    await refresh_market_totals(pool, protocol)

    total_rows = await _count_rows(pool, totals)
    logger.info("[%s] ✅ 迁移完成：loan.%s 共 %d 行", protocol, totals, total_rows)


async def _main() -> None:
    p = argparse.ArgumentParser(description="迁移 market_totals 物化视图 → 普通汇总表")
    p.add_argument(
        "--protocol", "-p",
        dest="protocols",
        action="append",
        default=[],
        choices=["v2", "v3"],
        metavar="PROTOCOL",
        help="v2 | v3，可多次指定（默认 v2 和 v3 都迁移）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印信息，不执行任何 DDL 或数据写入",
    )
    p.add_argument(
        "--config",
        type=str,
        default="",
        help="配置文件路径（默认 config.yaml）",
    )
    args = p.parse_args()

    protocols = args.protocols or ["v2", "v3"]
    cfg = load_config(args.config or None)

    pool = await asyncpg.create_pool(dsn=cfg.postgres.dsn, min_size=1, max_size=3)
    try:
        for prot in protocols:
            await _migrate_protocol(pool, prot, dry_run=args.dry_run)
    finally:
        await pool.close()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
