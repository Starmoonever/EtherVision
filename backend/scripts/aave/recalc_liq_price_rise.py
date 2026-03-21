"""
recalc_liq_price_rise.py
─────────────────────────────────────────────────────────────────────────────
从数据库读取借贷端仓位数据，使用正确公式重算 liq_price_rise，批量写回 DB。
无需重爬，RPC 用量极少（仅 getReserveConfigurationData × N_assets，约 15 次）。

运行方式
    cd backend
    uv run python scripts/recalc_liq_price_rise.py [-p v3_borrow] [--dry-run]

公式（HF = 1 时触发，设 x = P_rise / P_now）：
    eth_col_theta × x + C_fixed = eth_debt × x + D_fixed
    => x = (D_fixed - C_fixed) / (eth_col_theta - eth_debt)
    => P_rise = P_now × x

其中：
    eth_debt       = Σ(ETH系负债 USD)
    eth_col_theta  = Σ(ETH系抵押品USD × liq_threshold)
    C_fixed        = Σ(非ETH抵押品USD × liq_threshold)
    D_fixed        = Σ(非ETH负债 USD)
    P_now          = 扫描时存储的 ETH 价格（来自 reserve_positions）

denom = eth_col_theta - eth_debt
    denom >= 0  → ETH 多头净敞口，ETH 上涨有益 → liq_price_rise = 0
    denom < 0   → ETH 空头净敞口，ETH 上涨有害 → liq_price_rise > 0
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
from aave_crawler.constants import ETH_SYMBOLS as _ETH_SYMBOLS  # noqa: E402
from aave_crawler.constants import LIQ_PRICE_CAP as _LIQ_PRICE_CAP  # noqa: E402
from aave_crawler.db import get_tables  # noqa: E402
from aave_crawler.rpc import build_web3  # noqa: E402
from aave_crawler.rpc import get_all_reserve_tokens, get_contracts, get_reserve_config  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 核心计算（完全基于 DB 存储数据）
# ─────────────────────────────────────────────────────────────────────────────


def _recalc_rise(
    reserves: list[dict],
    liq_thresholds: dict[str, Decimal],  # token_address（小写）→ threshold (0~1)
) -> Decimal:
    """
    用 DB 数据重算 liq_price_rise。

    reserves 每项字段（对应 reserve_positions 表列）：
        token_address, symbol, price_usd, supply_usd,
        supply_raw, stable_debt_raw, variable_debt_raw,
        total_debt_usd, use_as_collateral, decimals
    """
    # 找第一个 ETH 系资产的价格作为 P_now
    eth_price_now: Decimal | None = None
    for r in reserves:
        if r["symbol"].upper() in _ETH_SYMBOLS and Decimal(str(r["price_usd"])) > 0:
            eth_price_now = Decimal(str(r["price_usd"]))
            break
    if eth_price_now is None or eth_price_now == 0:
        return Decimal("0")

    eth_debt_usd_sum = Decimal("0")
    eth_col_theta_usd_sum = Decimal("0")
    d_fixed = Decimal("0")
    c_fixed = Decimal("0")

    for r in reserves:
        symbol_upper = r["symbol"].upper()
        supply_raw = int(r["supply_raw"])
        debt_raw = int(r["stable_debt_raw"]) + int(r["variable_debt_raw"])
        supply_usd = Decimal(str(r["supply_usd"]))
        debt_usd = Decimal(str(r["total_debt_usd"]))
        threshold = liq_thresholds.get(r["token_address"].lower(), Decimal("0"))

        if symbol_upper in _ETH_SYMBOLS:
            if debt_raw > 0:
                eth_debt_usd_sum += debt_usd
            if supply_raw > 0 and r["use_as_collateral"] and threshold > 0:
                eth_col_theta_usd_sum += supply_usd * threshold
        else:
            if debt_raw > 0:
                d_fixed += debt_usd
            if supply_raw > 0 and r["use_as_collateral"] and threshold > 0:
                c_fixed += supply_usd * threshold

    if eth_debt_usd_sum == 0:
        return Decimal("0")

    denom = eth_col_theta_usd_sum - eth_debt_usd_sum
    if denom >= 0:
        return Decimal("0")

    numerator = d_fixed - c_fixed
    liq_price_rise = eth_price_now * numerator / denom
    if liq_price_rise <= 0:
        return Decimal("0")

    # 安全检查：E-Mode 用户的真实 liq_threshold > getReserveConfigurationData 普通值，
    # 若结果 < 当前 ETH 价格（eth_price_now）说明是 E-Mode 误判，返回 0。
    if liq_price_rise < eth_price_now:
        return Decimal("0")

    return min(liq_price_rise, _LIQ_PRICE_CAP)


# ─────────────────────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────────────────────


async def main(config_path: str | None, dry_run: bool, protocol: str) -> None:
    cfg = load_config(config_path)
    tables = get_tables(protocol)

    if tables.side != "borrow":
        logger.error(
            "协议 %s 不是借贷端（side=%s），请使用 v3_borrow 或 v2_borrow",
            protocol,
            tables.side,
        )
        return

    pos_table = tables.positions
    res_table = tables.reserve_positions
    logger.info(
        "协议: %s  |  positions: %s  |  reserve_positions: %s",
        protocol,
        pos_table,
        res_table,
    )

    # ── 1. 从链上取 reserve configs（约 N_assets 次 RPC）────────────────────
    # 去掉 "_borrow" 后缀获取基础协议版本（v3/v2）的合约
    base_protocol = protocol.replace("_borrow", "")
    contracts = get_contracts(base_protocol)

    logger.info("连接 RPC：%s", cfg.rpc_url)
    w3 = await build_web3(cfg)
    logger.info("获取储备资产列表...")
    reserve_tokens = await get_all_reserve_tokens(w3, contracts=contracts)
    logger.info("储备资产数量: %d", len(reserve_tokens))

    logger.info("批量获取 liq_threshold（每资产 1 次 RPC）...")
    token_addresses = [rt.token_address for rt in reserve_tokens]
    configs_list = await asyncio.gather(
        *[
            get_reserve_config(w3, addr, contracts=contracts)
            for addr in token_addresses
        ],
        return_exceptions=True,
    )
    liq_thresholds: dict[str, Decimal] = {}
    for addr, cfg_or_err in zip(token_addresses, configs_list):
        if isinstance(cfg_or_err, Exception):
            logger.warning("get_reserve_config 失败 %s: %s", addr, cfg_or_err)
            continue
        liq_thresholds[addr.lower()] = Decimal(
            cfg_or_err.liquidation_threshold  # type: ignore[attr-defined]
        ) / Decimal(10000)
    logger.info("成功获取 %d 个资产的 liq_threshold", len(liq_thresholds))
    await w3.provider.disconnect()

    # ── 2. 读取 DB 数据 ───────────────────────────────────────────────────────
    logger.info("连接数据库...")
    pool = await asyncpg.create_pool(cfg.postgres.dsn, min_size=2, max_size=5)

    async with pool.acquire() as conn:
        reserve_rows = await conn.fetch(
            f"""
            SELECT user_address, token_address, symbol,
                   price_usd, supply_usd, supply_raw,
                   stable_debt_raw, variable_debt_raw, total_debt_usd,
                   use_as_collateral
            FROM loan.{res_table}
            """
        )
        pos_count = await conn.fetchval(f"SELECT COUNT(*) FROM loan.{pos_table}")
    logger.info(
        "读取 reserve 明细行数: %d（涉及仓位: %d）", len(reserve_rows), pos_count
    )

    # ── 3. 按 user_address 分组 ───────────────────────────────────────────────
    reserves_by_user: dict[str, list[dict]] = {}
    for row in reserve_rows:
        key = row["user_address"]
        reserves_by_user.setdefault(key, []).append(dict(row))

    # ── 4. 逐用户重算 liq_price_rise ─────────────────────────────────────────
    updates: list[tuple[Decimal, str]] = []
    cnt_risk = 0
    cnt_zero = 0

    for addr, reserves in reserves_by_user.items():
        new_val = _recalc_rise(reserves, liq_thresholds)
        updates.append((new_val, addr))
        if new_val > 0:
            cnt_risk += 1
        else:
            cnt_zero += 1

    logger.info(
        "计算完成：共 %d 条 | liq_price_rise > 0: %d | = 0: %d",
        len(updates),
        cnt_risk,
        cnt_zero,
    )

    if dry_run:
        logger.info("[dry-run] 前 10 条预览：")
        for val, addr in sorted(updates, key=lambda x: x[0], reverse=True)[:10]:
            logger.info("  %-44s  liq_price_rise = %s", addr, val)
        logger.info("[dry-run] 未写入数据库")
        await pool.close()
        return

    # ── 5. 批量 UPDATE ────────────────────────────────────────────────────────
    BATCH = 500
    total_updated = 0
    async with pool.acquire() as conn:
        for i in range(0, len(updates), BATCH):
            batch = updates[i : i + BATCH]
            await conn.executemany(
                f"UPDATE loan.{pos_table} SET liq_price_rise = $1 WHERE user_address = $2",
                batch,
            )
            total_updated += len(batch)
            logger.info("已更新 %d / %d", total_updated, len(updates))

    await pool.close()
    logger.info("完成！共更新 %d 条 liq_price_rise", total_updated)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="重算借贷端仓位的 liq_price_rise（无需重爬）"
    )
    p.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="config.yaml 路径（默认自动查找）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只计算不写入，打印前 10 条 liq_price_rise > 0 的结果",
    )
    p.add_argument(
        "--protocol",
        "-p",
        choices=["v3_borrow", "v2_borrow"],
        default="v3_borrow",
        help="借贷端协议版本（默认 v3_borrow）",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args.config, args.dry_run, protocol=args.protocol))
