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
    # 采集单个时间点（支持日期或 datetime）
    uv run python scripts/collect_market_snapshots.py -p v2 -p v3 --time 2024-06-01
    uv run python scripts/collect_market_snapshots.py -p v3 --time 2024-06-01T12:00:00Z
    # 采集时间区间（每 1 小时一个快照，默认）
    uv run python scripts/collect_market_snapshots.py -p v3 \\
        --from 2024-01-01 --to 2025-01-01
    # 每 6 小时一个快照
    uv run python scripts/collect_market_snapshots.py -p v3 \\
        --from 2024-01-01T00:00:00Z --to 2024-02-01T00:00:00Z --step-hours 6

选项
    -p / --protocol     v2 | v3，可多次指定（默认 v3）
    --block    N        指定单个区块号
    --time     DATETIME 指定单个时间点（YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SSZ）
    --from     DATETIME 起始时间（配合 --step-hours 生成时间序列）
    --to       DATETIME 结束时间（默认当前时间，配合 --from）
    --step-hours N      时间步长（小时，默认 1）
    --rpc-concurrency N RPC 并发上限（默认 12，archive 节点可适当提高）
    --dry-run           仅打印将要采集的区块/协议，不执行 RPC/写库
    --skip-existing     跳过数据库中已有数据的区块（默认行为：UPSERT 覆盖写入）
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

from aave_crawler.config import load_config  # noqa: E402
from aave_crawler.market_collector import (  # noqa: E402
    _block_at_timestamp,
    collect_block_snapshot,
    ensure_block_timestamps_table,
    ensure_market_snapshot_table,
    refresh_market_totals,
    upsert_block_timestamps,
)
from aave_crawler.rpc import build_web3  # noqa: E402
from web3 import AsyncWeb3  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def _parse_time(time_str: str) -> datetime:
    """将时间字符串解析为 UTC datetime。

    支持格式：
      YYYY-MM-DD             → 当天 UTC 0 点
      YYYY-MM-DDTHH:MM:SSZ   → UTC 精确时刻
      YYYY-MM-DDTHH:MM:SS+00:00
    """
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S+00:00", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(time_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    # 纯日期
    return datetime.strptime(time_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)


async def _ts_to_block(
    w3: AsyncWeb3,
    target_dt: datetime,
    pool: "asyncpg.Pool | None" = None,
    cache_window_minutes: int = 5,
) -> int:
    """将 UTC datetime 转换为最近区块号，优先查询缓存表。"""
    ts = int(target_dt.timestamp())

    if pool is not None:
        window = timedelta(minutes=cache_window_minutes)
        row = await pool.fetchrow(
            """
            SELECT block_number, block_timestamp
            FROM loan.eth_block_timestamps
            WHERE block_timestamp BETWEEN $1 AND $2
            ORDER BY ABS(EXTRACT(EPOCH FROM (block_timestamp - $3))) ASC
            LIMIT 1
            """,
            target_dt - window,
            target_dt + window,
            target_dt,
        )
        if row:
            logger.info(
                "%s → 区块 %d (缓存命中，block_ts=%s)",
                target_dt.isoformat(),
                row["block_number"],
                row["block_timestamp"].isoformat(),
            )
            return int(row["block_number"])

    block = await _block_at_timestamp(w3, ts, pool)
    block_meta = await w3.eth.get_block(block)
    block_ts = datetime.fromtimestamp(int(block_meta["timestamp"]), tz=timezone.utc)  # type: ignore[typeddict-item]
    logger.info(
        "%s (unix=%d) → 区块 %d (block_ts=%s)",
        target_dt.isoformat(),
        ts,
        block,
        block_ts.isoformat(),
    )

    if pool is not None:
        await upsert_block_timestamps(pool, [(block, block_ts)])

    return block


