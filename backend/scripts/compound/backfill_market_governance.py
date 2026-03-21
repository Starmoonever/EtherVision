"""Backfill Compound v3 market governance and status snapshots."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from crawler_shared.logging import setup_cli_logging
from compound_crawler.config import load_config
from compound_crawler.crawler import run_crawler
from compound_crawler.db import create_pool
from compound_crawler.user_position_snapshots import _parse_utc_time


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None, help="config.yaml path")
    parser.add_argument("--start", default=None, help="UTC start date/time")
    parser.add_argument("--end", default=None, help="UTC end date/time")
    parser.add_argument(
        "--interval",
        type=int,
        default=24,
        help="sampling interval in hours",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=False,
        help="skip points where market/governance rows already exist",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="collect without writing to database",
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

    if args.interval < 1:
        raise SystemExit("--interval must be >= 1 hour")

    cfg = load_config(args.config)
    cfg.protocol = "v3"

    start = _parse_utc_time(args.start) if args.start else None
    end = _parse_utc_time(args.end) if args.end else None

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await run_crawler(
                cfg,
                pool,
                start_at=start,
                end_at=end,
                interval_hours=args.interval,
                skip_existing=args.skip_existing,
                dry_run=args.dry_run,
                include_market_state=False,
                include_governance=True,
            )
        finally:
            await pool.close()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
