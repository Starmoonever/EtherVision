"""Load Morpho V1 vault current tables from exported states JSON.

Input example:
  tmp/morpho_vault_states_over_10000_usd.json

This script reads `successes` items, keeps `protocol == v1`, and upserts into:
  - loan.morpho_vault_v1_current
  - loan.morpho_vault_v1_allocation_current
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from morpho_crawler.config import load_config
from morpho_crawler.db import create_pool

ROOT = Path(__file__).resolve().parent.parent.parent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="将 v1 state 导出 JSON 回填到 morpho_vault_v1_current 两张表"
    )
    parser.add_argument(
        "--input",
        default="tmp/morpho_vault_states_over_10000_usd.json",
        help="输入 JSON（相对 backend/ 或绝对路径）",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        default=True,
        help="写入前清空两张目标表（默认开启）",
    )
    parser.add_argument(
        "--no-truncate",
        dest="truncate",
        action="store_false",
        help="不清空，直接 upsert",
    )
    return parser


def _resolve_path(path_text: str) -> Path:
    p = Path(path_text)
    if p.is_absolute():
        return p
    return ROOT / p


def _hex_to_bytes(addr: str | None) -> bytes | None:
    if not addr:
        return None
    s = str(addr).strip()
    if not s:
        return None
    if s.startswith("0x") or s.startswith("0X"):
        s = s[2:]
    if len(s) % 2 == 1:
        s = "0" + s
    try:
        return bytes.fromhex(s)
    except ValueError:
        return None


async def _load(args: argparse.Namespace) -> tuple[int, int]:
    cfg = load_config()
    pool = await create_pool(cfg.postgres)
    try:
        payload = json.loads(_resolve_path(args.input).read_text(encoding="utf-8"))
        successes = payload.get("successes") or []

        v1_items: list[dict[str, Any]] = []
        for row in successes:
            if not isinstance(row, dict):
                continue
            if str(row.get("protocol") or "").lower() != "v1":
                continue
            if not row.get("ok"):
                continue
            v1_items.append(row)

        current_rows: list[tuple[Any, ...]] = []
        alloc_rows: list[tuple[Any, ...]] = []
        for row in v1_items:
            body = ((row.get("response") or {}).get("data") or {}).get(
                "vaultByAddress"
            ) or {}
            state = body.get("state") or {}
            asset = body.get("asset") or {}
            vault_address_b = _hex_to_bytes(body.get("address"))
            if vault_address_b is None:
                continue

            current_rows.append(
                (
                    vault_address_b,
                    body.get("name"),
                    _hex_to_bytes(asset.get("address")),
                    asset.get("symbol"),
                    asset.get("decimals"),
                    state.get("totalAssetsUsd"),
                    state.get("apy"),
                    state.get("netApy"),
                    state.get("netApyExcludingRewards"),
                    state.get("avgNetApy"),
                    state.get("avgNetApyExcludingRewards"),
                    state.get("timelock"),
                    state.get("fee"),
                    state.get("liquidityUsd"),
                )
            )

            for alloc in state.get("allocation") or []:
                if not isinstance(alloc, dict):
                    continue
                market = alloc.get("market") or {}
                market_id = str(market.get("market_id") or "").strip()
                if not market_id:
                    continue
                alloc_rows.append(
                    (
                        vault_address_b,
                        market_id,
                        alloc.get("supplyAssetsUsd"),
                        alloc.get("supplyCapUsd"),
                        alloc.get("liquidityUsd"),
                    )
                )

        async with pool.acquire() as conn:
            async with conn.transaction():
                if args.truncate:
                    await conn.execute(
                        "TRUNCATE TABLE loan.morpho_vault_v1_allocation_current"
                    )
                    await conn.execute("TRUNCATE TABLE loan.morpho_vault_v1_current")

                await conn.executemany(
                    """
                    INSERT INTO loan.morpho_vault_v1_current (
                        vault_address,
                        vault_name,
                        asset_address,
                        asset_symbol,
                        asset_decimals,
                        total_assets_usd,
                        apy,
                        net_apy,
                        net_apy_excluding_rewards,
                        avg_net_apy,
                        avg_net_apy_excluding_rewards,
                        timelock_seconds,
                        fee_raw,
                        liquidity_usd,
                        source_ts,
                        updated_at
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
                        NOW(),NOW()
                    )
                    ON CONFLICT (vault_address) DO UPDATE SET
                        vault_name = EXCLUDED.vault_name,
                        asset_address = EXCLUDED.asset_address,
                        asset_symbol = EXCLUDED.asset_symbol,
                        asset_decimals = EXCLUDED.asset_decimals,
                        total_assets_usd = EXCLUDED.total_assets_usd,
                        apy = EXCLUDED.apy,
                        net_apy = EXCLUDED.net_apy,
                        net_apy_excluding_rewards = EXCLUDED.net_apy_excluding_rewards,
                        avg_net_apy = EXCLUDED.avg_net_apy,
                        avg_net_apy_excluding_rewards = EXCLUDED.avg_net_apy_excluding_rewards,
                        timelock_seconds = EXCLUDED.timelock_seconds,
                        fee_raw = EXCLUDED.fee_raw,
                        liquidity_usd = EXCLUDED.liquidity_usd,
                        source_ts = NOW(),
                        updated_at = NOW()
                    """,
                    current_rows,
                )

                await conn.executemany(
                    """
                    INSERT INTO loan.morpho_vault_v1_allocation_current (
                        vault_address,
                        market_id,
                        supply_assets_usd,
                        supply_cap_usd,
                        liquidity_usd,
                        source_ts,
                        updated_at
                    ) VALUES ($1,$2,$3,$4,$5,NOW(),NOW())
                    ON CONFLICT (vault_address, market_id) DO UPDATE SET
                        supply_assets_usd = EXCLUDED.supply_assets_usd,
                        supply_cap_usd = EXCLUDED.supply_cap_usd,
                        liquidity_usd = EXCLUDED.liquidity_usd,
                        source_ts = NOW(),
                        updated_at = NOW()
                    """,
                    alloc_rows,
                )

        return len(current_rows), len(alloc_rows)
    finally:
        await pool.close()


def main() -> None:
    args = _build_parser().parse_args()
    current_cnt, alloc_cnt = asyncio.run(_load(args))
    print(f"Loaded morpho_vault_v1_current rows: {current_cnt}")
    print(f"Loaded morpho_vault_v1_allocation_current rows: {alloc_cnt}")


if __name__ == "__main__":
    main()
