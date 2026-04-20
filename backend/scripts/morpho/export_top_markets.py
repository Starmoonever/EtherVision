"""Export top Morpho markets by Total Market Size.

Examples:
    uv run python scripts/morpho/export_top_markets.py
    uv run python scripts/morpho/export_top_markets.py --top 100 --chain-id 1
    uv run python scripts/morpho/export_top_markets.py --output scripts/morpho/top_markets.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any

GRAPHQL_ENDPOINT = "https://blue-api.morpho.org/graphql"
APP_MARKETS_URL = "https://app.morpho.org/markets?chains=1"

QUERY = """
query TopMarkets($first: Int!, $chainIds: [Int!], $listed: Boolean) {
  markets(
    first: $first
    orderBy: SizeUsd
    orderDirection: Desc
    where: { chainId_in: $chainIds, listed: $listed }
  ) {
    items {
      marketId
      loanAsset {
        symbol
        address
      }
      collateralAsset {
        symbol
        address
      }
      state {
        sizeUsd
        utilization
      }
    }
    pageInfo {
      count
      countTotal
    }
  }
}
""".strip()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="导出 Morpho 按 Total Market Size 排序的市场列表"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=100,
        help="导出的市场数量，默认 100",
    )
    parser.add_argument(
        "--chain-id",
        type=int,
        default=1,
        help="链 id，默认 1（Ethereum）",
    )
    parser.add_argument(
        "--include-unlisted",
        action="store_true",
        default=False,
        help="是否包含未 listed 市场（默认 false）",
    )
    parser.add_argument(
        "--output",
        default="scripts/morpho/top_100_markets_by_total_market_size.json",
        help="输出 JSON 文件路径（相对 backend/ 或绝对路径）",
    )
    return parser


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
        text = proc.stdout
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"curl failed when calling Morpho GraphQL: {exc.stderr.strip()}"
        ) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from Morpho GraphQL: {text[:200]}") from exc


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    loan = item.get("loanAsset") or {}
    collateral = item.get("collateralAsset") or {}
    state = item.get("state") or {}
    return {
        "market_id": item.get("marketId"),
        "loan": {
            "symbol": loan.get("symbol"),
            "address": loan.get("address"),
        },
        "collateral": {
            "symbol": collateral.get("symbol"),
            "address": collateral.get("address"),
        },
        "total_market_size_usd": _to_float(state.get("sizeUsd")),
        "utilization": _to_float(state.get("utilization")),
    }


def main() -> None:
    args = _build_parser().parse_args()
    if args.top <= 0:
        raise SystemExit("--top 必须大于 0")

    variables = {
        "first": max(args.top, 100),
        "chainIds": [args.chain_id],
        "listed": None if args.include_unlisted else True,
    }
    raw = _post_graphql({"query": QUERY, "variables": variables})
    if raw.get("errors"):
        raise RuntimeError(f"Morpho GraphQL returned errors: {raw['errors']}")

    markets_block = (raw.get("data") or {}).get("markets") or {}
    items = markets_block.get("items") or []
    normalized = [_normalize_item(item) for item in items]
    normalized.sort(key=lambda x: x["total_market_size_usd"], reverse=True)
    top_markets = normalized[: args.top]

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path(__file__).resolve().parents[2] / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = {
        "source": {
            "app_markets_url": APP_MARKETS_URL,
            "graphql_endpoint": GRAPHQL_ENDPOINT,
            "chain_id": args.chain_id,
            "listed_only": not args.include_unlisted,
        },
        "sort": {
            "field": "total_market_size_usd",
            "direction": "desc",
        },
        "total_items_fetched": len(normalized),
        "top_n": args.top,
        "markets": top_markets,
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"exported {len(top_markets)} markets -> {output_path}")


if __name__ == "__main__":
    main()
