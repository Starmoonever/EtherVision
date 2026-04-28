"""Export Morpho vaults (V1 + V2) over USD threshold.

Examples:
    uv run python scripts/morpho/export_vaults_over_10k_usd.py
    uv run python scripts/morpho/export_vaults_over_10k_usd.py --min-usd 50000
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

GRAPHQL_ENDPOINT = "https://api.morpho.org/graphql"
ROOT = Path(__file__).resolve().parent.parent.parent

# api/morpho/vault/export相关：V1 金库列表查询（主网）
V1_VAULTS_QUERY = """
query V1Vaults($first: Int!, $chainId: Int!) {
  vaults(first: $first, where: { chainId_in: [$chainId] }) {
    items {
      address
      asset {
        symbol
      }
      state {
        totalAssetsUsd
      }
    }
  }
}
""".strip()

# api/morpho/vault/export相关：V2 金库列表查询（主网）
V2_VAULTS_QUERY = """
query V2Vaults($first: Int!, $chainId: Int!) {
  vaultV2s(first: $first, where: { chainId_in: [$chainId] }) {
    items {
      address
      asset {
        symbol
      }
      totalAssetsUsd
      liquidityUsd
    }
  }
}
""".strip()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="导出 Morpho 金库（V1+V2）中总资产 USD 超过阈值的列表"
    )
    parser.add_argument("--chain-id", type=int, default=1, help="链 ID，默认 1（主网）")
    parser.add_argument(
        "--min-usd", type=float, default=10000, help="最小总资产 USD 阈值"
    )
    parser.add_argument(
        "--first",
        type=int,
        default=1000,
        help="每类金库拉取条数上限，默认 1000",
    )
    parser.add_argument(
        "--output",
        default="tmp/morpho_vaults_over_10000_usd.json",
        help="输出路径（相对 backend/ 或绝对路径）",
    )
    return parser


def _post_graphql(payload: dict[str, Any]) -> dict[str, Any]:
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
    return json.loads(proc.stdout)


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _resolve_output(path_text: str) -> Path:
    p = Path(path_text)
    if p.is_absolute():
        return p
    return ROOT / p


def main() -> None:
    args = _build_parser().parse_args()

    # api/morpho/vault/export相关：拉取 V1
    v1_body = _post_graphql(
        {
            "query": V1_VAULTS_QUERY,
            "variables": {"first": args.first, "chainId": args.chain_id},
        }
    )
    if v1_body.get("errors"):
        raise RuntimeError(f"V1 vaults GraphQL 错误: {v1_body['errors']}")

    # api/morpho/vault/export相关：拉取 V2
    v2_body = _post_graphql(
        {
            "query": V2_VAULTS_QUERY,
            "variables": {"first": args.first, "chainId": args.chain_id},
        }
    )
    if v2_body.get("errors"):
        raise RuntimeError(f"V2 vaults GraphQL 错误: {v2_body['errors']}")

    rows: list[dict[str, Any]] = []

    for item in ((v1_body.get("data") or {}).get("vaults") or {}).get("items", []):
        if not isinstance(item, dict):
            continue
        usd = _to_float(((item.get("state") or {}).get("totalAssetsUsd")))
        if usd < args.min_usd:
            continue
        rows.append(
            {
                "address": item.get("address"),
                "asset": ((item.get("asset") or {}).get("symbol")),
                "tvl_usd": usd,
                "liquidity_usd": None,
                "protocol": "v1",
            }
        )

    for item in ((v2_body.get("data") or {}).get("vaultV2s") or {}).get("items", []):
        if not isinstance(item, dict):
            continue
        usd = _to_float(item.get("totalAssetsUsd"))
        if usd < args.min_usd:
            continue
        rows.append(
            {
                "address": item.get("address"),
                "asset": ((item.get("asset") or {}).get("symbol")),
                "tvl_usd": usd,
                "liquidity_usd": _to_float(item.get("liquidityUsd")),
                "protocol": "v2",
            }
        )

    rows.sort(key=lambda x: x.get("tvl_usd", 0.0), reverse=True)

    output = {
        "source": "https://app.morpho.org/vaults?v2=false",
        "chain_id": args.chain_id,
        "min_usd": args.min_usd,
        "count": len(rows),
        "items": rows,
    }
    out_path = _resolve_output(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
