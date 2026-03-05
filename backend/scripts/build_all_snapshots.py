"""
build_all_snapshots.py
──────────────────────────────────────────────────────────────────────────────
从 aave.aave_history 全量构建 loan.position_snapshot_cache。

每个用户-交易对应一次 eth_call@block_number RPC 调用，拿到真实链上快照后写库。
已缓存的 tx 自动跳过（幂等），支持断点续跑。

运行方式
    cd backend
    uv run python scripts/build_all_snapshots.py -p v3 [选项]
    uv run python scripts/build_all_snapshots.py -p v2 -p v3 --workers 5

选项
    -p / --protocol     v2 | v3, 可多次指定（默认 v3）
    --workers   N       同时处理的用户数（默认 3）
    --rpc-concurrency N 全局 RPC 并发数（默认 10，公共节点建议 5-8）
    --batch     N       每个用户每批 RPC gather 数（默认 200）
    --limit     N       限制处理的用户总数（0 = 不限，默认 0）
    --user      ADDR    仅处理指定地址（调试用）
    --dry-run           不执行 RPC / 不写库，仅打印将要处理的用户和 tx 数
    --no-brief          跳过 AI-ContractParser brief 解析（速度更快）
    --config    PATH    配置文件路径（默认 config.yaml）
    --start     DATE    历史起始日期（默认 2020-01-01）
    --end       DATE    历史结束日期（默认 今天）
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aave_crawler.config import load_config  # noqa: E402
from aave_crawler.constants import WETH_ADDR as _WETH_ADDR  # noqa: E402
from aave_crawler.db import ensure_snapshot_cache_table  # noqa: E402
from aave_crawler.db import fetch_user_tx_history, upsert_snapshot_cache
from aave_crawler.rpc import EMPTY_POSITION  # noqa: E402
from aave_crawler.rpc import (build_web3, fetch_user_position_at_block,
                              get_all_reserve_tokens, get_contracts,
                              get_reserve_config)
from aave_crawler.tx_parser import parse_briefs_from_metas  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 从 aave_history 发现所有活跃用户 ─────────────────────────────────────────

_SQL_DISCOVER_USERS = """
SELECT DISTINCT lower(convert_from(user_address, 'UTF8')) AS addr
FROM aave.aave_history
WHERE protocol_version::text = $1
UNION
SELECT DISTINCT lower(convert_from(target_user_address, 'UTF8')) AS addr
FROM aave.aave_history
WHERE protocol_version::text = $1
  AND target_user_address IS NOT NULL
ORDER BY 1
"""

# 已缓存的 tx_hash 集合（用于跳过已处理的 tx）
_SQL_CACHED_TX_SET = """
SELECT tx_hash
FROM loan.position_snapshot_cache
WHERE user_address = lower($1)
  AND protocol     = $2
