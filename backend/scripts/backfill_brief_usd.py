"""
backfill_brief_usd.py
─────────────────────────────────────────────────────────────────────────────
对 position_snapshot_cache 中已有数据，利用 reserves_json 中存储的 token 价格，
重新生成含「（价值 X.XX USD）」描述的 brief 并写回数据库。

与 backfill_brief.py 的区别：
  - 额外读取 reserves_json 字段，构建 prices dict
  - 调用 parse_tx_brief(tx_hash, protocol, prices=prices) 绕过内存缓存
  - 默认处理 所有 行（不限于 brief='' 的空行），相当于总是 --force

运行方式
    cd backend
    uv run python scripts/backfill_brief_usd.py [--config config.yaml] [--dry-run]
                                                  [--batch BATCH] [--limit LIMIT]
                                                  [--only-empty]

选项
    --config CONFIG   配置文件路径（默认 config.yaml）
    --dry-run         仅打印待处理 tx，不写入数据库
    --batch  BATCH    每批并发解析的 tx 数量（默认 20）
    --limit  LIMIT    最多处理多少行（0 = 全量，默认 0）
    --only-empty      仅处理 brief = '' 的行（跳过已有 brief 的行）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from decimal import Decimal
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aave_crawler.config import load_config  # noqa: E402
from aave_crawler.constants import WETH_ADDR as _WETH_ADDR  # noqa: E402
from aave_crawler.tx_parser import parse_briefs_from_metas  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── SQL ──────────────────────────────────────────────────────────────────────

_SQL_FETCH_ALL = """
SELECT id, tx_hash, protocol, reserves_json, eth_price_usd
FROM loan.position_snapshot_cache
ORDER BY block_timestamp ASC
"""

_SQL_FETCH_ALL_LIMIT = """
SELECT id, tx_hash, protocol, reserves_json, eth_price_usd
FROM loan.position_snapshot_cache
ORDER BY block_timestamp ASC
LIMIT $1
"""

_SQL_FETCH_EMPTY = """
SELECT id, tx_hash, protocol, reserves_json, eth_price_usd
FROM loan.position_snapshot_cache
WHERE brief = ''
ORDER BY block_timestamp ASC
"""

_SQL_FETCH_EMPTY_LIMIT = """
SELECT id, tx_hash, protocol, reserves_json, eth_price_usd
FROM loan.position_snapshot_cache
WHERE brief = ''
ORDER BY block_timestamp ASC
LIMIT $1
"""

_SQL_UPDATE = """
UPDATE loan.position_snapshot_cache
SET brief = $1
WHERE id = $2
"""


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _build_prices(
    reserves_json: list[dict] | str | None,
    eth_price_usd: Decimal | None = None,
) -> dict[str, Decimal]:
    """从 reserves_json 字段构建 token_address_lower → USD 价格的映射。

    eth_price_usd 作为 WETH 价格备用：当用户全额取出 WETH 导致 reserves_json
    中无 WETH 条目时，仍能为 ETH/WETH 相关操作提供 USD 注释。
    """
    if not reserves_json:
        prices: dict[str, Decimal] = {}
        if eth_price_usd:
            prices[_WETH_ADDR] = eth_price_usd
        return prices
    if isinstance(reserves_json, str):
        try:
            reserves_json = json.loads(reserves_json)
        except Exception:
            return {}
    prices = {}
    for r in reserves_json:
        addr = r.get("token_address", "").lower()
        price_raw = r.get("price_usd", "")
        if addr and price_raw:
            try:
                prices[addr] = Decimal(str(price_raw))
            except Exception:
                pass
    # WETH 可能因余额为 0 而缺失，用 eth_price_usd 补充
    if eth_price_usd:
        prices.setdefault(_WETH_ADDR, eth_price_usd)
    return prices


async def _parse_one(
    tx_hash: str,
    protocol: str,
    prices: dict[str, Decimal],
) -> str:
    """单笔解析（仅保留签名兼容性，实际不再使用）。"""
    raise NotImplementedError("use parse_briefs_from_metas instead")


# ── 主逻辑 ────────────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    dsn = cfg.postgres.dsn

    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=5)

    try:
        # 1. 读取待处理行
        if args.only_empty:
            fetch_sql = _SQL_FETCH_EMPTY_LIMIT if args.limit else _SQL_FETCH_EMPTY
            mode_label = "仅补空（--only-empty）"
        else:
            fetch_sql = _SQL_FETCH_ALL_LIMIT if args.limit else _SQL_FETCH_ALL
            mode_label = "全量重写（含 USD 价值描述）"

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
                rv = r["reserves_json"]
                eth_p = Decimal(str(r["eth_price_usd"])) if r["eth_price_usd"] else None
                prices = _build_prices(rv if isinstance(rv, list) else (json.loads(rv) if rv else []), eth_p)
                logger.info(
                    "  [dry-run] id=%s  tx=%s  protocol=%s  tokens=%d",
                    r["id"], r["tx_hash"], r["protocol"], len(prices),
                )
            if total > 10:
                logger.info("  ... 共 %d 行（仅展示前 10 行）", total)
            return

        # 2. 按批次并发解析并写回
        batch_size = args.batch
        updated = 0
        failed = 0

        for batch_start in range(0, total, batch_size):
            batch = rows[batch_start: batch_start + batch_size]

            briefs = await parse_briefs_from_metas(
                pool,
                [
                    {
                        "tx_hash": r["tx_hash"],
                        "protocol": r["protocol"],
                        "prices": _build_prices(
                            r["reserves_json"],
                            Decimal(str(r["eth_price_usd"])) if r["eth_price_usd"] else None,
                        ),
                    }
                    for r in batch
                ],
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
            "回填完成：共处理 %d 行，解析成功 %d，空结果（不支持的方法等）%d",
            total, updated, failed,
        )

    finally:
        await pool.close()


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="回填 position_snapshot_cache.brief 字段（含 USD 价值描述）"
    )
    parser.add_argument("--config", default="config.yaml",
                        help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅打印待处理行，不修改数据库")
    parser.add_argument("--batch", type=int, default=20,
                        help="每批并发解析数量（默认 20）")
    parser.add_argument("--limit", type=int, default=0,
                        help="最多处理行数（0 = 全量，默认 0）")
    parser.add_argument("--only-empty", action="store_true",
                        help="仅处理 brief = '' 的行（默认全量重写）")
    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
