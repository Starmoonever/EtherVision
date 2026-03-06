"""
collect_market_snapshots.py
──────────────────────────────────────────────────────────────────────────────
采集 Aave V2 / V3 历史大盘快照，通过 eth_call@block 查询 archive 节点。

每次采集指定区块高度下所有 reserve 的：
  - 总供给 / 总借贷（原始整数 + USD）
  - 存款 / 借款利率（ray 原始值，27 位精度）
  - 资产价格（USD 8 位精度）
  - 利用率（衍生，0.0～1.0）
  - 区块时间戳

结果写入 loan.aave_v2_market_snapshots / loan.aave_v3_market_snapshots，
以 (block_number, token_address) 为主键幂等 UPSERT。

运行方式
    cd backend
    # 采集单个区块
    uv run python scripts/collect_market_snapshots.py -p v3 --block 21000000
    # 采集单个日期（UTC 0 点附近区块）
    uv run python scripts/collect_market_snapshots.py -p v2 -p v3 --date 2024-06-01
    # 采集日期区间（每 7 天一个快照）
    uv run python scripts/collect_market_snapshots.py -p v3 \\
        --from-date 2024-01-01 --to-date 2025-01-01 --step-days 7

选项
    -p / --protocol     v2 | v3，可多次指定（默认 v3）
    --block    N        指定单个区块号（可与 --date 互斥使用）
    --date     DATE     指定日期（UTC 0 点），自动二分搜索最近区块
    --from-date DATE    起始日期（配合 --step-days 生成区间）
    --to-date   DATE    结束日期（默认今天）
    --step-days N       日期步长（天，默认 1）
    --rpc-concurrency N RPC 并发上限（默认 12，archive 节点可适当提高）
    --dry-run           仅打印将要采集的区块/协议，不执行 RPC/写库
    --config   PATH     配置文件路径（默认 config.yaml）
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aave_crawler.config import load_config
from aave_crawler.market_collector import (_block_at_timestamp,
                                           collect_block_snapshot,
                                           ensure_block_timestamps_table,
                                           ensure_market_snapshot_table,
                                           refresh_market_totals,
                                           upsert_block_timestamps)
from aave_crawler.rpc import build_web3
from web3 import AsyncWeb3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)



async def _date_to_block(
    w3: AsyncWeb3,
    date_str: str,
    pool: "asyncpg.Pool | None" = None,
) -> int:
    """将 'YYYY-MM-DD'（UTC 0 点）转换为最近区块号。

    若提供 pool，先从 eth_block_timestamps 缓存表查询（误差窗口 ±10 分钟），
    命中则跳过二分搜索；未命中则执行 RPC 搜索后写入缓存。
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    ts = int(dt.timestamp())

    if pool is not None:
        # 查缓存：找 block_timestamp 最接近 UTC 0 点且在 ±10 分钟内的区块
        row = await pool.fetchrow(
            """
            SELECT block_number, block_timestamp
            FROM loan.eth_block_timestamps
            WHERE block_timestamp BETWEEN $1 AND $2
            ORDER BY ABS(EXTRACT(EPOCH FROM (block_timestamp - $3))) ASC
            LIMIT 1
            """,
            dt - timedelta(minutes=10),
            dt + timedelta(minutes=10),
            dt,
        )
        if row:
            logger.info(
                "日期 %s → 区块 %d (缓存命中，block_ts=%s)",
                date_str, row["block_number"], row["block_timestamp"].isoformat(),
            )
            return int(row["block_number"])

    block = await _block_at_timestamp(w3, ts)
    block_meta = await w3.eth.get_block(block)
    block_ts = datetime.fromtimestamp(int(block_meta["timestamp"]), tz=timezone.utc)
    logger.info("日期 %s (unix=%d) → 区块 %d (block_ts=%s)", date_str, ts, block, block_ts.isoformat())

    if pool is not None:
        await upsert_block_timestamps(pool, [(block, block_ts)])

    return block


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="采集 Aave V2/V3 历史大盘快照（eth_call@block）"
    )
    p.add_argument(
        "-p", "--protocol",
        dest="protocols",
        action="append",
        default=[],
        choices=["v2", "v3"],
        metavar="PROTOCOL",
        help="v2 | v3，可多次指定（默认 v3）",
    )
    # 区块来源（三选其一）
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--block", type=int, help="指定单个区块号")
    group.add_argument("--date", type=str, metavar="YYYY-MM-DD", help="指定日期（UTC 0 点）")
    group.add_argument("--from-date", type=str, metavar="YYYY-MM-DD",
                       help="起始日期（配合 --step-days）")

    p.add_argument("--to-date",   type=str, default="", metavar="YYYY-MM-DD",
                   help="结束日期（默认今天，配合 --from-date）")
    p.add_argument("--step-days", type=int, default=1,
                   help="日期步长（天，默认 1）")
    p.add_argument("--rpc-concurrency", type=int, default=12,
                   help="RPC 并发上限（默认 12）")
    p.add_argument("--dry-run", action="store_true",
                   help="仅打印将要采集的区块/协议，不执行 RPC/写库")
    p.add_argument("--config", type=str, default="",
                   help="配置文件路径（默认 config.yaml）")
    return p.parse_args()


