"""Repair JustLend current-position rows with incorrect collateral side labels.

Examples:
    uv run python scripts/justlend/repair_current_collateral_sides.py --dry-run
    uv run python scripts/justlend/repair_current_collateral_sides.py
    uv run python scripts/justlend/repair_current_collateral_sides.py --address TVMbWf384CAtzJwge7n7EnzHTfDiwBZ7yZ
    uv run python scripts/justlend/repair_current_collateral_sides.py --limit 100
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(os.path.abspath(str(ROOT)))

from crawler_shared.logging import setup_cli_logging  # noqa: E402
from justlend_crawler.api.service import (  # noqa: E402
    _tron_address_to_bytes,
    _tron_bytes_to_base58,
)
from justlend_crawler.config import load_config  # noqa: E402
from justlend_crawler.db import create_pool, ensure_justlend_tables  # noqa: E402

_MAX_HF = Decimal("1e18")


@dataclass(slots=True)
class RepairStats:
    selected_users: int = 0
    updated_users: int = 0
    fixed_assets: int = 0
    skipped_users: int = 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "修复 loan.justlend_current_user_position_assets 中误标为 "
            "side=collateral 且 entered=false 的供给资产，并重算 current 汇总"
        )
    )
    parser.add_argument("--config", default=None, help="config.yaml path")
    parser.add_argument(
        "--address",
        action="append",
        dest="addresses",
        default=None,
        help="target TRON address, repeatable; default scans all affected users",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="max users to repair; 0 means no limit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="print affected users/assets without writing database",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="enable DEBUG logging",
    )
    return parser


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _bool_from_extra(extra_jsonb: Any, key: str) -> bool:
    if not isinstance(extra_jsonb, dict):
        return False
    value = extra_jsonb.get(key)
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def _effective_collateral_flag(extra_jsonb: Any) -> bool | None:
    if not isinstance(extra_jsonb, dict):
        return None
    if "entered" in extra_jsonb:
        return _bool_from_extra(extra_jsonb, "entered")
    if "is_collateral" in extra_jsonb:
        return _bool_from_extra(extra_jsonb, "is_collateral")
    return None


def _normalized_asset_side(side: str, extra_jsonb: Any) -> str:
    if side not in {"collateral", "supply"}:
        return side
    effective_flag = _effective_collateral_flag(extra_jsonb)
    if effective_flag is None:
        return side
    return "collateral" if effective_flag else "supply"


async def _fetch_target_users(
    pool: Any,
    *,
    user_addresses: list[bytes] | None,
    limit: int,
) -> list[bytes]:
    params: list[Any] = []
    where_clauses = [
        """(
            side IN ('collateral', 'supply')
            AND (
                (
                    extra_jsonb ? 'entered'
                    AND (
                        (
                            COALESCE(extra_jsonb->>'entered', 'false') = 'true'
                            AND side = 'supply'
                        )
                        OR (
                            COALESCE(extra_jsonb->>'entered', 'false') = 'false'
                            AND side = 'collateral'
                        )
                    )
                )
                OR (
                    NOT (extra_jsonb ? 'entered')
                    AND extra_jsonb ? 'is_collateral'
                    AND (
                        (
                            COALESCE(extra_jsonb->>'is_collateral', 'false') = 'true'
                            AND side = 'supply'
                        )
                        OR (
                            COALESCE(extra_jsonb->>'is_collateral', 'false') = 'false'
                            AND side = 'collateral'
                        )
                    )
                )
            )
        )"""
    ]
    if user_addresses:
        params.append(user_addresses)
        where_clauses.append(f"user_address = ANY(${len(params)}::bytea[])")
    limit_sql = ""
    if limit > 0:
        params.append(limit)
        limit_sql = f"LIMIT ${len(params)}"

    sql = f"""
        SELECT DISTINCT user_address
        FROM loan.justlend_current_user_position_assets
        WHERE {" AND ".join(where_clauses)}
        ORDER BY user_address
        {limit_sql}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(*([sql] + params))
    return [bytes(row["user_address"]) for row in rows]


