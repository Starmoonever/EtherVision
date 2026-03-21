"""
recalc_liq_price_snapshot.py
────────────────────────────
修复 aave_position_snapshots 表中因旧公式（仅取第一个 ETH 系抑品、
未考虑 ETH 系债务对冲）导致的错误 liq_price 值。

旧公式问题：
  1. 分母只用第一个 ETH 系抵押品的 amount×θ，忽略多 token 情况（wstETH+cbETH 等）
  2. 未从有效债务中扣除 ETH 系债务，导致 "ETH 抵押 + ETH 借贷" 的对冲仓位
     产生错误的（甚至高于当前市价的）清算价

新公式（与修复后的 db._calc_liq_price 完全对应）：
  设 P_now = ETH 当前价格（eth_price_usd 列）
  eth_col_theta = Σ (ETH系抵押 amount_i × P_now × θ_i)
  eth_debt_usd  = Σ (ETH系负债 amount_i × P_now)
  c_fixed       = Σ (非ETH抵押 USD × θ_j)
  d_fixed       = Σ (非ETH负债 USD)
  denom         = eth_col_theta - eth_debt_usd
  numer         = d_fixed - c_fixed

  denom ≤ 0  → liq_price = 0  (净空 ETH 或完全对冲，无下跌清算风险)
  denom > 0  → liq_price = (numer / denom) × P_now  (可为 0 若 numer ≤ 0)

所有数据均来自 reserves_json 列（JSONB 数组，每个元素含 symbol、
supply_raw、stable_debt_raw、variable_debt_raw、price_usd、
decimals、use_as_collateral、liquidation_threshold），
无需访问链上 RPC，可批量原地修复。

用法：
    uv run python scripts/recalc_liq_price_snapshot.py [--protocol v3] [--dry-run] [--batch 1000]
    uv run python scripts/recalc_liq_price_snapshot.py --protocol v3 --address 0xABCD...
    uv run python scripts/recalc_liq_price_snapshot.py --protocol v3 --fix-only-positive
"""

import argparse
import asyncio
import json
import logging
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import asyncpg

# ── 使脚本从任意 cwd 运行 ─────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aave_crawler.config import load_config  # noqa: E402
from aave_crawler.constants import ETH_SYMBOLS, LIQ_PRICE_CAP  # noqa: E402
from aave_crawler.db import create_pool  # noqa: E402
from aave_crawler.db import ensure_snapshot_cache_table  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_LIQ_PRICE_CAP: Decimal = LIQ_PRICE_CAP  # from aave_crawler/constants.py
_ETH_SYMBOLS: frozenset[str] = frozenset(s.upper() for s in ETH_SYMBOLS)


def _dec(v: object) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _raw_to_dec(raw: int | str, decimals: int) -> Decimal:
    r = _dec(raw)
    if r == 0 or decimals < 0:
        return Decimal("0")
    return r / Decimal(10**decimals)


def recalc_liq_price(
    reserves_json: list[dict],
    eth_price_usd_col: Decimal,
    total_collateral_usd: Decimal,
    liq_threshold_ratio: Decimal,
) -> Decimal:
    """
    从 reserves_json 重新计算 liq_price（ETH 下跌触发清算价）。
    逻辑与 aave_crawler/db.py 中的 _calc_liq_price 严格对应。

    reserves_json 结构（每个元素）：
        symbol               : str
        decimals             : int
        price_usd            : str  (8位精度 USD，扫描时刻 Oracle 价格，含 LST 转换率)
        supply_raw           : str  (原始整数)
        stable_debt_raw      : str
        variable_debt_raw    : str
        use_as_collateral    : bool
        liquidation_threshold: int  (basis points, e.g. 9500 = 95%)

    eth_price_usd_col：DB 中 eth_price_usd 列的值，统一使用 WETH 价格作为 P_now。
    total_collateral_usd：DB 的 total_collateral_usd 列（来自 getUserAccountData，历史正确值）。
    liq_threshold_ratio：DB 的 liq_threshold 列（0.0~1.0，来自 getUserAccountData，历史正确值）。
                         只有 ETH 系资产的 θ 用 reserves 里的值（长期稳定）；
                         非 ETH 资产的 θ 加权值由 total_col_theta − eth_col_theta 推导，
                         完全绕过因治理更新而失效的 reserves_json.liquidation_threshold。
    """
    if not reserves_json:
        return Decimal("0")

    # P_now：统一使用 WETH 价格（eth_price_usd_col 列），不再从 reserves 取 LST 价格
    eth_price_now = eth_price_usd_col
    if eth_price_now is None or eth_price_now <= 0:
        return Decimal("0")

    eth_col_theta_usd = Decimal(
        "0"
    )  # Σ ETH系抵押 amount×price×θ（ETH资产θ长期稳定，可信）
    eth_debt_usd = Decimal("0")  # Σ ETH系负债 amount×price
    d_fixed = Decimal("0")  # Σ 非ETH负债 USD

    for r in reserves_json:
        symbol = r.get("symbol", "").upper()
        decimals = int(r.get("decimals", 18))
        theta = _dec(r.get("liquidation_threshold", 0)) / Decimal(10000)
        use_col = bool(r.get("use_as_collateral", False))

        supply_dec = _raw_to_dec(r.get("supply_raw", 0), decimals)
        debt_dec = _raw_to_dec(r.get("stable_debt_raw", 0), decimals) + _raw_to_dec(
            r.get("variable_debt_raw", 0), decimals
        )
        price_usd = _dec(r.get("price_usd", 0))

        if symbol in _ETH_SYMBOLS:
            if supply_dec > 0 and use_col:
                eth_col_theta_usd += supply_dec * price_usd * theta
            if debt_dec > 0:
                eth_debt_usd += debt_dec * price_usd
        else:
            if debt_dec > 0:
                d_fixed += debt_dec * price_usd

    if eth_col_theta_usd == 0:
        return Decimal("0")

    # 使用 getUserAccountData 聚合 LT（历史区块正确值）推导非 ETH 抵押的 θ 加权安全垫：
    #   total_col_theta = total_collateral_usd × liq_threshold_ratio
    #   c_fixed = total_col_theta − eth_col_theta_usd
    # 完全绕过 reserves_json 里因治理更新而失效的每资产 θ 值
    total_col_theta_usd = total_collateral_usd * liq_threshold_ratio
    c_fixed = max(Decimal("0"), total_col_theta_usd - eth_col_theta_usd)

    denom = eth_col_theta_usd - eth_debt_usd
    if denom <= 0:
        return Decimal("0")

    numer = d_fixed - c_fixed
    liq_price_raw = numer / denom * eth_price_now
    if liq_price_raw <= 0:
        return Decimal("0")

    return min(liq_price_raw, _LIQ_PRICE_CAP)


