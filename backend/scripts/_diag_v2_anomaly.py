"""诊断 V2 liq_price_weth > eth_price_usd 异常行。"""
import asyncio
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import asyncpg
from aave_crawler.config import load_config


async def main():
    cfg = load_config("config.yaml")
    pool = await asyncpg.create_pool(cfg.postgres.dsn, min_size=1, max_size=3)

    # 1. 基本统计：V2 vs V3 异常行数量
    print("=== 异常行统计（liq_price_weth > eth_price_usd AND hf > 1）===")
    for proto in ("v2", "v3"):
        cnt = await pool.fetchval(
            """SELECT COUNT(*) FROM loan.position_snapshot_cache
               WHERE protocol=$1 AND health_factor > 1.0
                 AND liq_price_weth > eth_price_usd
                 AND eth_collateral_amount != 0""",
            proto,
        )
        print(f"  {proto}: {cnt}")

    # 2. 对 V2 异常行，检查 health_factor 与 reserves_json 是否一致
    print("\n=== V2 异常行详情（前5行）===")
    rows = await pool.fetch(
        """SELECT user_address, eth_price_usd, health_factor,
                  total_collateral_usd, total_debt_usd, liq_price_weth,
                  reserves_json
           FROM loan.position_snapshot_cache
           WHERE protocol='v2' AND health_factor > 1.0
             AND liq_price_weth > eth_price_usd
             AND eth_collateral_amount != 0
           LIMIT 5"""
    )
    import json as _json
    for r in rows:
        reserves = _json.loads(r["reserves_json"])
        col_usd_col = sum(
            Decimal(str(x.get("supply_usd", 0)))
            for x in reserves
            if x.get("use_as_collateral")
        )
        debt_usd_col = sum(Decimal(str(x.get("total_debt_usd", 0))) for x in reserves)
        hf_db = float(r["health_factor"])
        hf_re = float(col_usd_col / debt_usd_col) if debt_usd_col else 0

        # 检查 theta 加权后的 HF
        col_theta = sum(
            Decimal(str(x.get("supply_usd", 0)))
            * Decimal(str(x.get("liquidation_threshold", 0)))
            / Decimal(10000)
            for x in reserves
            if x.get("use_as_collateral")
        )
        hf_theta = float(col_theta / debt_usd_col) if debt_usd_col else 0

        print(f"\n  user: {r['user_address'][:10]}... eth={r['eth_price_usd']:.0f}")
        print(f"  hf_db={hf_db:.4f}  hf_re(no_theta)={hf_re:.4f}  hf_re(with_theta)={hf_theta:.4f}")
        print(f"  col_usd={col_usd_col:.2f}  debt_usd={debt_usd_col:.2f}  liq_price_weth={r['liq_price_weth']:.2f}")
        print(f"  Reserves:")
        for x in reserves:
            sym = x.get("symbol", "?")
            sup_usd = Decimal(str(x.get("supply_usd", 0)))
            debt_usd = Decimal(str(x.get("total_debt_usd", 0)))
            theta = x.get("liquidation_threshold", 0)
            use_col = x.get("use_as_collateral", False)
            if sup_usd > 0 or debt_usd > 0:
                print(f"    {sym}: col={sup_usd:.2f} debt={debt_usd:.2f} theta={theta} use_col={use_col}")

    await pool.close()


asyncio.run(main())