async def _fetch_user_assets(conn: Any, *, user_address: bytes) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT
            asset_address,
            side,
            value_usd,
            extra_jsonb
        FROM loan.justlend_current_user_position_assets
        WHERE user_address = $1
        ORDER BY value_usd DESC, asset_address, side
        """,
        user_address,
    )
    return [dict(row) for row in rows]


async def _repair_user(
    conn: Any, *, user_address: bytes, dry_run: bool
) -> tuple[int, bool]:
    assets = await _fetch_user_assets(conn, user_address=user_address)
    fixed_assets = 0
    total_collateral_usd = Decimal("0")
    total_debt_usd = Decimal("0")
    discounted_collateral_usd = Decimal("0")

    for asset in assets:
        extra_jsonb = asset.get("extra_jsonb") or {}
        side = str(asset.get("side") or "")
        value_usd = _decimal(asset.get("value_usd"))
        collateral_factor = _decimal(
            (extra_jsonb if isinstance(extra_jsonb, dict) else {}).get(
                "collateral_factor", "0"
            )
        )
        normalized_side = _normalized_asset_side(side, extra_jsonb)
        if normalized_side != side:
            fixed_assets += 1
        if normalized_side == "collateral":
            total_collateral_usd += value_usd
            discounted_collateral_usd += value_usd * collateral_factor
        elif normalized_side == "borrow":
            total_debt_usd += value_usd

    if fixed_assets == 0:
        return 0, False

    available_borrow_usd = max(discounted_collateral_usd - total_debt_usd, Decimal("0"))
    health_factor = (
        discounted_collateral_usd / total_debt_usd
        if total_debt_usd > 0
        else (_MAX_HF if total_collateral_usd > 0 else Decimal("0"))
    )
    ltv = (
        total_debt_usd / total_collateral_usd
        if total_collateral_usd > 0
        else Decimal("0")
    )
    liquidation_threshold = (
        discounted_collateral_usd / total_collateral_usd
        if total_collateral_usd > 0
        else Decimal("0")
    )

    if dry_run:
        return fixed_assets, True

    await conn.execute(
        """
        UPDATE loan.justlend_current_user_position_assets
        SET side = CASE
                WHEN side NOT IN ('collateral', 'supply') THEN side
                WHEN extra_jsonb ? 'entered'
                    THEN CASE
                        WHEN COALESCE(extra_jsonb->>'entered', 'false') = 'true'
                            THEN 'collateral'
                        ELSE 'supply'
                    END
                WHEN extra_jsonb ? 'is_collateral'
                    THEN CASE
                        WHEN COALESCE(extra_jsonb->>'is_collateral', 'false') = 'true'
                            THEN 'collateral'
                        ELSE 'supply'
                    END
                ELSE side
            END,
            updated_at = NOW()
        WHERE user_address = $1
          AND side IN ('collateral', 'supply')
          AND (
                (
                    extra_jsonb ? 'entered'
                    AND (
                        (
                            COALESCE(extra_jsonb->>'entered', 'false') = 'true'
                            AND side = 'supply'
                        )
                        OR (
                            COALESCE(extra_jsonb->>'entered', 'false') = 'false'
                            AND side = 'collateral'
                        )
                    )
                )
                OR (
                    NOT (extra_jsonb ? 'entered')
                    AND extra_jsonb ? 'is_collateral'
                    AND (
                        (
                            COALESCE(extra_jsonb->>'is_collateral', 'false') = 'true'
                            AND side = 'supply'
                        )
                        OR (
                            COALESCE(extra_jsonb->>'is_collateral', 'false') = 'false'
                            AND side = 'collateral'
                        )
                    )
                )
          )
        """,
        user_address,
    )
    await conn.execute(
        """
        UPDATE loan.justlend_current_user_positions
        SET total_collateral_usd = $2,
            total_debt_usd = $3,
            available_borrow_usd = $4,
            health_factor = $5,
            ltv = $6,
            liquidation_threshold = $7,
            updated_at = NOW()
        WHERE user_address = $1
        """,
        user_address,
        total_collateral_usd,
        total_debt_usd,
        available_borrow_usd,
        health_factor,
        ltv,
        liquidation_threshold,
    )
    return fixed_assets, True


async def _run() -> None:
    args = _build_parser().parse_args()
    setup_cli_logging(args.verbose)

    cfg = load_config(args.config)
    pool = await create_pool(cfg.postgres)

    address_filters = (
        [_tron_address_to_bytes(address) for address in args.addresses]
        if args.addresses
        else None
    )
    try:
        await ensure_justlend_tables(pool)
        target_users = await _fetch_target_users(
            pool,
            user_addresses=address_filters,
            limit=args.limit,
        )
        stats = RepairStats(selected_users=len(target_users))

        async with pool.acquire() as conn:
            for user_address in target_users:
                async with conn.transaction():
                    fixed_assets, changed = await _repair_user(
                        conn,
                        user_address=user_address,
                        dry_run=args.dry_run,
                    )
                if not changed:
                    stats.skipped_users += 1
                    continue
                stats.updated_users += 1
                stats.fixed_assets += fixed_assets
                print(
                    f"user={_tron_bytes_to_base58(user_address)} "
                    f"fixed_assets={fixed_assets} "
                    f"dry_run={args.dry_run}"
                )

        print(
            "done: "
            f"selected={stats.selected_users} "
            f"updated={stats.updated_users} "
            f"skipped={stats.skipped_users} "
            f"fixed_assets={stats.fixed_assets} "
            f"dry_run={args.dry_run}"
        )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
