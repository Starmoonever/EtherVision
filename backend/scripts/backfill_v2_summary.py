"""
backfill_v2_summary.py
──────────────────────────────────────────────────────────────────────────────
修复 aave_position_snapshots 中 V2 旧数据的 total_collateral_usd /
total_debt_usd / available_borrows_usd 三个字段。

根因：V2 的 getUserAccountData 返回 ETH 计价（18 位精度），而旧代码未对
AccountSummary.total_*_base 做 ETH→USD 归一化（仅归一化了 asset_prices），
导致这三个字段存成了 ETH/18dec 规格，比真实 USD 值大约 10^10 倍。

修复已在 rpc.py 中落实。本脚本对 DB 里已有的 V2 快照，逐条重新 RPC 重放
并覆盖写回（brief / tx_hash / block_timestamp / eth_price_usd 保持原值）。

运行方式
    cd backend
    uv run python scripts/backfill_v2_summary.py [--config config.yaml]
                                                  [--dry-run]
                                                  [--batch BATCH]
                                                  [--limit LIMIT]

选项
    --config CONFIG   配置文件路径（默认 config.yaml）
    --dry-run         仅打印要处理的行，不写入数据库
    --batch  BATCH    每批并发 RPC 重放的行数（默认 10）
    --limit  LIMIT    最多处理多少行（默认不限，全量）
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from decimal import Decimal
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aave_crawler.config import load_config  # noqa: E402
from aave_crawler.db import upsert_snapshot_cache  # noqa: E402
from aave_crawler.rpc import (  # noqa: E402
    CONTRACTS_V2,
    EMPTY_POSITION,
    build_web3,
    fetch_user_position_at_block,
    get_all_reserve_tokens,
    get_reserve_config,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── SQL ───────────────────────────────────────────────────────────────────────

_SQL_FETCH_ALL = """
SELECT id, user_address, block_number, tx_hash, block_timestamp,
       eth_price_usd, brief
FROM loan.aave_position_snapshots
WHERE protocol = 'v2'
ORDER BY block_timestamp ASC
"""

_SQL_FETCH_LIMIT = """
SELECT id, user_address, block_number, tx_hash, block_timestamp,
       eth_price_usd, brief
FROM loan.aave_position_snapshots
WHERE protocol = 'v2'
ORDER BY block_timestamp ASC
LIMIT $1
"""


# ── 预取公共数据 ─────────────────────────────────────────────────────────────


async def _load_v2_common_data(w3):
    """加载 V2 储备资产列表、配置，不加载价格（价格在 fetch_user_position_at_block 内查）。"""
    logger.info("加载 V2 储备资产列表和配置...")
    reserve_tokens = await get_all_reserve_tokens(w3, CONTRACTS_V2)
    addresses = [rt.token_address for rt in reserve_tokens]

    configs = await asyncio.gather(
        *[get_reserve_config(w3, a, CONTRACTS_V2) for a in addresses],
        return_exceptions=True,
    )
    reserve_configs = {
        a: c for a, c in zip(addresses, configs) if not isinstance(c, Exception)
    }
    logger.info(
        "V2 储备资产数量: %d，成功加载配置: %d",
        len(reserve_tokens),
        len(reserve_configs),
    )
    return reserve_tokens, reserve_configs


# ── 主逻辑 ────────────────────────────────────────────────────────────────────


async def run(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    db_pool = await asyncpg.create_pool(cfg.postgres.dsn, min_size=2, max_size=5)

    try:
        # 1. 读取待处理的 V2 快照行
        async with db_pool.acquire() as conn:
            if args.limit:
                rows = await conn.fetch(_SQL_FETCH_LIMIT, args.limit)
            else:
                rows = await conn.fetch(_SQL_FETCH_ALL)

        total = len(rows)
        logger.info("待处理 V2 快照行数: %d", total)
        if total == 0:
            logger.info("无 V2 数据，退出。")
            return

        if args.dry_run:
            for r in rows[:20]:
                logger.info(
                    "  [dry-run] user=%s block=%s tx=%s...",
                    r["user_address"],
                    r["block_number"],
                    r["tx_hash"][:20],
                )
            if total > 20:
                logger.info("  ... （共 %d 行，仅显示前 20）", total)
            return

        # 2. 初始化 Web3 + 预取公共数据
        w3 = await build_web3(cfg)
        reserve_tokens, reserve_configs = await _load_v2_common_data(w3)
        semaphore = asyncio.Semaphore(args.batch)

        # 3. 分批 RPC 重放
        ok = fail = skip = 0
        batch_size = args.batch

        for batch_start in range(0, total, batch_size):
            batch = rows[batch_start : batch_start + batch_size]

            tasks = [
                fetch_user_position_at_block(
                    w3,
                    r["user_address"],
                    reserve_tokens,
                    reserve_configs,  # type: ignore[arg-type]
                    r["block_number"],
                    semaphore,
                    CONTRACTS_V2,
                )
                for r in batch
            ]
            results = await asyncio.gather(*tasks)

            new_positions = []
            new_metas = []
            new_briefs = []

            for r, res in zip(batch, results):
                if res is None:
                    logger.warning(
                        "RPC 重放失败，跳过 user=%s block=%s tx=%s...",
                        r["user_address"],
                        r["block_number"],
                        r["tx_hash"][:20],
                    )
                    fail += 1
                    continue
                if res is EMPTY_POSITION:
                    # block 上该用户无仓位（已平仓），保留原行不处理
                    logger.debug(
                        "block %s 用户 %s 无仓位，跳过",
                        r["block_number"],
                        r["user_address"],
                    )
                    skip += 1
                    continue

                pos, eth_price_raw = res  # type: ignore[misc]
                new_positions.append(pos)
                new_metas.append(
                    {
                        "tx_hash": r["tx_hash"],
                        "block_timestamp": r["block_timestamp"],
                        "eth_price_usd": Decimal(eth_price_raw) / Decimal(10**8),
                        "protocol": "v2",
                    }
                )
                new_briefs.append(r["brief"])  # 保留原 brief
                ok += 1

            if new_positions:
                written = await upsert_snapshot_cache(
                    db_pool,
                    positions=new_positions,
                    tx_meta=new_metas,
                    briefs=new_briefs,
                )
                logger.info(
                    "进度 %d/%d  本批写入 %d 条（本批失败 %d，跳过 %d）",
                    min(batch_start + batch_size, total),
                    total,
                    written,
                    fail,
                    skip,
                )

        logger.info(
            "完成。成功: %d  失败: %d  跳过（无仓位）: %d  共: %d",
            ok,
            fail,
            skip,
            total,
        )

    finally:
        await db_pool.close()


# ── CLI ──────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="回填 V2 AccountSummary 字段（ETH→USD 归一化修复）"
    )
    p.add_argument("--config", default="config.yaml", help="配置文件路径")
    p.add_argument("--dry-run", action="store_true", help="仅打印待处理行，不写入 DB")
    p.add_argument(
        "--batch", type=int, default=10, help="每批并发 RPC 重放数量（默认 10）"
    )
    p.add_argument("--limit", type=int, default=None, help="最多处理行数（默认全量）")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
