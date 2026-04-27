"""Load Morpho V2 vault tables from vault list JSON.

Input example:
  tmp/morpho_vaults_over_10000_usd.json

Flow:
  1) read items and keep protocol == v2
  2) query V2 state from official GraphQL (via existing service helper)
  3) upsert into:
     - loan.morpho_vault_v2_current
     - loan.morpho_vault_v2_gates_current
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from morpho_crawler.api.service import get_vault_v2_state_main_graphql
from morpho_crawler.config import load_config
from morpho_crawler.db import create_pool

ROOT = Path(__file__).resolve().parent.parent.parent
_GATE_TYPES = (
    "sendSharesGate",
    "receiveAssetsGate",
    "receiveSharesGate",
    "sendAssetsGate",
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从金库列表抓取 v2/state 并回填 V2 当前表"
    )
    parser.add_argument(
        "--input",
        default="tmp/morpho_vaults_over_10000_usd.json",
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
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="并发抓取数量，默认 8",
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


async def _fetch_one(address: str, sem: asyncio.Semaphore) -> dict[str, Any] | None:
    async with sem:
        try:
            resp = await get_vault_v2_state_main_graphql(address=address)
            return (
                ((resp.data or {}).get("vaultV2ByAddress") or {}) if resp.data else None
            )
        except Exception:  # noqa: BLE001
            return None


async def _load(args: argparse.Namespace) -> tuple[int, int]:
    raw = json.loads(_resolve_path(args.input).read_text(encoding="utf-8"))
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ValueError("输入文件格式错误：缺少 items 数组")

    addresses: list[str] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        if str(row.get("protocol") or "").lower() != "v2":
            continue
        addr = str(row.get("address") or "").strip()
        if addr:
            addresses.append(addr)

    sem = asyncio.Semaphore(max(1, args.concurrency))
    fetched = await asyncio.gather(*[_fetch_one(a, sem) for a in addresses])
    vaults = [v for v in fetched if isinstance(v, dict) and v.get("address")]

    cfg = load_config()
    pool = await create_pool(cfg.postgres)
    try:
        current_rows: list[tuple[Any, ...]] = []
        gates_rows: list[tuple[Any, ...]] = []

        for v in vaults:
            vault_address_b = _hex_to_bytes(v.get("address"))
            if vault_address_b is None:
                continue
            asset = v.get("asset") or {}
            current_rows.append(
                (
                    vault_address_b,
                    v.get("name"),
                    _hex_to_bytes(asset.get("address")),
                    asset.get("symbol"),
                    asset.get("decimals"),
                    v.get("totalAssetsUsd"),
                    v.get("idleAssetsUsd"),
                    v.get("liquidityUsd"),
                    v.get("apy"),
                    v.get("netApy"),
                    v.get("netApyExcludingRewards"),
                    v.get("avgNetApy"),
                    v.get("avgNetApyExcludingRewards"),
                    v.get("maxApy"),
                    v.get("forceDeallocatableLiquidityUsd"),
                    v.get("performanceFee"),
                    v.get("managementFee"),
                )
            )

            gates = v.get("gatesConfig") or {}
            for gate_type in _GATE_TYPES:
                gate = gates.get(gate_type) or {}
                gates_rows.append(
                    (
                        vault_address_b,
                        gate_type,
                        _hex_to_bytes(gate.get("address")),
                        bool(gate.get("abdicated") or False),
                        gate.get("pendingAbdicationExecutableAt"),
                        _hex_to_bytes(gate.get("pendingAddress")),
                        gate.get("pendingExecutableAt"),
                    )
                )

        async with pool.acquire() as conn:
            async with conn.transaction():
                if args.truncate:
                    await conn.execute(
                        "TRUNCATE TABLE loan.morpho_vault_v2_gates_current"
                    )
                    await conn.execute("TRUNCATE TABLE loan.morpho_vault_v2_current")

                await conn.executemany(
                    """
                    INSERT INTO loan.morpho_vault_v2_current (
                        vault_address, vault_name, asset_address, asset_symbol, asset_decimals,
                        total_assets_usd, idle_assets_usd, liquidity_usd, apy, net_apy,
                        net_apy_excluding_rewards, avg_net_apy, avg_net_apy_excluding_rewards, max_apy,
                        force_deallocatable_liquidity_usd, performance_fee, management_fee, source_ts, updated_at
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,NOW(),NOW()
                    )
                    ON CONFLICT (vault_address) DO UPDATE SET
                        vault_name = EXCLUDED.vault_name,
                        asset_address = EXCLUDED.asset_address,
                        asset_symbol = EXCLUDED.asset_symbol,
                        asset_decimals = EXCLUDED.asset_decimals,
                        total_assets_usd = EXCLUDED.total_assets_usd,
                        idle_assets_usd = EXCLUDED.idle_assets_usd,
                        liquidity_usd = EXCLUDED.liquidity_usd,
                        apy = EXCLUDED.apy,
                        net_apy = EXCLUDED.net_apy,
                        net_apy_excluding_rewards = EXCLUDED.net_apy_excluding_rewards,
                        avg_net_apy = EXCLUDED.avg_net_apy,
                        avg_net_apy_excluding_rewards = EXCLUDED.avg_net_apy_excluding_rewards,
                        max_apy = EXCLUDED.max_apy,
                        force_deallocatable_liquidity_usd = EXCLUDED.force_deallocatable_liquidity_usd,
                        performance_fee = EXCLUDED.performance_fee,
                        management_fee = EXCLUDED.management_fee,
                        source_ts = NOW(),
                        updated_at = NOW()
                    """,
                    current_rows,
                )

                await conn.executemany(
                    """
                    INSERT INTO loan.morpho_vault_v2_gates_current (
                        vault_address, gate_type, gate_address, abdicated,
                        pending_abdication_executable_at, pending_address, pending_executable_at,
                        source_ts, updated_at
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,NOW(),NOW())
                    ON CONFLICT (vault_address, gate_type) DO UPDATE SET
                        gate_address = EXCLUDED.gate_address,
                        abdicated = EXCLUDED.abdicated,
                        pending_abdication_executable_at = EXCLUDED.pending_abdication_executable_at,
                        pending_address = EXCLUDED.pending_address,
                        pending_executable_at = EXCLUDED.pending_executable_at,
                        source_ts = NOW(),
                        updated_at = NOW()
                    """,
                    gates_rows,
                )

        return len(current_rows), len(gates_rows)
    finally:
        await pool.close()


def main() -> None:
    args = _build_parser().parse_args()
    current_cnt, gates_cnt = asyncio.run(_load(args))
    print(f"Loaded morpho_vault_v2_current rows: {current_cnt}")
    print(f"Loaded morpho_vault_v2_gates_current rows: {gates_cnt}")


if __name__ == "__main__":
    main()
