#!/usr/bin/env python3
"""诊断：检查各表的数据量和liq_price分布"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncpg
import yaml


async def main():
    cfg = yaml.safe_load(open("config.yaml"))
    pg = cfg["postgres"]
    dsn = f"postgresql://{pg['user']}:{pg['password']}@{pg['host']}:{pg['port']}/{pg['database']}"
    pool = await asyncpg.create_pool(dsn)

    # Check columns of reserve_positions_collateral
    cols = await pool.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_schema='loan' AND table_name='aave_v3_eth_reserve_positions_collateral' ORDER BY ordinal_position"
    )
    print("aave_v3_eth_reserve_positions_collateral columns:")
    for c in cols:
        print(" ", c["column_name"])

    # Sample row
    r = await pool.fetchrow("SELECT * FROM loan.aave_v3_eth_reserve_positions_collateral LIMIT 1")
    if r:
        print("\nSample row keys:", list(r.keys()))
        print("Sample:", dict(r))

    # Count ETH symbol rows
    ETH_SYMBOLS = ['WETH', 'wstETH', 'rETH', 'cbETH', 'ETH', 'weETH', 'ezETH', 'rsETH']
    r2 = await pool.fetchrow(
        f"SELECT COUNT(DISTINCT user_address) FROM loan.aave_v3_eth_reserve_positions_collateral WHERE UPPER(symbol) = ANY(ARRAY{[s.upper() for s in ETH_SYMBOLS]}::text[]) AND usage_as_collateral_enabled = true AND supply_raw > 0"
    )
    print(f"\nUsers with ETH collateral: {r2['count']}")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
