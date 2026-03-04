"""
backfill_brief.py
─────────────────────────────────────────────────────────────────────────────
对 position_snapshot_cache 中 brief = '' 的旧数据，通过 AI-ContractParser
子模块批量解析并回填 brief 字段。

运行方式
    cd backend
    uv run python scripts/backfill_brief.py [--config config.yaml] [--dry-run]
                                             [--batch BATCH] [--limit LIMIT]

选项
    --config CONFIG   配置文件路径（默认 config.yaml）
    --dry-run         仅打印将要处理的 tx，不写入数据库
    --batch  BATCH    每批并发解析的 tx 数量（默认 20）
    --limit  LIMIT    最多处理多少行（默认不限，全量回填）
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

from aave_crawler.config import load_config  # noqa: E402
from aave_crawler.tx_parser import parse_tx_briefs  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── SQL ──────────────────────────────────────────────────────────────────────

_SQL_FETCH = """
SELECT id, tx_hash, protocol
FROM loan.position_snapshot_cache
WHERE brief = ''
ORDER BY block_timestamp ASC
"""

_SQL_FETCH_LIMIT = """
SELECT id, tx_hash, protocol
FROM loan.position_snapshot_cache
WHERE brief = ''
ORDER BY block_timestamp ASC
LIMIT $1
"""

# --force 模式：忽略 brief 是否为空，全量重写
_SQL_FETCH_FORCE = """
SELECT id, tx_hash, protocol
FROM loan.position_snapshot_cache
ORDER BY block_timestamp ASC
"""

_SQL_FETCH_FORCE_LIMIT = """
SELECT id, tx_hash, protocol
FROM loan.position_snapshot_cache
ORDER BY block_timestamp ASC
LIMIT $1
"""

_SQL_UPDATE = """
UPDATE loan.position_snapshot_cache
SET brief = $1
WHERE id = $2
"""


# ── 主逻辑 ────────────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    dsn = cfg.postgres.dsn

    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=5)

    try:
        # 1. 读取待处理行
        if args.force:
            fetch_sql  = _SQL_FETCH_FORCE_LIMIT if args.limit else _SQL_FETCH_FORCE
            mode_label = "全量重写（--force）"
        else:
            fetch_sql  = _SQL_FETCH_LIMIT if args.limit else _SQL_FETCH
            mode_label = "仅补空"

        async with pool.acquire() as conn:
            if args.limit:
                rows = await conn.fetch(fetch_sql, args.limit)
            else:
                rows = await conn.fetch(fetch_sql)

        total = len(rows)
        if total == 0:
            logger.info("没有需要处理的行（模式：%s）。", mode_label)
            return

        logger.info("共 %d 行待处理（模式：%s）", total, mode_label)
        if args.dry_run:
            for r in rows[:10]:
                logger.info("  [dry-run] id=%s  tx=%s  protocol=%s",
                             r["id"], r["tx_hash"], r["protocol"])
            if total > 10:
                logger.info("  ... 共 %d 行（仅展示前 10 行）", total)
            return

        # 2. 按批次处理
        batch_size = args.batch
        updated = 0
        failed = 0

        for batch_start in range(0, total, batch_size):
            batch = rows[batch_start: batch_start + batch_size]

            # 按 protocol 分组，减少无效 pool 地址切换
            # 实际上 parse_tx_briefs 每行指定一次 protocol，这里分组仅用于日志清晰度
            tx_hashes = [r["tx_hash"] for r in batch]
            protocols  = [r["protocol"] for r in batch]

            # 分别对每种 protocol 的 tx 解析（通常一批内 protocol 相同）
            # 为简化：逐行 gather，parse_tx_brief 内部有信号量限流
            briefs = await asyncio.gather(
                *[
                    _parse_one(tx, proto)
                    for tx, proto in zip(tx_hashes, protocols)
                ]
            )

            # 3. 批量写回
            async with pool.acquire() as conn:
                async with conn.transaction():
                    pairs = [
                        (brief, r["id"])
                        for brief, r in zip(briefs, batch)
                    ]
                    await conn.executemany(_SQL_UPDATE, pairs)

            batch_updated = sum(1 for b in briefs if b)
            batch_failed  = len(briefs) - batch_updated
            updated += batch_updated
            failed  += batch_failed

            logger.info(
                "进度 %d/%d  本批：成功 %d  空结果 %d",
                min(batch_start + batch_size, total),
                total,
                batch_updated,
                batch_failed,
            )

        logger.info(
            "回填完成：共处理 %d 行，解析成功 %d，空结果（不支持的方法等）%d",
            total, updated, failed,
        )

    finally:
        await pool.close()


async def _parse_one(tx_hash: str, protocol: str) -> str:
    """单笔解析，捕获异常保证不中断整批。"""
    try:
        results = await parse_tx_briefs([tx_hash], protocol=protocol)
        return results[0] if results else ""
    except Exception as exc:
        logger.warning("解析失败 tx=%s: %s", tx_hash, exc)
        return ""


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="回填 position_snapshot_cache.brief 字段"
    )
    parser.add_argument("--config",  default="config.yaml",
                        help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅打印待处理行，不修改数据库")
    parser.add_argument("--batch",   type=int, default=20,
                        help="每批并发解析数量（默认 20）")
    parser.add_argument("--limit",   type=int, default=0,
                        help="最多处理行数（0 = 全量，默认 0）")
    parser.add_argument("--force",   action="store_true",
                        help="全量重写：覆盖所有行（含已有 brief 的），用于修复格式错误")
    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
