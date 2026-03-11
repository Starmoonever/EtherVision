"""
backfill_brief.py
─────────────────────────────────────────────────────────────────────────────
对 aave_position_snapshots 中 brief = '' 的旧数据，从 aave_history 读取操作
数据并回填 brief 字段。

格式："{操作类型} {数量} {token符号} (价值 {value} usd)"
（与 tx_parser.generate_brief 完全一致）

运行方式
    cd backend
    uv run python scripts/backfill_brief.py [--dry-run]
                                             [--batch BATCH] [--limit LIMIT]

选项
    --dry-run         仅打印将要处理的 tx，不写入数据库
    --batch  BATCH    每批处理的行数（默认 500）
    --limit  LIMIT    最多处理多少行（默认不限，全量回填）
    --force           全量重写（含已有 brief 的行）
    --pattern PATTERN 只处理 brief LIKE '%PATTERN%' 的行（如 --pattern 执行）
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aave_crawler.config import load_config  # noqa: E402
from aave_crawler.db import create_pool  # noqa: E402
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
FROM loan.aave_position_snapshots
WHERE brief = ''
ORDER BY block_timestamp ASC
"""

_SQL_FETCH_LIMIT = """
SELECT id, tx_hash, protocol
FROM loan.aave_position_snapshots
WHERE brief = ''
ORDER BY block_timestamp ASC
LIMIT $1
"""

_SQL_FETCH_FORCE = """
SELECT id, tx_hash, protocol
FROM loan.aave_position_snapshots
ORDER BY block_timestamp ASC
"""

_SQL_FETCH_FORCE_LIMIT = """
SELECT id, tx_hash, protocol
FROM loan.aave_position_snapshots
ORDER BY block_timestamp ASC
LIMIT $1
"""

_SQL_FETCH_PATTERN = """
SELECT id, tx_hash, protocol
FROM loan.aave_position_snapshots
WHERE brief LIKE '%' || $1 || '%'
ORDER BY block_timestamp ASC
"""

_SQL_FETCH_PATTERN_LIMIT = """
SELECT id, tx_hash, protocol
FROM loan.aave_position_snapshots
WHERE brief LIKE '%' || $1 || '%'
ORDER BY block_timestamp ASC
LIMIT $2
"""

_SQL_UPDATE = """
UPDATE loan.aave_position_snapshots
SET brief = $1
WHERE id = $2
"""


# ── 主逻辑 ────────────────────────────────────────────────────────────────────


async def run(args: argparse.Namespace) -> None:
    cfg = load_config()
    pool = await create_pool(cfg.postgres)

    try:
        # 1. 读取待处理行
        if args.pattern:
            # --pattern 模式：只处理 brief LIKE '%pattern%' 的行
            if args.limit:
                fetch_sql = _SQL_FETCH_PATTERN_LIMIT
                rows = await pool.fetch(fetch_sql, args.pattern, args.limit)
            else:
                fetch_sql = _SQL_FETCH_PATTERN
                rows = await pool.fetch(fetch_sql, args.pattern)
            mode_label = f"匹配 '%{args.pattern}%'"
        elif args.force:
            fetch_sql = _SQL_FETCH_FORCE_LIMIT if args.limit else _SQL_FETCH_FORCE
            mode_label = "全量重写（--force）"
            async with pool.acquire() as conn:
                rows = (
                    await conn.fetch(fetch_sql, args.limit)
                    if args.limit
                    else await conn.fetch(fetch_sql)
                )
        else:
            fetch_sql = _SQL_FETCH_LIMIT if args.limit else _SQL_FETCH
            mode_label = "仅补空"
            async with pool.acquire() as conn:
                rows = (
                    await conn.fetch(fetch_sql, args.limit)
                    if args.limit
                    else await conn.fetch(fetch_sql)
                )

        total = len(rows)
        if total == 0:
            logger.info("没有需要处理的行（模式：%s）。", mode_label)
            return

        logger.info("共 %d 行待处理（模式：%s）", total, mode_label)
        if args.dry_run:
            for r in rows[:10]:
                logger.info(
                    "  [dry-run] id=%s  tx=%s  protocol=%s",
                    r["id"],
                    r["tx_hash"],
                    r["protocol"],
                )
            if total > 10:
                logger.info("  ... 共 %d 行（仅展示前 10 行）", total)
            return

        # 2. 按批次处理
        batch_size = args.batch
        updated = 0
        failed = 0

        for batch_start in range(0, total, batch_size):
            batch = rows[batch_start : batch_start + batch_size]

            # 同一批内按 protocol 分组，分别查市场快照价格
            # 每组调用一次 parse_tx_briefs(pool, hashes, protocol=...)
            # 最后按原始顺序重组结果
            proto_groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
            for idx, r in enumerate(batch):
                proto_groups[r["protocol"]].append((idx, r["tx_hash"]))

            briefs: list[str] = [""] * len(batch)
            for proto, idx_hashes in proto_groups.items():
                idxs = [ih[0] for ih in idx_hashes]
                hashes = [ih[1] for ih in idx_hashes]
                results = await parse_tx_briefs(pool, hashes, protocol=proto)
                for i, brief in zip(idxs, results):
                    briefs[i] = brief

            # 3. 批量写回
            pairs = [(brief, r["id"]) for brief, r in zip(briefs, batch)]
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.executemany(_SQL_UPDATE, pairs)

            batch_updated = sum(1 for b in briefs if b)
            batch_failed = len(briefs) - batch_updated
            updated += batch_updated
            failed += batch_failed

            logger.info(
                "进度 %d/%d  本批：成功 %d  空结果 %d",
                min(batch_start + batch_size, total),
                total,
                batch_updated,
                batch_failed,
            )

        logger.info(
            "回填完成：共处理 %d 行，解析成功 %d，空结果 %d",
            total,
            updated,
            failed,
        )

    finally:
        await pool.close()


# ── 入口 ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="回填 aave_position_snapshots.brief 字段"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="仅打印待处理行，不修改数据库"
    )
    parser.add_argument(
        "--batch", type=int, default=500, help="每批处理行数（默认 500）"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="最多处理行数（0 = 全量，默认 0）"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="全量重写：覆盖所有行（含已有 brief 的），用于修复格式",
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default="",
        help="只处理 brief LIKE '%%PATTERN%%' 的行（如 --pattern 执行）",
    )
    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
