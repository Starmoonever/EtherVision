"""Backfill JustLend market snapshots in strict historical mode.

This script only writes market snapshots reconstructed from historical TRON RPC
reads at a block mapped to each target UTC day. It does not fall back to
current state or live state when historical reads are unavailable.

Examples:
    uv run python scripts/justlend/backfill_market_history_daily.py --start 2026-04-01 --end 2026-04-10
    uv run python scripts/justlend/backfill_market_history_daily.py --start 2026-04-01 --end 2026-04-10 --market TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd
    uv run python scripts/justlend/backfill_market_history_daily.py --start 2026-04-01 --end 2026-04-10 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(os.path.abspath(str(ROOT)))

from crawler_shared.logging import setup_cli_logging  # noqa: E402
from crawler_shared.tron_rpc import build_tron_rpc_client  # noqa: E402
from justlend_crawler.api import service  # noqa: E402
from justlend_crawler.config import load_config  # noqa: E402
from justlend_crawler.db import create_pool, ensure_justlend_tables  # noqa: E402
from justlend_crawler.db import fetch_justlend_market_state_period  # noqa: E402
from justlend_crawler.rpc import (  # noqa: E402
    find_block_at_or_before_timestamp,
    probe_historical_constant_call_support,
)


def _parse_utc_date(value: str) -> date:
    formats = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S")
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise SystemExit(f"unsupported UTC date format: {value}")


def _day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="按天回补 JustLend 市场历史快照，严格依赖历史 TRON RPC 读取"
    )
    parser.add_argument("--config", default=None, help="config.yaml path")
    parser.add_argument("--start", required=True, help="UTC start date")
    parser.add_argument("--end", required=True, help="UTC end date")
    parser.add_argument(
        "--market",
        action="append",
        dest="markets",
        default=None,
        help="target market address, repeatable; default uses config or market API",
    )
    parser.add_argument(
        "--interval-days",
        type=int,
        default=1,
        help="snapshot interval in days; minimum is 1",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=False,
        help="skip days that already have stored snapshots for the market",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="fetch historical states without writing database",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="enable DEBUG logging",
    )
    return parser


async def _resolve_markets(cfg, explicit_markets: list[str] | None) -> list[str]:
    if explicit_markets:
        return [
            normalized
            for market in explicit_markets
            if (normalized := service._normalize_tron_address(market)) is not None
        ]
    configured = getattr(getattr(cfg, "justlend", None), "markets", None) or []
    if configured:
        return [
            normalized
            for market in configured
            if (normalized := service._normalize_tron_address(market)) is not None
        ]
    catalog = await service._fetch_justlend_market_catalog(
        cfg,
        tron_rpc=None,
        market_addresses=[],
    )
    seen: set[str] = set()
    markets: list[str] = []
    for meta in catalog.values():
        if not isinstance(meta, dict):
            continue
        market_address = service._normalize_tron_address(meta.get("market_address"))
        if not market_address or market_address in seen:
            continue
        seen.add(market_address)
        markets.append(market_address)
    return markets


async def _run() -> None:
    args = _build_parser().parse_args()
    setup_cli_logging(args.verbose)

    if args.interval_days < 1:
        raise SystemExit("--interval-days must be >= 1")

    start_day = _parse_utc_date(args.start)
    end_day = _parse_utc_date(args.end)
    if start_day > end_day:
        raise SystemExit("--start must be earlier than or equal to --end")

    cfg = load_config(args.config)
    pool = await create_pool(cfg.postgres)
    tron_rpc = build_tron_rpc_client(
        cfg.tron_rpc_url,
        timeout=float(cfg.crawler.rpc_timeout),
    )

    try:
        if tron_rpc is None:
            raise SystemExit("tron_rpc_url is required for strict historical backfill")

        await ensure_justlend_tables(pool)
        markets = await _resolve_markets(cfg, args.markets)
        if not markets:
            print("no JustLend markets resolved")
            return

        if not await probe_historical_constant_call_support(
            tron_rpc,
            contract_address=markets[0],
        ):
            raise SystemExit(
                "current TRON RPC node does not appear to support historical "
                "triggerconstantcontract(block_number=...)."
            )

        total_rows = 0
        skipped_existing = 0
        current_day = start_day
        while current_day <= end_day:
            point_ts = _day_start(current_day)
            block_number, block_ts = await find_block_at_or_before_timestamp(
                tron_rpc,
                timestamp=point_ts,
            )

            point_markets = markets
            if args.skip_existing:
                pending: list[str] = []
                for market in point_markets:
                    rows = await fetch_justlend_market_state_period(
                        pool,
                        market_address=market,
                        from_ts=point_ts,
                        to_ts=point_ts
                        + timedelta(days=args.interval_days)
                        - timedelta(microseconds=1),
                    )
                    if rows:
                        skipped_existing += 1
                        continue
                    pending.append(market)
                point_markets = pending

            if point_markets:
                rows = await service.fetch_and_optionally_persist_market_states(
                    pool=pool,
                    cfg=cfg,
                    tron_rpc=tron_rpc,
                    market_addresses=point_markets,
                    persist_current=False,
                    persist_snapshots=not args.dry_run,
                    block_number=block_number,
                    snapshot_at=block_ts,
                    require_rpc=True,
                )
                total_rows += len(rows)
                print(
                    f"{current_day.isoformat()} block={block_number} "
                    f"markets={len(rows)} dry_run={args.dry_run}"
                )

            current_day += timedelta(days=args.interval_days)

        print(
            "done: "
            f"markets={len(markets)} "
            f"range={start_day.isoformat()}..{end_day.isoformat()} "
            f"interval_days={args.interval_days} "
            f"written_rows={total_rows} "
            f"skipped_existing={skipped_existing} "
            f"dry_run={args.dry_run}"
        )
    finally:
        if tron_rpc is not None:
            await tron_rpc.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
