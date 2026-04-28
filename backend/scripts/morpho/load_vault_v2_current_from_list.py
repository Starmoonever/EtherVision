"""Load Morpho V2 current tables from exported state JSON.

Input example:
  tmp/morpho_vault_states_over_10000_usd.json

This script reads exported v2/state responses and upserts into:
  - loan.morpho_vault_v2_current
  - loan.morpho_vault_v2_adapters_current
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from morpho_crawler.api.service import _upsert_vault_v2_state_to_table
from morpho_crawler.config import load_config
from morpho_crawler.db import create_pool

ROOT = Path(__file__).resolve().parent.parent.parent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从导出的 v2/state JSON 回填 V2 当前表和 adapters 表"
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


def _extract_v2_vaults(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise ValueError("输入文件格式错误：缺少 items 数组")

    vaults: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("protocol") or "").lower() != "v2":
            continue
        if not row.get("ok"):
            continue
        response = row.get("response") if isinstance(row.get("response"), dict) else {}
        vault = response.get("vaultV2ByAddress") if isinstance(response, dict) else None
        if isinstance(vault, dict) and vault.get("address"):
            vaults.append(vault)
    return vaults


async def _load(args: argparse.Namespace) -> tuple[int, int]:
    payload = json.loads(_resolve_path(args.input).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("输入文件格式错误：顶层必须是对象")

    vaults = _extract_v2_vaults(payload)
    cfg = load_config()
    pool = await create_pool(cfg.postgres)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                if args.truncate:
                    await conn.execute(
                        "TRUNCATE TABLE loan.morpho_vault_v2_adapters_current"
                    )
                    await conn.execute("TRUNCATE TABLE loan.morpho_vault_v2_current")

        for vault in vaults:
            await _upsert_vault_v2_state_to_table(pool, vault=vault)

        async with pool.acquire() as conn:
            current_cnt = await conn.fetchval(
                "SELECT COUNT(*) FROM loan.morpho_vault_v2_current"
            )
            adapters_cnt = await conn.fetchval(
                "SELECT COUNT(*) FROM loan.morpho_vault_v2_adapters_current"
            )
        return int(current_cnt or 0), int(adapters_cnt or 0)
    finally:
        await pool.close()


def main() -> None:
    args = _build_parser().parse_args()
    current_cnt, adapters_cnt = asyncio.run(_load(args))
    print(f"Loaded morpho_vault_v2_current rows: {current_cnt}")
    print(f"Loaded morpho_vault_v2_adapters_current rows: {adapters_cnt}")


if __name__ == "__main__":
    main()