# ── CLI 入口 ──────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="采集 Aave V2/V3 历史大盘快照（eth_call@block）"
    )
    p.add_argument(
        "-p",
        "--protocol",
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
    group.add_argument(
        "--time",
        type=str,
        metavar="DATETIME",
        help="指定单个时间点（YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SSZ）",
    )
    group.add_argument(
        "--from",
        dest="from_time",
        type=str,
        metavar="DATETIME",
        help="起始时间（配合 --step-hours 生成时间序列）",
    )

    p.add_argument(
        "--to",
        dest="to_time",
        type=str,
        default="",
        metavar="DATETIME",
        help="结束时间（默认当前 UTC 时间，配合 --from）",
    )
    p.add_argument(
        "--step-hours",
        type=int,
        default=1,
        help="时间步长（小时，默认 1）",
    )
    p.add_argument(
        "--rpc-concurrency", type=int, default=12, help="RPC 并发上限（默认 12）"
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印将要采集的区块/协议，不执行 RPC/写库",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="跳过数据库中已有数据的区块（默认：UPSERT 覆盖写入）",
    )
    p.add_argument(
        "--config", type=str, default="", help="配置文件路径（默认 config.yaml）"
    )
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

        elif args.time:
            target_dt = await _parse_time(args.time)
            target_blocks = [await _ts_to_block(w3, target_dt, pool)]

        else:  # args.from_time
            start_dt = await _parse_time(args.from_time)
            end_dt = (
                await _parse_time(args.to_time)
                if args.to_time
                else datetime.now(tz=timezone.utc)
            )
            step = timedelta(hours=args.step_hours)

            time_points: list[datetime] = []
            cur = start_dt
            while cur <= end_dt:
                time_points.append(cur)
                cur += step

            logger.info(
                "时间区间 %s → %s，步长 %d 小时，共 %d 个时间点",
                start_dt.isoformat(),
                end_dt.isoformat(),
                args.step_hours,
                len(time_points),
            )

            # 串行将时间点转换为区块号（缓存命中时跳过 RPC 二分搜索）
            for tp in time_points:
                target_blocks.append(await _ts_to_block(w3, tp, pool))

        # 去重（多个时间点可能二分到同一区块）
        seen: set[int] = set()
        deduped_blocks: list[int] = []
        for blk in target_blocks:
            if blk not in seen:
                seen.add(blk)
                deduped_blocks.append(blk)
        if len(deduped_blocks) < len(target_blocks):
            logger.info(
                "去重后目标区块数：%d（原 %d）",
                len(deduped_blocks),
                len(target_blocks),
            )
        target_blocks = deduped_blocks

        logger.info("目标区块: %d 个", len(target_blocks))
        logger.info("目标协议: %s", protocols)

        if args.dry_run:
            logger.info("[dry-run] 模式，不执行 RPC 采集，退出。")
            for prot in protocols:
                for blk in target_blocks:
                    logger.info("[dry-run] protocol=%s  block=%d", prot, blk)
            return

        # 确保协议明细表及汇总表存在
        for prot in protocols:
            await ensure_market_snapshot_table(pool, prot)

        # 逐区块、逐协议采集
        total_written = 0
        total_skipped = 0
        for blk in target_blocks:
            for prot in protocols:
                if args.skip_existing:
                    table = f"loan.aave_{prot}_market_snapshots"
                    existing = await pool.fetchval(
                        f"SELECT COUNT(1) FROM {table} WHERE block_number = $1",
                        blk,
                    )
                    if existing:
                        logger.info(
                            "[%s] block=%d 已有 %d 条记录，跳过（--skip-existing）",
                            prot,
                            blk,
                            existing,
                        )
                        total_skipped += 1
                        continue
                written = await collect_block_snapshot(
                    w3, pool, prot, blk, semaphore, dry_run=False
                )
                total_written += written

        # 所有区块写入完成后统一滚动更新汇总表
        for prot in protocols:
            await refresh_market_totals(pool, prot)

        if total_skipped:
            logger.info("跳过已有区块：%d 个（--skip-existing）", total_skipped)
        logger.info("采集完成，共写入 %d 条 reserve 快照记录。", total_written)
    finally:
        await pool.close()  # type: ignore[union-attr]


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
