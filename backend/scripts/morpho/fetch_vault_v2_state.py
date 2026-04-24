"""Fetch Morpho Vault V2 state JSON and save into backend/tmp.

Examples:
    uv run python scripts/morpho/fetch_vault_v2_state.py \
      --address 0x9a1D6bd5b8642C41F25e0958129B85f8E1176F3e
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

GRAPHQL_ENDPOINT = "https://api.morpho.org/graphql"
ROOT = Path(__file__).resolve().parent.parent.parent
TMP_DIR = ROOT / "tmp"

# api/morpho/vault/state相关：V2 vault 查询字段（可直接落盘为 JSON）
VAULT_V2_QUERY = """
query VaultV2ByAddress($address: String!, $chainId: Int!) {
  vaultV2ByAddress(address: $address, chainId: $chainId) {
    id
    address
    symbol
    name
    type
    listed
    creationBlockNumber
    creationTimestamp
    totalAssets
    totalSupply
    totalAssetsUsd
    idleAssets
    idleAssetsUsd
    liquidity
    liquidityUsd
    sharePrice
    apy
    netApy
    netApyExcludingRewards
    avgNetApy
    avgNetApyExcludingRewards
    maxRate
    maxApy
    forceDeallocatableLiquidity
    forceDeallocatableLiquidityUsd
    performanceFee
    managementFee
    performanceFeeRecipient
    managementFeeRecipient
    liquidityData {
      __typename
    }
    asset {
      address
      symbol
      decimals
    }
    chain {
      id
      network
    }
    owner {
      address
    }
    curator {
      address
    }
    factory {
      address
    }
    gatesConfig {
      sendSharesGate {
        address
        abdicated
        pendingAbdicationExecutableAt
        pendingAddress
        pendingExecutableAt
      }
      receiveAssetsGate {
        address
        abdicated
        pendingAbdicationExecutableAt
        pendingAddress
        pendingExecutableAt
      }
      receiveSharesGate {
        address
        abdicated
        pendingAbdicationExecutableAt
        pendingAddress
        pendingExecutableAt
      }
      sendAssetsGate {
        address
        abdicated
        pendingAbdicationExecutableAt
        pendingAddress
        pendingExecutableAt
      }
    }
    warnings {
      type
      level
      metadata {
        __typename
      }
    }
    metadata {
      description
      image
    }
  }
}
""".strip()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="查询 Morpho V2 金库并写入 tmp JSON")
    parser.add_argument(
        "--address",
        required=True,
        help="Vault V2 地址（EVM）",
    )
    parser.add_argument(
        "--chain-id",
        type=int,
        default=1,
        help="链 ID，默认 1（Ethereum）",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出文件路径（默认写入 backend/tmp/morpho_vault_v2_<address>.json）",
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
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"curl 调用 GraphQL 失败: {(exc.stderr or '').strip()}"
        ) from exc
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GraphQL 返回不是合法 JSON") from exc


def _default_output_path(address: str) -> Path:
    safe = address.lower()
    return TMP_DIR / f"morpho_vault_v2_{safe}.json"


def main() -> None:
    args = _build_parser().parse_args()
    payload = {
        "query": VAULT_V2_QUERY,
        "variables": {"address": args.address, "chainId": args.chain_id},
    }
    body = _post_graphql(payload)
    if body.get("errors"):
        raise RuntimeError(f"GraphQL 返回 errors: {body['errors']}")

    out_path = Path(args.output) if args.output else _default_output_path(args.address)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
