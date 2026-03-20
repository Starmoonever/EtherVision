"""
提取 Compound v3 各市场活跃用户地址，保存到 derived_users/compound_v3_{market}_users.csv。
用法：
    uv run scripts/compound/extract_active_users.py --market usdc
"""

import argparse
import asyncpg
import csv
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
from compound_crawler.config import load_config

DB_DSN = os.getenv("PG_DSN", "postgresql://user:pass@localhost:5432/defi")

MARKET_ADDRESS = {
    "usdc": "0xc3d688b66703497daa19211eedff47f25384cdc3",
    "usdt": "0xA17581A9E3356d9A858b789D68B4d866e593aE94",
    "weth": "0x3Afdc9BCA9213A35503b077a6072F3D0d5AB0840",
}


async def extract_active_users(market: str, dsn: str | None = None):
    market_addr = MARKET_ADDRESS.get(market.lower())
    if not market_addr:
        raise ValueError(f"未知市场: {market}")
    if dsn is None:
        config = load_config()
        dsn = config.postgres.dsn
    # asyncpg 要求 address 用 bytes 传递
    market_addr_bytes = bytes.fromhex(market_addr.lower().removeprefix("0x"))
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT DISTINCT from_address
            FROM compound.compound_history
            WHERE version = '3' AND to_address = $1
            """,
            market_addr_bytes,
        )
        users = [r["from_address"] for r in rows]
    finally:
        await conn.close()
    out_path = f"derived_users/compound_v3_{market.lower()}_users.csv"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["address"])
        for addr in users:
            writer.writerow([addr])
    print(f"写入 {len(users)} 个用户到 {out_path}")


if __name__ == "__main__":
    import asyncio

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--market", required=True, choices=["usdc", "usdt", "weth"], help="市场名称"
    )
    parser.add_argument(
        "--dsn", default=None, help="PostgreSQL DSN（如不指定则自动读取 config.yaml）"
    )
    args = parser.parse_args()
    asyncio.run(extract_active_users(args.market, args.dsn))
