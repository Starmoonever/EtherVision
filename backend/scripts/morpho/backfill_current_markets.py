"""Backfill Morpho current markets cache table.

Examples:
    uv run python scripts/morpho/backfill_current_markets.py
    uv run python scripts/morpho/backfill_current_markets.py --dry-run --limit 5
    uv run python scripts/morpho/backfill_current_markets.py --input tmp/morpho_markets_hardcoded_market_ids.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from web3 import AsyncHTTPProvider, AsyncWeb3

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(os.path.abspath(str(ROOT)))

from crawler_shared.logging import setup_cli_logging  # noqa: E402
from morpho_crawler.config import load_config  # noqa: E402
from morpho_crawler.db import create_pool  # noqa: E402
from morpho_crawler.rpc import fetch_market_state  # noqa: E402

GRAPHQL_ENDPOINT = "https://blue-api.morpho.org/graphql"
MARKET_BY_ID_QUERY = """
query MarketMetrics($marketId: String!, $chainId: Int!) {
  marketById(marketId: $marketId, chainId: $chainId) {
    state {
      sizeUsd
    }
  }
}
""".strip()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="回填 loan.morpho_blue_current_markets（100 个硬编码市场）"
    )
    parser.add_argument("--config", default=None, help="config.yaml 路径")
    parser.add_argument(
        "--input",
        default="tmp/morpho_markets_hardcoded_market_ids.json",
        help="market_id 列表 JSON 文件路径（相对 backend/ 或绝对路径）",
    )
    parser.add_argument(
        "--chain-id",
        type=int,
        default=1,
        help="Morpho Blue API chainId，默认 1",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="最多处理多少个市场，0 表示全部",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="只拉取不写库",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="开启 DEBUG 日志",
    )
    return parser


def _resolve_path(path_text: str) -> Path:
    p = Path(path_text)
    if p.is_absolute():
        return p
    return ROOT / p


def _load_market_ids(path: Path) -> list[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("market_id 文件格式错误：顶层必须是数组")
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.startswith("0x"):
            out.append(item.strip())
    if not out:
        raise ValueError("market_id 文件为空或无有效 market_id")
    return out


def _post_graphql(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [
                "curl",
                "-sS",
                "-X",
                "POST",
                GRAPHQL_ENDPOINT,
                "-H",
                "Content-Type: application/json",
                "--data",
                json.dumps(payload),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(f"curl 调用 Morpho GraphQL 失败: {stderr}") from exc
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Morpho GraphQL 返回非 JSON") from exc


def _fetch_market_size_usd(*, market_id: str, chain_id: int) -> Decimal | None:
    body = _post_graphql(
        {
            "query": MARKET_BY_ID_QUERY,
            "variables": {"marketId": market_id, "chainId": chain_id},
        }
    )
    if body.get("errors"):
        raise RuntimeError(f"Morpho GraphQL 错误: {body['errors']}")
    row = (body.get("data") or {}).get("marketById") or {}
    state = row.get("state") or {}
    size = state.get("sizeUsd")
    if size is None:
        return None
    return Decimal(str(size))


async def _upsert_row(
    pool,
    *,
    market_id: str,
    payload: dict[str, Any],
    total_market_size_usd: Decimal | None,
) -> None:
    loan_token = payload["loanToken"]
    collateral_token = payload["collateralToken"]
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO loan.morpho_blue_current_markets (
                market_id,
                loan_symbol,
                loan_address,
                loan_decimals,
                collateral_symbol,
                collateral_address,
                collateral_decimals,
                oracle,
                irm,
                lltv_raw,
                total_supply_assets,
                total_supply_shares,
                total_borrow_assets,
                total_borrow_shares,
                last_update,
                fee_raw,
                total_market_size_usd,
                source,
                is_active,
                updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9,
                $10, $11, $12, $13, $14, $15, $16, $17, $18, true, NOW()
            )
            ON CONFLICT (market_id) DO UPDATE SET
                loan_symbol = EXCLUDED.loan_symbol,
                loan_address = EXCLUDED.loan_address,
                loan_decimals = EXCLUDED.loan_decimals,
                collateral_symbol = EXCLUDED.collateral_symbol,
                collateral_address = EXCLUDED.collateral_address,
                collateral_decimals = EXCLUDED.collateral_decimals,
                oracle = EXCLUDED.oracle,
                irm = EXCLUDED.irm,
                lltv_raw = EXCLUDED.lltv_raw,
                total_supply_assets = EXCLUDED.total_supply_assets,
                total_supply_shares = EXCLUDED.total_supply_shares,
                total_borrow_assets = EXCLUDED.total_borrow_assets,
                total_borrow_shares = EXCLUDED.total_borrow_shares,
                last_update = EXCLUDED.last_update,
                fee_raw = EXCLUDED.fee_raw,
                total_market_size_usd = EXCLUDED.total_market_size_usd,
                source = EXCLUDED.source,
                is_active = EXCLUDED.is_active,
                updated_at = NOW()
            """,
            market_id,
            loan_token.get("symbol"),
            loan_token.get("address"),
            int(loan_token.get("decimals") or 0),
            collateral_token.get("symbol"),
            collateral_token.get("address"),
            int(collateral_token.get("decimals") or 0),
            payload.get("oracle"),
            payload.get("irm"),
            Decimal(str(payload["lltv"]["raw"])),
            Decimal(str(payload["totalSupplyAssets"])),
            Decimal(str(payload["totalSupplyShares"])),
            Decimal(str(payload["totalBorrowAssets"])),
            Decimal(str(payload["totalBorrowShares"])),
            int(payload["lastUpdate"]),
            Decimal(str(payload["fee"])),
            total_market_size_usd,
            "script:backfill_current_markets",
        )


async def _run() -> None:
    args = _build_parser().parse_args()
    setup_cli_logging(args.verbose)

    cfg = load_config(args.config)
    if not cfg.eth_rpc_url:
        raise RuntimeError("config 中 eth_rpc_url 为空，无法拉链上数据")

    input_path = _resolve_path(args.input)
    market_ids = _load_market_ids(input_path)
    if args.limit > 0:
        market_ids = market_ids[: args.limit]

    w3 = AsyncWeb3(AsyncHTTPProvider(cfg.eth_rpc_url))
    pool = await create_pool(cfg.postgres)

    ok = 0
    failed = 0
    try:
        for idx, market_id in enumerate(market_ids, start=1):
            try:
                state_payload = await fetch_market_state(w3, market_id=market_id)
                size_usd = _fetch_market_size_usd(
                    market_id=market_id,
                    chain_id=args.chain_id,
                )
                if not args.dry_run:
                    await _upsert_row(
                        pool,
                        market_id=market_id,
                        payload=state_payload,
                        total_market_size_usd=size_usd,
                    )
                ok += 1
                print(
                    f"[{idx}/{len(market_ids)}] ok market_id={market_id} "
                    f"size_usd={size_usd if size_usd is not None else 'null'} "
                    f"write={'no' if args.dry_run else 'yes'}"
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(
                    f"[{idx}/{len(market_ids)}] fail market_id={market_id} error={exc}"
                )
        print(
            "done: "
            f"total={len(market_ids)} ok={ok} failed={failed} dry_run={args.dry_run}"
        )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
