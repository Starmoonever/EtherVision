"""
recalc_liq_price.py
─────────────────────────────────────────────────────────────────────────────
从数据库读取已存储的仓位数据，使用正确的逐资产清算阈值公式重算 liq_price，
然后批量写回 DB。

运行方式
    cd backend
    uv run python scripts/recalc_liq_price.py [--config config.yaml] [--dry-run]

与全量 crawl 相比，此脚本的 RPC 用量极少：
  - 仅对每个储备资产做一次 getReserveConfigurationData（约 15 次调用）
  - 不做任何 getUserAccountData / getUserReserveData
  - market data（价格、supply_raw）全部来自 DB

正确公式（HF = 1 时触发清算）：
    P = (total_debt_usd − Σ other_supply_usd_i × liq_threshold_i)
        ─────────────────────────────────────────────────────────
        eth_supply_amount × liq_threshold_ETH
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from decimal import Decimal
from pathlib import Path

import asyncpg

# ── 将 backend/ 加入路径（脚本可从任意 cwd 运行）────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aave_crawler.config import load_config  # noqa: E402
from aave_crawler.db import get_tables  # noqa: E402
from aave_crawler.rpc import (build_web3, get_all_reserve_tokens,  # noqa: E402
                              get_contracts, get_reserve_config)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ETH 系资产（与 db.py / service.py 保持一致）
_ETH_SYMBOLS: frozenset[str] = frozenset({"WETH", "ETH", "CBETH", "WSTETH", "RETH"})
_LIQ_PRICE_CAP = Decimal("9999999.99999999")

# ─────────────────────────────────────────────────────────────────────────────
# 核心计算
# ─────────────────────────────────────────────────────────────────────────────

def _recalc(
    total_debt_usd: Decimal,
    reserves: list[dict],
    liq_thresholds: dict[str, Decimal],   # token_address → threshold (0~1)
) -> Decimal:
    """
    使用逐资产 liq_threshold 重算 ETH 清算价。

    reserves 每项字段：
        token_address, symbol, supply_raw, supply_usd,
        decimals, use_as_collateral
    liq_thresholds：token_address → Decimal(threshold / 10000)
    """
    if total_debt_usd == 0:
        return Decimal("0")

    # 找第一个 ETH 系抵押品
    eth_reserve = None
    for r in reserves:
        if (
            r["symbol"].upper() in _ETH_SYMBOLS
            and r["use_as_collateral"]
            and int(r["supply_raw"]) > 0
        ):
            eth_reserve = r
            break

    if eth_reserve is None:
        return Decimal("0")

    eth_addr = eth_reserve["token_address"].lower()
    eth_liq_threshold = liq_thresholds.get(eth_addr, Decimal("0"))
    if eth_liq_threshold == 0:
        return Decimal("0")

    # eth_amount = supply_raw / 10^decimals
    eth_amount = Decimal(str(int(eth_reserve["supply_raw"]))) / Decimal(10) ** eth_reserve["decimals"]
    if eth_amount == 0:
        return Decimal("0")

    # 其他（非 ETH）抵押品安全垫
    other_safe = Decimal("0")
    for r in reserves:
        if r["symbol"].upper() in _ETH_SYMBOLS:
            continue
        if not r["use_as_collateral"] or int(r["supply_raw"]) == 0:
            continue
        threshold = liq_thresholds.get(r["token_address"].lower(), Decimal("0"))
        if threshold == 0:
            continue
        # supply_usd 已存储（= supply_raw / 10^decimals × price_usd），直接用
        other_safe += Decimal(str(r["supply_usd"])) * threshold

    numerator = total_debt_usd - other_safe
    if numerator <= 0:
        return Decimal("0")

    liq_price = numerator / (eth_amount * eth_liq_threshold)
    return min(liq_price, _LIQ_PRICE_CAP)


# ─────────────────────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────────────────────

async def main(config_path: str | None, dry_run: bool, protocol: str = "v3") -> None:
    cfg = load_config(config_path)
    contracts = get_contracts(protocol)
    tables = get_tables(protocol)
    pos_table = tables.positions
    res_table = tables.reserve_positions
    logger.info("Protocol: %s  |  positions: %s  |  reserve_positions: %s", protocol, pos_table, res_table)

    # ── 1. 从链上取 reserve configs（仅此一次 RPC，约 15 次调用）──────────────
    logger.info("连接 RPC：%s", cfg.rpc_url)
    w3 = await build_web3(cfg)

    logger.info("获取储备资产列表 ...")
    reserve_tokens = await get_all_reserve_tokens(w3, contracts=contracts)
    logger.info("储备资产数量: %d", len(reserve_tokens))

    logger.info("批量获取 reserve configs（每资产 liq_threshold）...")
    token_addresses = [rt.token_address for rt in reserve_tokens]
    configs_list = await asyncio.gather(
        *[get_reserve_config(w3, addr, contracts=contracts) for addr in token_addresses],
        return_exceptions=True,
    )

    # token_address（统一小写） → Decimal threshold（0~1）
    liq_thresholds: dict[str, Decimal] = {}
    for addr, cfg_or_err in zip(token_addresses, configs_list):
        if isinstance(cfg_or_err, Exception):
            logger.warning("get_reserve_config 失败 %s: %s", addr, cfg_or_err)
            continue
        liq_thresholds[addr.lower()] = Decimal(cfg_or_err.liquidation_threshold) / Decimal(10000)

    logger.info("成功获取 %d 个资产的 liq_threshold", len(liq_thresholds))

    # ── 2. 连接 DB，读取所有仓位数据 ─────────────────────────────────────────
    logger.info("连接数据库 ...")
    pool = await asyncpg.create_pool(cfg.postgres.dsn, min_size=2, max_size=5)

    async with pool.acquire() as conn:
        # 读主仓位表（total_debt_usd）
        positions_rows = await conn.fetch(
            f"SELECT user_address, total_debt_usd FROM loan.{pos_table}"
        )
        logger.info("读取仓位数量: %d", len(positions_rows))

        # 读 reserve positions（逐资产明细）
        reserve_rows = await conn.fetch(
            f"""
            SELECT user_address, token_address, symbol,
                   supply_raw, supply_usd, decimals, use_as_collateral
            FROM loan.{res_table}
            """
        )
        logger.info("读取 reserve 明细行数: %d", len(reserve_rows))

    await pool.close()

    # ── 3. 按 user_address 分组 reserve 明细 ─────────────────────────────────
    reserves_by_user: dict[str, list[dict]] = {}
    for row in reserve_rows:
        key = row["user_address"]
        reserves_by_user.setdefault(key, []).append(dict(row))

    # ── 4. 逐用户重算 liq_price ───────────────────────────────────────────────
    updates: list[tuple[Decimal, str]] = []   # (new_liq_price, user_address)
    skipped = 0

    for row in positions_rows:
        addr = row["user_address"]
        total_debt = Decimal(str(row["total_debt_usd"]))
        reserves = reserves_by_user.get(addr, [])

        new_price = _recalc(total_debt, reserves, liq_thresholds)
        updates.append((new_price, addr))

    changed = sum(1 for _ in updates)  # 全部更新，不做旧值比较（避免精度问题）
    logger.info("计算完成，共 %d 条记录待更新（跳过 %d 条）", changed, skipped)

    if dry_run:
        # 打印前 10 条预览
        logger.info("[dry-run] 前 10 条结果预览：")
        for new_price, addr in updates[:10]:
            logger.info("  %s  →  liq_price = %s", addr, new_price)
        logger.info("[dry-run] 未写入数据库")
        return

    # ── 5. 批量 UPDATE ────────────────────────────────────────────────────────
    BATCH = 500
    pool2 = await asyncpg.create_pool(cfg.postgres.dsn, min_size=2, max_size=5)
    total_updated = 0

    async with pool2.acquire() as conn:
        for i in range(0, len(updates), BATCH):
            batch = updates[i : i + BATCH]
            await conn.executemany(
                f"UPDATE loan.{pos_table} SET liq_price = $1 WHERE user_address = $2",
                batch,
            )
            total_updated += len(batch)
            logger.info("已更新 %d / %d", total_updated, len(updates))

    await pool2.close()
    logger.info("完成！共更新 %d 条 liq_price", total_updated)


# ─────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="重算 DB 中所有仓位的 liq_price")
    p.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="config.yaml 路径（默认自动查找）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只计算不写入，打印前 10 条结果预览",
    )
    p.add_argument(
        "--protocol", "-p",
        choices=["v2", "v3", "v2_borrow", "v3_borrow"],
        default="v3",
        help="Aave 协议版本（默认 v3）",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args.config, args.dry_run, protocol=args.protocol))
