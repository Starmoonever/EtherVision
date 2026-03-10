"""
临时诊断脚本：检查并清理 position_snapshot_cache 中 eth_price_usd 异常值。
运行：uv run python scripts/_debug_eth_price.py [--fix]
  --fix   实际执行 DELETE（默认仅诊断，不修改数据）
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402
from aave_crawler.config import load_config  # noqa: E402

ANOMALY = "10000000000.00000000"
DRY_RUN = "--fix" not in sys.argv


async def main() -> None:
    cfg = load_config()
    pool = await asyncpg.create_pool(dsn=cfg.postgres.dsn)

    # 1. 总数 + 协议分布
    cnt = await pool.fetchval(
        f"SELECT COUNT(*) FROM loan.position_snapshot_cache WHERE eth_price_usd = {ANOMALY}"
    )
    print(f"异常行总数: {cnt}")

    proto_rows = await pool.fetch(
        f"SELECT protocol, COUNT(*) AS n FROM loan.position_snapshot_cache"
        f" WHERE eth_price_usd = {ANOMALY} GROUP BY protocol ORDER BY protocol"
    )
    for r in proto_rows:
        print(f"  protocol={r['protocol']}: {r['n']} 行")

    # 2. 区块 / 时间范围
    rng = await pool.fetchrow(
        f"SELECT MIN(block_number) AS min_blk, MAX(block_number) AS max_blk,"
        f"       MIN(cached_at)    AS min_ts,  MAX(cached_at)    AS max_ts"
        f" FROM loan.position_snapshot_cache WHERE eth_price_usd = {ANOMALY}"
    )
    print(f"\nblock 范围: {rng['min_blk']} ~ {rng['max_blk']}")
    print(f"cached_at 范围: {rng['min_ts']} ~ {rng['max_ts']}")

    # 3. 样本行
    samples = await pool.fetch(
        f"SELECT user_address, protocol, block_number, cached_at,"
        f"       total_collateral_usd, total_debt_usd, health_factor, eth_price_usd"
        f" FROM loan.position_snapshot_cache"
        f" WHERE eth_price_usd = {ANOMALY}"
        f" ORDER BY block_number LIMIT 8"
    )
    print("\n样本行:")
    for r in samples:
        print(dict(r))

    # 4. 删除异常行
    if DRY_RUN:
        print(f"\n[dry-run] 添加 --fix 参数以实际删除 {cnt} 条异常行。")
    else:
        await pool.execute(
            f"DELETE FROM loan.position_snapshot_cache WHERE eth_price_usd = {ANOMALY}"
        )
        print(
            f"\n已删除 {cnt} 条异常行。下次运行 build_all_snapshots.py 会自动重建这些缓存。"
        )

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