"""

# ─────────────────────────────────────────────────────────────────────────────


async def discover_users(pool: asyncpg.Pool, protocol: str) -> list[str]:
    """从 aave_history 查全部唯一用户地址（当前协议）。"""
    pv = protocol[-1]  # 'v3' → '3', 'v2' → '2'
    rows = await pool.fetch(_SQL_DISCOVER_USERS, pv)
    addrs = [r["addr"] for r in rows if r["addr"]]
    logger.info("[discover] protocol=%s  用户总数: %d", protocol, len(addrs))
    return addrs


async def get_cached_tx_set(
    pool: asyncpg.Pool,
    user_address: str,
    protocol: str,
) -> set[str]:
    """获取某用户已缓存的 tx_hash 集合（用于快速跳过）。"""
    rows = await pool.fetch(_SQL_CACHED_TX_SET, user_address, protocol)
    return {r["tx_hash"] for r in rows}


async def process_user(
    pool: asyncpg.Pool,
    w3,
    user_address: str,
    protocol: str,
    reserve_tokens,
    reserve_configs,
    global_rpc_sem: asyncio.Semaphore,
    from_dt: datetime,
    to_dt: datetime,
    batch_size: int,
    dry_run: bool,
    no_brief: bool,
) -> tuple[int, int]:
    """
    处理单个用户的全量快照构建。

    Returns:
        (rpc_count, write_count)  本次实际发出的 RPC 数 和 写入数
    """
    # 1. 从 aave_history 拿 tx 列表（快，有索引）
    tx_rows = await fetch_user_tx_history(pool, user_address, protocol, from_dt, to_dt)
    if not tx_rows:
        return 0, 0

    # 去重（同 block 只保留一条）
    seen_blocks: dict[int, dict] = {}
    for r in tx_rows:
        bn = r["block_number"]
        if bn not in seen_blocks:
            seen_blocks[bn] = dict(r)
    deduped = sorted(seen_blocks.values(), key=lambda x: x["block_number"])

    # 2. 查哪些 tx 已缓存
    cached_set = await get_cached_tx_set(pool, user_address, protocol)
    miss_txs = [t for t in deduped if t["tx_hash"] not in cached_set]

    if not miss_txs:
        return 0, 0  # 全部已缓存，跳过

    if dry_run:
        logger.info(
            "[dry-run] %s  total=%d  miss=%d  cached=%d",
            user_address[:12], len(deduped), len(miss_txs), len(cached_set),
        )
        return 0, 0

    contracts = get_contracts(protocol)
    total_written = 0

    # 3. 分批 RPC + 写库（流水线：RPC 完成立刻写，不等下一批）
    for batch_start in range(0, len(miss_txs), batch_size):
        batch = miss_txs[batch_start: batch_start + batch_size]

        tasks = [
            fetch_user_position_at_block(
                w3, user_address, reserve_tokens, reserve_configs,
                t["block_number"], global_rpc_sem, contracts,
            )
            for t in batch
        ]
        results = await asyncio.gather(*tasks)

        # 过滤有效结果
        positions = []
        metas = []
        for t, res in zip(batch, results):
            if res is None or res is EMPTY_POSITION:
                continue
            pos, eth_price_raw = res
            eth_price_dec = Decimal(eth_price_raw) / Decimal(10 ** 8)
            _prices = {
                r.token_address.lower(): Decimal(r.price_raw) / Decimal(10 ** 8)
                for r in pos.reserves
            }
            # WETH 可能因全额取出后余额为 0 而不在 reserves 里，
            # 天然用 eth_price_usd 作为 WETH / ETH 价格
            _prices.setdefault(_WETH_ADDR, eth_price_dec)
            positions.append(pos)
            metas.append({
                "tx_hash":         t["tx_hash"],
                "block_timestamp": t["block_timestamp"],
                "eth_price_usd":   eth_price_dec,
                "protocol":        protocol,
                "prices":          _prices,
            })

        if not positions:
            continue

        # brief 解析（可关闭以提速）
        if no_brief:
            briefs = [""] * len(positions)
        else:
            briefs = await parse_briefs_from_metas(metas)

        written = await upsert_snapshot_cache(pool, positions, metas, briefs=briefs)
        total_written += written

    return len(miss_txs), total_written


# ── 全局进度统计 ──────────────────────────────────────────────────────────────
class _Stats:
    def __init__(self) -> None:
        self.users_done   = 0
        self.users_skipped = 0
        self.users_failed  = 0
        self.rpc_total    = 0
        self.write_total  = 0
        self.t_start      = time.monotonic()

    def report(self, total_users: int) -> None:
        elapsed = time.monotonic() - self.t_start
        rate = self.rpc_total / elapsed if elapsed > 0 else 0
        logger.info(
            "进度 %d/%d  skip=%d  fail=%d  RPC=%d  写入=%d  "
            "速率=%.1f RPC/s  已用时=%.0fs",
            self.users_done + self.users_skipped + self.users_failed,
            total_users,
            self.users_skipped,
            self.users_failed,
            self.rpc_total,
            self.write_total,
            rate,
            elapsed,
        )


# ─────────────────────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    dsn = cfg.postgres.dsn

    from_dt = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    to_dt   = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)

    # DB 连接池
    pool = await asyncpg.create_pool(
        dsn,
        min_size=args.workers + 2,
        max_size=args.workers + 8,
    )

    # 确保表存在
    await ensure_snapshot_cache_table(pool)

    # Web3（多节点后备）
    w3 = await build_web3(cfg)

    # 全局 RPC 并发锁（所有用户共享，最大化节点利用率）
    global_rpc_sem = asyncio.Semaphore(args.rpc_concurrency)

    stats = _Stats()

    for protocol in args.protocol:
        logger.info("═══ 开始处理 protocol=%s ═══", protocol)
        pv = protocol[-1]  # '3' or '2'

        # ── 一次性加载 reserve_tokens / reserve_configs（全协议共用）─────────
        logger.info("[%s] 加载 reserve_tokens / configs ...", protocol)
        contracts    = get_contracts(protocol)
        reserve_tokens = await get_all_reserve_tokens(w3, contracts)
        reserve_configs: dict = {}
        for rt in reserve_tokens:
            cfg_item = await get_reserve_config(w3, rt.token_address, contracts)
            if cfg_item:
                reserve_configs[rt.token_address] = cfg_item
        logger.info(
            "[%s] reserve_tokens=%d  reserve_configs=%d",
            protocol, len(reserve_tokens), len(reserve_configs),
        )

        # ── 发现用户 ─────────────────────────────────────────────────────────
        if args.user:
            users = [args.user.lower()]
        else:
            users = await discover_users(pool, protocol)
            if args.limit:
                users = users[: args.limit]

        total_users = len(users)

        # ── 并发限流（USER_CONCURRENCY）──────────────────────────────────────
        user_sem = asyncio.Semaphore(args.workers)

        async def _handle_user(addr: str) -> None:
            async with user_sem:
                try:
                    rpc_cnt, write_cnt = await process_user(
                        pool      = pool,
                        w3        = w3,
                        user_address  = addr,
                        protocol      = protocol,
                        reserve_tokens= reserve_tokens,
                        reserve_configs=reserve_configs,
                        global_rpc_sem= global_rpc_sem,
                        from_dt   = from_dt,
                        to_dt     = to_dt,
                        batch_size= args.batch,
                        dry_run   = args.dry_run,
                        no_brief  = args.no_brief,
                    )
                    if rpc_cnt == 0:
                        stats.users_skipped += 1
                    else:
                        stats.users_done   += 1
                        stats.rpc_total    += rpc_cnt
                        stats.write_total  += write_cnt
                except Exception as exc:
                    stats.users_failed += 1
                    logger.warning("[%s] 处理失败 user=%s: %s", protocol, addr[:12], exc)

        # 并发启动所有用户任务（user_sem 控制同时运行数）
        tasks = [asyncio.create_task(_handle_user(addr)) for addr in users]

        # 每 100 个任务完成打印一次进度
        done_count = 0
        for coro in asyncio.as_completed(tasks):
            await coro
            done_count += 1
            if done_count % 100 == 0:
                stats.report(total_users)

        stats.report(total_users)
        logger.info("═══ protocol=%s 完成 ═══", protocol)

    await pool.close()
    logger.info("全部完成。写入: %d  RPC调用: %d", stats.write_total, stats.rpc_total)


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(
        description="从 aave_history 全量构建 position_snapshot_cache"
    )
    parser.add_argument("-p", "--protocol", action="append", default=[],
                        choices=["v2", "v3"],
                        help="协议版本（可多次指定，默认 v3）")
    parser.add_argument("--workers",         type=int, default=3,
                        help="同时处理的用户数（默认 3）")
    parser.add_argument("--rpc-concurrency", type=int, default=10,
                        help="全局 RPC 并发数（默认 10）")
    parser.add_argument("--batch",           type=int, default=200,
                        help="每用户每批 RPC gather 数（默认 200）")
    parser.add_argument("--limit",           type=int, default=0,
                        help="最多处理用户数（0 = 全量）")
    parser.add_argument("--user",            type=str, default="",
                        help="仅处理指定地址（调试）")
    parser.add_argument("--dry-run",         action="store_true",
                        help="不执行 RPC / 不写库")
    parser.add_argument("--no-brief",        action="store_true",
                        help="跳过 AI-ContractParser brief 解析")
    parser.add_argument("--config",          default="config.yaml",
                        help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--start",           default="2020-01-01",
                        help="历史起始日期 YYYY-MM-DD（默认 2020-01-01）")
    parser.add_argument("--end",             default=today,
                        help=f"历史结束日期 YYYY-MM-DD（默认 {today}）")

    args = parser.parse_args()
    if not args.protocol:
        args.protocol = ["v3"]

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