async def _main() -> None:
    args = _parse_args()

    protocols = args.protocols or ["v3"]
    cfg = load_config(args.config or None)

    # 调整日志级别
    logging.getLogger().setLevel(getattr(logging, cfg.log_level.upper(), logging.INFO))

    # 构建 Web3（所有协议共用同一 RPC 连接，因为都在 Ethereum Mainnet）
    w3 = await build_web3(cfg)
    semaphore = asyncio.Semaphore(args.rpc_concurrency)

    # 提前创建 DB 连接池（date→block 缓存查询需要）
    pool = await asyncpg.create_pool(dsn=cfg.postgres.dsn, min_size=2, max_size=5)
    try:
        # 确保缓存表存在（全局，与协议无关，只建一次）
        await ensure_block_timestamps_table(pool)

        # 确定目标区块列表
        target_blocks: list[int] = []

        if args.block is not None:
            target_blocks = [args.block]

        elif args.date:
            target_blocks = [await _date_to_block(w3, args.date, pool)]

        else:  # args.from_date
            end_str = args.to_date or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            start_dt = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end_dt   = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            step     = timedelta(days=args.step_days)

            date_list: list[str] = []
            cur = start_dt
            while cur <= end_dt:
                date_list.append(cur.strftime("%Y-%m-%d"))
                cur += step

            logger.info("日期区间 %s → %s，步长 %d 天，共 %d 个时间点",
                        args.from_date, end_str, args.step_days, len(date_list))

            # 串行将日期转换为区块号（缓存命中时跳过 RPC 二分搜索）
            for d in date_list:
                target_blocks.append(await _date_to_block(w3, d, pool))

        logger.info("目标区块: %s", target_blocks)
        logger.info("目标协议: %s", protocols)

        if args.dry_run:
            logger.info("[dry-run] 模式，不执行 RPC 采集，退出。")
            for prot in protocols:
                for blk in target_blocks:
                    logger.info("[dry-run] protocol=%s  block=%d", prot, blk)
            return

        # 确保协议明细表及物化视图存在
        for prot in protocols:
            await ensure_market_snapshot_table(pool, prot)

        # 逐区块、逐协议采集
        total_written = 0
        for blk in target_blocks:
            for prot in protocols:
                written = await collect_block_snapshot(
                    w3, pool, prot, blk, semaphore, dry_run=False
                )
                total_written += written

        # 所有区块写入完成后统一刷新物化视图
        for prot in protocols:
            await refresh_market_totals(pool, prot)

        logger.info("采集完成，共写入 %d 条 reserve 快照记录。", total_written)
    finally:
        await pool.close()  # type: ignore[union-attr]


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
