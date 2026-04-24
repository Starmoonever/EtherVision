"""Inspect an address on Ethereum and dump onchain details to JSON.

Examples:
    uv run python scripts/morpho/inspect_address_onchain.py \
      --address 0x19b3cD7032B8C062E8d44EaCad661a0970DD8c55
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from web3 import AsyncHTTPProvider, AsyncWeb3

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(os.path.abspath(str(ROOT)))

from morpho_crawler.config import load_config  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="查询单个地址链上信息并输出 JSON")
    parser.add_argument(
        "--address",
        required=True,
        help="目标地址（EVM）",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出路径（默认写入 backend/tmp/inspect_<address>.json）",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="config.yaml 路径（默认自动查找）",
    )
    return parser


async def _safe_call(contract, fn_name: str) -> dict[str, Any]:
    try:
        value = await getattr(contract.functions, fn_name)().call()
        return {"ok": True, "value": value}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _json_default(value: Any) -> Any:
    if isinstance(value, bytes):
        return "0x" + value.hex()
    return str(value)


async def _run() -> None:
    args = _build_parser().parse_args()
    cfg = load_config(args.config)
    if not cfg.eth_rpc_url:
        raise RuntimeError("config 中 eth_rpc_url 为空，无法查询链上信息")

    w3 = AsyncWeb3(AsyncHTTPProvider(cfg.eth_rpc_url))
    checksum = AsyncWeb3.to_checksum_address(args.address)

    latest_block, chain_id, code, balance_wei, nonce = await asyncio.gather(
        w3.eth.get_block("latest"),
        w3.eth.chain_id,
        w3.eth.get_code(checksum),
        w3.eth.get_balance(checksum),
        w3.eth.get_transaction_count(checksum),
    )

    # 常见 ERC20 / ERC4626 / Vault 字段（尽量覆盖基金层常用读取）
    abi = [
        {
            "name": "name",
            "type": "function",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"type": "string"}],
        },
        {
            "name": "symbol",
            "type": "function",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"type": "string"}],
        },
        {
            "name": "decimals",
            "type": "function",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"type": "uint8"}],
        },
        {
            "name": "totalSupply",
            "type": "function",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"type": "uint256"}],
        },
        {
            "name": "owner",
            "type": "function",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"type": "address"}],
        },
        {
            "name": "asset",
            "type": "function",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"type": "address"}],
        },
        {
            "name": "totalAssets",
            "type": "function",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"type": "uint256"}],
        },
        {
            "name": "curator",
            "type": "function",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"type": "address"}],
        },
        {
            "name": "guardian",
            "type": "function",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"type": "address"}],
        },
        {
            "name": "timelock",
            "type": "function",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"type": "uint256"}],
        },
        {
            "name": "fee",
            "type": "function",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"type": "uint256"}],
        },
    ]
    contract = w3.eth.contract(address=checksum, abi=abi)

    call_names = [
        "name",
        "symbol",
        "decimals",
        "totalSupply",
        "owner",
        "asset",
        "totalAssets",
        "curator",
        "guardian",
        "timelock",
        "fee",
    ]
    call_results = await asyncio.gather(*[_safe_call(contract, n) for n in call_names])

    functions: dict[str, Any] = {}
    for name, res in zip(call_names, call_results, strict=True):
        functions[name] = res

    out = {
        "query": {
            "address_input": args.address,
            "address_checksum": checksum,
            "queried_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        },
        "rpc": {
            "chain_id": chain_id,
            "latest_block_number": latest_block.get("number"),
        },
        "basic": {
            "is_contract": len(code) > 0,
            "code_size_bytes": len(code),
            "code_hex_prefix": "0x" + code.hex()[:128],
            "native_balance_wei": balance_wei,
            "nonce": nonce,
        },
        "functions": functions,
    }

    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = ROOT / output_path
    else:
        filename = f"inspect_{checksum.lower()}.json"
        output_path = ROOT / "tmp" / filename

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    print(f"written -> {output_path}")


if __name__ == "__main__":
    asyncio.run(_run())
