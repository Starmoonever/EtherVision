"""Backfill JustLend current positions for users derived from history.

Examples:
    uv run python scripts/justlend/backfill_current_positions_from_history.py
    uv run python scripts/justlend/backfill_current_positions_from_history.py --symbol TRX --symbol USDT --match-mode all
    uv run python scripts/justlend/backfill_current_positions_from_history.py --start 2026-04-01 --end 2026-04-17T23:59:59Z --limit 100
    uv run python scripts/justlend/backfill_current_positions_from_history.py --address TVMbWf384CAtzJwge7n7EnzHTfDiwBZ7yZ --dry-run
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

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(os.path.abspath(str(ROOT)))

from crawler_shared.logging import setup_cli_logging  # noqa: E402
from crawler_shared.tron_rpc import build_tron_rpc_client  # noqa: E402
from justlend_crawler.config import load_config  # noqa: E402
from justlend_crawler.current_position_backfill import (  # noqa: E402
    backfill_current_positions_from_history,
)
from justlend_crawler.db import create_pool, fetch_justlend_markets_current  # noqa: E402


def _parse_utc_time(time_str: str) -> datetime:
    formats = (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(time_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise SystemExit(f"unsupported UTC time format: {time_str}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="根据 justlend.justlend_history 选出目标用户，并用链上实时状态全量刷新 current 仓位"
    )
    parser.add_argument("--config", default=None, help="config.yaml path")
    parser.add_argument(
        "--address",
        action="append",
        dest="addresses",
        default=None,
        help="target TRON address, repeatable; skips history scan when provided",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        default=None,
        help="target underlying symbol, repeatable; default is all current JustLend underlyings",
    )
    parser.add_argument(
        "--match-mode",
        choices=("all", "any"),
        default="all",
        help="how target symbols should match history-derived users",
    )
    parser.add_argument(
        "--user-source",
        choices=("history", "current", "union"),
        default="history",
        help="which user set to refresh when --address is not provided",
    )
    parser.add_argument("--start", default=None, help="optional UTC start time")
    parser.add_argument("--end", default=None, help="optional UTC end time")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="max users to process; 0 means no limit",
    )
    parser.add_argument(
        "--market",
        action="append",
        dest="markets",
        default=None,
        help="override RPC market list, repeatable; default uses current market cache",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="scan users and fetch RPC positions without writing database",
    )
    parser.add_argument(
        "--include-failed-history",
        action="store_true",
        default=False,
        help="do not restrict justlend_history scan to successful rows",
    )
    parser.add_argument(
        "--keep-closed",
        action="store_true",
        default=False,
        help="do not delete current rows when the user no longer has an on-chain JustLend position",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=False,
        help="skip users that already exist in loan.justlend_current_user_positions",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="enable DEBUG logging",
    )
    parser.add_argument(
        "--write-failures-jsonl",
        default=None,
        help="optional path to write all failed user reasons as JSONL",
    )
    parser.add_argument(
        "--write-deletions-txt",
        default=None,
        help="optional path to write all deleted user addresses, one per line",
    )
    return parser


def _write_failures_jsonl(path_str: str, items: list[dict[str, str]]) -> None:
    path = Path(path_str).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _write_deletions_txt(path_str: str, items: list[str]) -> None:
    path = Path(path_str).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(f"{item}\n")


async def _resolve_target_symbols(args: argparse.Namespace, pool: Any) -> list[str]:
    if args.symbols:
        return args.symbols
    market_rows = await fetch_justlend_markets_current(pool)
    symbols = sorted(
        {
            str(row["underlying_symbol"]).strip().upper()
            for row in market_rows
            if row.get("underlying_symbol") and str(row["underlying_symbol"]).strip()
        }
    )
    if not symbols:
        raise SystemExit(
            "loan.justlend_markets_current has no underlying_symbol rows; "
            "please populate market cache or pass --symbol explicitly"
        )
    return symbols


async def _run() -> None:
    args = _build_parser().parse_args()
    setup_cli_logging(args.verbose)

    start_time = _parse_utc_time(args.start) if args.start else None
    end_time = _parse_utc_time(args.end) if args.end else None
    if start_time and end_time and start_time > end_time:
        raise SystemExit("--start must be earlier than or equal to --end")

    cfg = load_config(args.config)
    pool = await create_pool(cfg.postgres)
    tron_rpc = build_tron_rpc_client(
        cfg.tron_rpc_url,
        timeout=float(cfg.crawler.rpc_timeout),
    )
    if tron_rpc is None:
        raise SystemExit("tron_rpc_url is required")

    try:
        target_symbols = await _resolve_target_symbols(args, pool)
        stats = await backfill_current_positions_from_history(
            pool,
            cfg=cfg,
            tron_rpc=tron_rpc,
            target_symbols=target_symbols,
            match_mode=args.match_mode,
            start_time=start_time,
            end_time=end_time,
            addresses=args.addresses,
            limit=args.limit,
            dry_run=args.dry_run,
            only_success=not args.include_failed_history,
            delete_closed=not args.keep_closed,
            skip_existing=args.skip_existing,
            market_addresses=args.markets,
            user_source=args.user_source,
        )
        print(
            "done: "
            f"selected={stats.selected_users} "
            f"updated={stats.updated_users} "
            f"deleted={stats.deleted_users} "
            f"skipped={stats.skipped_users} "
            f"failed={stats.failed_users} "
            f"dry_run={args.dry_run} "
            f"user_source={args.user_source}"
        )
        if stats.failed_reason_counts:
            print("failure reasons:")
            for reason, count in sorted(
                stats.failed_reason_counts.items(),
                key=lambda item: (-item[1], item[0]),
            ):
                print(f"  {count} x {reason}")
        if stats.failed_details:
            print("failure samples:")
            for item in stats.failed_details[:20]:
                print(f"  {item['user_address']}: {item['reason']}")
        if stats.deleted_addresses:
            print("deleted address samples:")
            for address in stats.deleted_addresses[:20]:
                print(f"  {address}")
        if args.write_failures_jsonl and stats.failed_details:
            _write_failures_jsonl(args.write_failures_jsonl, stats.failed_details)
            print(f"failure details written to: {args.write_failures_jsonl}")
        if args.write_deletions_txt and stats.deleted_addresses:
            _write_deletions_txt(args.write_deletions_txt, stats.deleted_addresses)
            print(f"deleted addresses written to: {args.write_deletions_txt}")
        if stats.failed_users:
            raise SystemExit(1)
    finally:
        await tron_rpc.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
