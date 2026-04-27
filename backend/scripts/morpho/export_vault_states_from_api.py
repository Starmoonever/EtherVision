"""Export full vault states by calling local Morpho API endpoints.

Reads a vault list JSON (e.g. tmp/morpho_vaults_over_10000_usd.json), then calls:
- /api/morpho/vault/v1/state?address=...
- /api/morpho/vault/v2/state?address=...

and writes a merged JSON with success/error details.

Examples:
    uv run python scripts/morpho/export_vault_states_from_api.py
    uv run python scripts/morpho/export_vault_states_from_api.py --concurrency 16
    uv run python scripts/morpho/export_vault_states_from_api.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="按金库列表调用 v1/v2 state 接口并导出全量状态 JSON"
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
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="本地 API 基础地址",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=12,
        help="并发请求数，默认 12",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=40.0,
        help="单请求超时秒数，默认 40",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="失败重试次数，默认 2（总尝试次数 = retries + 1）",
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


def _path_for_protocol(protocol: str) -> str:
    if protocol == "v1":
        return "/api/morpho/vault/v1/state"
    return "/api/morpho/vault/v2/state"


async def _fetch_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    *,
    base_url: str,
    address: str,
    protocol: str,
    retries: int,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{_path_for_protocol(protocol)}"
    params = {"address": address}
    attempts = retries + 1
    last_error = "unknown"
    t0 = time.time()
    for i in range(attempts):
        try:
            async with sem:
                resp = await client.get(url, params=params)
            if resp.status_code == 200:
                body = resp.json()
                return {
                    "address": address,
                    "protocol": protocol,
                    "ok": True,
                    "elapsed_ms": int((time.time() - t0) * 1000),
                    "status_code": 200,
                    "response": body,
                }
            last_error = f"http_{resp.status_code}: {resp.text[:300]}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        if i < attempts - 1:
            await asyncio.sleep(0.35 * (i + 1))
    return {
        "address": address,
        "protocol": protocol,
        "ok": False,
        "elapsed_ms": int((time.time() - t0) * 1000),
        "error": last_error,
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    items = _load_items(_resolve_path(args.input))
    sem = asyncio.Semaphore(max(1, args.concurrency))
    timeout = httpx.Timeout(args.timeout)
    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [
            _fetch_one(
                client,
                sem,
                base_url=args.base_url,
                address=str(it["address"]),
                protocol=str(it["protocol"]).lower(),
                retries=args.retries,
            )
            for it in items
        ]
        results = await asyncio.gather(*tasks)

    successes = [r for r in results if r.get("ok")]
    failures = [r for r in results if not r.get("ok")]
    return {
        "meta": {
            "source_input": str(args.input),
            "base_url": args.base_url,
            "requested": len(items),
            "success_count": len(successes),
            "failure_count": len(failures),
            "concurrency": args.concurrency,
            "timeout": args.timeout,
            "retries": args.retries,
        },
        "successes": successes,
        "failures": failures,
    }


def main() -> None:
    args = _build_parser().parse_args()
    out = asyncio.run(_run(args))
    out_path = _resolve_path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote: {out_path}")
    print(
        "Summary:",
        out["meta"]["requested"],
        "requested,",
        out["meta"]["success_count"],
        "success,",
        out["meta"]["failure_count"],
        "failed",
    )


if __name__ == "__main__":
    main()