async def recalc_all(
    pool: asyncpg.Pool,
    *,
    protocol: str | None,
    address: str | None,
    dry_run: bool,
    batch_size: int,
    fix_only_positive: bool,
) -> None:
    """
    遍历 aave_position_snapshots 全部行，重新计算 liq_price 并 UPDATE。

    --fix-only-positive：只更新当前 liq_price > 0 但新值 = 0 的行（最快速修复已知 bug）
    """
    # ── 构建 WHERE 条件 ───────────────────────────────────────────────────────
    conditions = []
    params: list = []
    if protocol:
        params.append(protocol)
        conditions.append(f"protocol = ${len(params)}")
    if address:
        params.append(address.lower())
        conditions.append(f"user_address = ${len(params)}")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    count_q = f"SELECT COUNT(*) FROM loan.aave_position_snapshots {where}"
    total: int = await pool.fetchval(count_q, *params)
    logger.info("待处理行数: %d  (protocol=%s, address=%s)", total, protocol, address)

    offset = 0
    updated = 0
    zeroed = 0
    skipped = 0

    while offset < total:
        fetch_q = (
            f"SELECT id, liq_price, eth_price_usd, reserves_json, "
            f"total_collateral_usd, liq_threshold "
            f"FROM loan.aave_position_snapshots {where} "
            f"ORDER BY id LIMIT {batch_size} OFFSET {offset}"
        )
        rows = await pool.fetch(fetch_q, *params)
        if not rows:
            break

        update_args: list[
            tuple[Decimal, Decimal, int]
        ] = []  # (liq_price, liq_price_weth, id)
        for row in rows:
            old_liq = _dec(row["liq_price"])
            p_now = _dec(row["eth_price_usd"])
            try:
                reserves = (
                    json.loads(row["reserves_json"])
                    if isinstance(row["reserves_json"], str)
                    else row["reserves_json"]
                )
            except Exception:
                reserves = []

            new_liq = recalc_liq_price(
                reserves,
                p_now,
                _dec(row["total_collateral_usd"]),
                _dec(row["liq_threshold"]),
            )

            if new_liq == old_liq:
                skipped += 1
                continue

            if fix_only_positive and not (old_liq > 0 and new_liq == 0):
                skipped += 1
                continue

            # liq_price 和 liq_price_weth 使用相同的值（都基于 WETH 价格计算）
            update_args.append((new_liq, new_liq, row["id"]))
            if new_liq == 0:
                zeroed += 1
            updated += 1

            logger.debug(
                "id=%d  old_liq=%s  new_liq=%s  (eth_price=%s)",
                row["id"],
                old_liq,
                new_liq,
                p_now,
            )

        if update_args and not dry_run:
            async with pool.acquire() as conn:
                await conn.executemany(
                    "UPDATE loan.aave_position_snapshots "
                    "SET liq_price = $1, liq_price_weth = $2 WHERE id = $3",
                    update_args,
                )

        offset += len(rows)
        logger.info(
            "进度 %d/%d  已更新 %d（其中归零 %d）  跳过 %d",
            min(offset, total),
            total,
            updated,
            zeroed,
            skipped,
        )

    if dry_run:
        logger.info(
            "[dry-run] 共检测到 %d 行需要更新（其中归零 %d 行），未写库。",
            updated,
            zeroed,
        )
    else:
        logger.info(
            "完成！共更新 %d 行（其中归零 %d 行），跳过 %d 行（值未变）。",
            updated,
            zeroed,
            skipped,
        )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="重新计算 aave_position_snapshots.liq_price"
    )
    p.add_argument(
        "--protocol",
        choices=["v2", "v3"],
        default=None,
        help="仅处理指定版本（默认全部）",
    )
    p.add_argument("--address", default=None, help="仅处理单个用户地址（0x...）")
    p.add_argument("--dry-run", action="store_true", help="仅统计需更新行数，不写库")
    p.add_argument(
        "--batch",
        type=int,
        default=500,
        dest="batch",
        help="每批处理的行数（默认 500）",
    )
    p.add_argument(
        "--fix-only-positive",
        action="store_true",
        help="只修复 liq_price > 0 但新公式结果 = 0 的行（最快速修复已知 bug）",
    )
    return p.parse_args()


async def _main() -> None:
    args = _parse_args()
    cfg = load_config()  # 自动查找 backend/config.yaml
    pool = await create_pool(cfg.postgres)
    try:
        # 确保 liq_price_weth 等新列已存在（幂等）
        await ensure_snapshot_cache_table(pool)
        await recalc_all(
            pool,
            protocol=args.protocol,
            address=args.address,
            dry_run=args.dry_run,
            batch_size=args.batch,
            fix_only_positive=args.fix_only_positive,
        )
    finally:
        await pool.close()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
