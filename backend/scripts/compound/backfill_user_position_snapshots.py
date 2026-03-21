"""Backfill Compound v3 user position snapshots from derived user CSVs."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from crawler_shared.logging import setup_cli_logging
from compound_crawler.config import load_config
from compound_crawler.db import create_pool
from compound_crawler.user_position_snapshots import (
    MIN_INTERVAL_DAYS,
    _parse_utc_time,
    available_csv_markets,
    run_user_position_backfill,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None, help="config.yaml path")
    parser.add_argument(
        "--market",
        action="append",
        dest="markets",
        default=None,
        help="target market name, repeatable; default uses all available CSVs",
    )
    parser.add_argument("--start", default=None, help="UTC start date/time")
    parser.add_argument("--end", default=None, help="UTC end date/time")
    parser.add_argument(
        "--interval",
        type=int,
        default=MIN_INTERVAL_DAYS,
        help=f"sampling interval in days (min {MIN_INTERVAL_DAYS})",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=False,
        help="skip existing (timestamp, market, user_address) rows",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="collect without writing to database",
    )
    parser.add_argument(
        "--derived-users-dir",
        default="derived_users",
        help="directory containing compound_v3_{market}_users.csv files",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="enable DEBUG logging",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    setup_cli_logging(args.verbose)

    derived_users_dir = Path(args.derived_users_dir)
    markets = [
        m.lower() for m in (args.markets or available_csv_markets(derived_users_dir))
    ]
    if not markets:
        raise SystemExit("no compound_v3_{market}_users.csv files found")
    if args.interval < MIN_INTERVAL_DAYS:
        raise SystemExit(f"--interval must be >= {MIN_INTERVAL_DAYS} day(s)")

    cfg = load_config(args.config)
    cfg.protocol = "v3"

    start = _parse_utc_time(args.start) if args.start else None
    end = _parse_utc_time(args.end) if args.end else None

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await run_user_position_backfill(
                cfg,
                pool,
                markets=markets,
                derived_users_dir=derived_users_dir,
                start=start,
                end=end,
                interval_days=args.interval,
                skip_existing=args.skip_existing,
                dry_run=args.dry_run,
            )
        finally:
            await pool.close()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
