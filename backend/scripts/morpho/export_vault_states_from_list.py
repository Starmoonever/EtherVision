"""Export Morpho V1/V2 state JSON from a vault list.

Input example:
  tmp/morpho_vaults_over_10000_usd.json

The output keeps each vault state's payload in the same shape as the current
v1/state or v2/state service response.

Examples:
    uv run python scripts/morpho/export_vault_states_from_list.py
    uv run python scripts/morpho/export_vault_states_from_list.py --concurrency 8
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from morpho_crawler.api.service import get_vault_state_main_graphql
from morpho_crawler.api.service import get_vault_v2_state_main_graphql

ROOT = Path(__file__).resolve().parent.parent.parent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="按金库列表导出 v1/state 与 v2/state 形态的 JSON"
    )
    parser.add_argument(
        "--input",
        default="tmp/morpho_vaults_over_10000_usd.json",
        help="输入金库列表 JSON（相对 backend/ 或绝对路径）",
    )
    parser.add_argument(
        "--output",
        default="tmp/morpho_vault_states_over_10000_usd.json",
        help="输出 JSON（相对 backend/ 或绝对路径）",
    )
    parser.add_argument("--chain-id", type=int, default=1, help="链 ID，默认 1")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="并发请求数，默认 8",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅导出前 N 个（调试用）",
    )
    return parser


def _resolve_path(path_text: str) -> Path:
    p = Path(path_text)
    if p.is_absolute():
        return p
    return ROOT / p


def _load_items(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("输入文件格式错误：缺少 items 数组")

    out: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        address = str(row.get("address") or "").strip()
        protocol = str(row.get("protocol") or "").strip().lower()
        if not address or protocol not in {"v1", "v2"}:
            continue
        out.append(row)
    return out


async def _fetch_one(
    row: dict[str, Any],
    *,
    sem: asyncio.Semaphore,
    chain_id: int,
) -> dict[str, Any]:
    address = str(row.get("address") or "").strip()
    protocol = str(row.get("protocol") or "").strip().lower()
    t0 = time.time()
    async with sem:
        try:
            if protocol == "v1":
                resp = await get_vault_state_main_graphql(
                    address=address,
                    chain_id=chain_id,
                    w3=None,
                    pool=None,
                )
            elif protocol == "v2":
                resp = await get_vault_v2_state_main_graphql(
                    address=address,
                    chain_id=chain_id,
                    pool=None,
                )
            else:
                raise ValueError(f"不支持的 protocol: {protocol}")
            return {
                "address": address,
                "protocol": protocol,
                "asset": row.get("asset"),
                "tvl_usd": row.get("tvl_usd"),
                "liquidity_usd": row.get("liquidity_usd"),
                "ok": True,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "response": resp.model_dump(mode="json"),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "address": address,
                "protocol": protocol,
                "asset": row.get("asset"),
                "tvl_usd": row.get("tvl_usd"),
                "liquidity_usd": row.get("liquidity_usd"),
                "ok": False,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "error": str(exc),
            }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    input_path = _resolve_path(args.input)
    rows = _load_items(input_path)
    if args.limit is not None:
        rows = rows[: max(0, args.limit)]

    sem = asyncio.Semaphore(max(1, args.concurrency))
    results = await asyncio.gather(
        *[_fetch_one(r, sem=sem, chain_id=args.chain_id) for r in rows]
    )
    successes = [r for r in results if r.get("ok")]
    failures = [r for r in results if not r.get("ok")]
    return {
        "source_input": str(input_path),
        "chain_id": args.chain_id,
        "requested": len(rows),
        "success_count": len(successes),
        "failure_count": len(failures),
        "items": results,
    }


def main() -> None:
    args = _build_parser().parse_args()
    output = asyncio.run(_run(args))
    out_path = _resolve_path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote: {out_path}")
    print(
        "Summary:",
        output["requested"],
        "requested,",
        output["success_count"],
        "success,",
        output["failure_count"],
        "failed",
    )


if __name__ == "__main__":
    main()
