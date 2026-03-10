"""
backfill_snapshot_fields.py
────────────────────────────────────────────────────────────────────────────
为 loan.position_snapshot_cache 中旧行（缺少新字段的行）批量填充：
    - eth_collateral_amount  ETH 系抵押品合计数量
    - eth_collateral_usd     ETH 系抵押品合计 USD
    - weth_debt_amount       ETH 系负债合计数量
    - weth_debt_usd          ETH 系负债合计 USD
    - liq_price_rise         ETH 上涨清算触发价

所有计算均基于行内现有的 reserves_json + eth_price_usd，无需任何 RPC 调用。
幂等：对全部行重算，可安全重复运行。

用法：
    uv run python scripts/backfill_snapshot_fields.py
    uv run python scripts/backfill_snapshot_fields.py --batch 500 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from decimal import Decimal

import asyncpg
from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aave_crawler.config import load_config
from aave_crawler.constants import ETH_SYMBOLS as _ETH_SYMBOLS
from aave_crawler.constants import LIQ_PRICE_CAP as _LIQ_PRICE_CAP

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ── 纯 Python 计算（镜像 db.py 中的函数，直接操作 JSONB dict）────────────────


def _calc_from_reserves(
    reserves: list[dict],
    eth_price_usd: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """
    从 reserves_json 列表计算 5 个新字段。

    返回：(eth_col_amount, eth_col_usd, weth_debt_amount, weth_debt_usd, liq_price_rise)
    """
    eth_col_amount = Decimal("0")
    eth_col_usd = Decimal("0")
    weth_debt_raw = Decimal("0")
    weth_debt_usd = Decimal("0")

    # liq_price_rise 所需中间量
    eth_debt_usd_sum = Decimal("0")
    eth_col_theta_usd_sum = Decimal("0")
    d_fixed = Decimal("0")
    c_fixed = Decimal("0")

    for r in reserves:
        symbol = r["symbol"].upper()
        decimals = int(r["decimals"])
        price = Decimal(str(r["price_usd"]))
        sup_raw = int(r["supply_raw"])
        st_raw = int(r["stable_debt_raw"])
        var_raw = int(r["variable_debt_raw"])
        use_col = bool(r["use_as_collateral"])
        liq_thr = Decimal(str(r["liquidation_threshold"])) / Decimal(10000)

        sup_amt = Decimal(sup_raw) / Decimal(10**decimals)
        debt_amt = Decimal(st_raw + var_raw) / Decimal(10**decimals)

        if symbol in _ETH_SYMBOLS:
            # 抵押品端
            if sup_raw > 0 and use_col:
                eth_col_amount += sup_amt
                eth_col_usd += sup_amt * price
                eth_col_theta_usd_sum += sup_amt * price * liq_thr
            # 负债端
            if st_raw + var_raw > 0:
                weth_debt_raw += Decimal(st_raw + var_raw)
                weth_debt_usd += debt_amt * price
                eth_debt_usd_sum += debt_amt * price
        else:
            # 非 ETH 抵押品
            if sup_raw > 0 and use_col:
                c_fixed += sup_amt * price * liq_thr
            # 非 ETH 负债
            if st_raw + var_raw > 0:
                d_fixed += debt_amt * price

    # weth_debt_amount：原始 wei → ETH 数量（WETH 系均 18 位）
    weth_debt_amount = weth_debt_raw / Decimal(10**18)

    # liq_price_rise
    if eth_debt_usd_sum == 0 or eth_price_usd == 0:
        liq_price_rise = Decimal("0")
    else:
        denom = eth_col_theta_usd_sum - eth_debt_usd_sum
        if denom >= 0:
            liq_price_rise = Decimal("0")
        else:
            numerator = d_fixed - c_fixed
            liq_price_rise = eth_price_usd * numerator / denom
            if liq_price_rise <= 0 or liq_price_rise < eth_price_usd:
                liq_price_rise = Decimal("0")
            else:
                liq_price_rise = min(liq_price_rise, _LIQ_PRICE_CAP)

    return eth_col_amount, eth_col_usd, weth_debt_amount, weth_debt_usd, liq_price_rise


# ── 主逻辑 ─────────────────────────────────────────────────────────────────────

_SQL_FETCH = """
SELECT id, reserves_json, eth_price_usd
FROM loan.position_snapshot_cache
ORDER BY id
"""

_SQL_UPDATE = """
UPDATE loan.position_snapshot_cache SET
    eth_collateral_amount = $1,
    eth_collateral_usd    = $2,
    weth_debt_amount      = $3,
    weth_debt_usd         = $4,
    liq_price_rise        = $5
WHERE id = $6
"""


async def backfill(batch_size: int, dry_run: bool) -> None:
    cfg = load_config()
    pool = await asyncpg.create_pool(
        host=cfg.postgres.host,
        port=cfg.postgres.port,
        user=cfg.postgres.user,
        password=cfg.postgres.password,
        database=cfg.postgres.database,
        min_size=2,
        max_size=4,
    )

    # 先统计总行数
    total: int = await pool.fetchval(
        "SELECT COUNT(*) FROM loan.position_snapshot_cache"
    )
    logger.info("共 %d 行需要回填", total)

    if total == 0:
        logger.info("表为空，无需操作")
        await pool.close()
        return

    updated = 0
    skipped = 0  # reserves_json 为空的行

    # 流式读取，分批 UPDATE（asyncpg cursor 必须在事务内）
    batch: list[tuple] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            with tqdm(total=total, unit="row", desc="回填") as pbar:
                async for row in conn.cursor(_SQL_FETCH):
                    raw_json = row["reserves_json"]
                    if isinstance(raw_json, str):
                        reserves = json.loads(raw_json)
                    else:
                        reserves = raw_json  # asyncpg 自动解析 JSONB → list

                    if not reserves:
                        skipped += 1
                        pbar.update(1)
                        continue

                    eth_price = Decimal(str(row["eth_price_usd"]))
                    ec_amt, ec_usd, wd_amt, wd_usd, lpr = _calc_from_reserves(
                        reserves, eth_price
                    )

                    batch.append(
                        (
                            ec_amt,
                            ec_usd,
                            wd_amt,
                            wd_usd,
                            lpr,
                            row["id"],
                        )
                    )
                    pbar.update(1)

                    if len(batch) >= batch_size:
                        if not dry_run:
                            async with pool.acquire() as wconn:
                                await wconn.executemany(_SQL_UPDATE, batch)
                        updated += len(batch)
                        batch.clear()

    # 尾批
    if batch:
        if not dry_run:
            async with pool.acquire() as wconn:
                await wconn.executemany(_SQL_UPDATE, batch)
        updated += len(batch)

    await pool.close()

    label = "[DRY-RUN] " if dry_run else ""
    logger.info(
        "%s回填完成：更新 %d 行，跳过（空 reserves）%d 行",
        label,
        updated,
        skipped,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="回填 position_snapshot_cache 新字段")
    parser.add_argument(
        "--batch", type=int, default=200, help="每批 UPDATE 行数（默认 200）"
    )
    parser.add_argument("--dry-run", action="store_true", help="只计算，不写入数据库")
    args = parser.parse_args()

    asyncio.run(backfill(batch_size=args.batch, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
