"""Repair JustLend market/current-position prices after oracle scale fixes.

Examples:
    uv run python scripts/justlend/repair_current_prices.py
    uv run python scripts/justlend/repair_current_prices.py --dry-run
    uv run python scripts/justlend/repair_current_prices.py --user-source current --limit 200
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(os.path.abspath(str(ROOT)))

from crawler_shared.logging import setup_cli_logging  # noqa: E402
from crawler_shared.tron_rpc import build_tron_rpc_client  # noqa: E402
from justlend_crawler.api.service import fetch_and_optionally_persist_market_states  # noqa: E402
from justlend_crawler.config import load_config  # noqa: E402
from justlend_crawler.current_position_backfill import (  # noqa: E402
    backfill_current_positions_from_history,
)
from justlend_crawler.db import create_pool, ensure_justlend_tables  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="整体重算 JustLend 市场价格与 current position 价格"
    )
    parser.add_argument("--config", default=None, help="config.yaml path")
    parser.add_argument(
        "--user-source",
        choices=("history", "current", "union"),
        default="union",
        help="which user set to refresh for current positions",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        default=None,
        help="target underlying symbol, repeatable; default is TRX and USDT",
    )
    parser.add_argument(
        "--match-mode",
        choices=("all", "any"),
        default="any",
        help="how target symbols should match history-derived users when history is used",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="max users to process; 0 means no limit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="fetch repair data without writing database",
    )
    parser.add_argument(
        "--skip-markets",
        action="store_true",
        default=False,
        help="skip refreshing loan.justlend_markets_current",
    )
    parser.add_argument(
        "--keep-closed",
        action="store_true",
        default=False,
        help="do not delete current rows when the user no longer has an on-chain JustLend position",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="enable DEBUG logging",
    )
    return parser


async def _run() -> None:
    args = _build_parser().parse_args()
    setup_cli_logging(args.verbose)

    cfg = load_config(args.config)
    pool = await create_pool(cfg.postgres)
    tron_rpc = build_tron_rpc_client(
        cfg.tron_rpc_url,
        timeout=float(cfg.crawler.rpc_timeout),
    )
    if tron_rpc is None:
        raise SystemExit("tron_rpc_url is required")

    try:
        await ensure_justlend_tables(pool)
        market_rows = []
        if not args.skip_markets:
            market_rows = await fetch_and_optionally_persist_market_states(
                pool=pool,
                cfg=cfg,
                tron_rpc=tron_rpc,
                persist_current=not args.dry_run,
                persist_snapshots=not args.dry_run,
            )

        stats = await backfill_current_positions_from_history(
            pool,
            cfg=cfg,
            tron_rpc=tron_rpc,
            target_symbols=args.symbols or ["TRX", "USDT"],
            match_mode=args.match_mode,
            limit=args.limit,
            dry_run=args.dry_run,
            only_success=True,
            delete_closed=not args.keep_closed,
            user_source=args.user_source,
        )
        print(
            "done: "
            f"markets={len(market_rows)} "
            f"selected={stats.selected_users} "
            f"updated={stats.updated_users} "
            f"deleted={stats.deleted_users} "
            f"skipped={stats.skipped_users} "
            f"failed={stats.failed_users} "
            f"dry_run={args.dry_run} "
            f"user_source={args.user_source}"
        )
        if stats.failed_users:
            raise SystemExit(1)
    finally:
        await tron_rpc.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
