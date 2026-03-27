"""Backfill Compound v3 current positions from derived user CSVs."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from crawler_shared.logging import setup_cli_logging

from compound_crawler.config import load_config
from compound_crawler.constants import COMPOUND_V3_MARKET_NAMES
from compound_crawler.crawler import _block_at_timestamp, _build_web3, close_web3
from compound_crawler.db import (
    create_pool,
    ensure_compound_v3_current_position_tables,
    refresh_compound_v3_current_positions,
)
from compound_crawler.user_position_snapshots import (
    _chunked,
    _collect_user_snapshots_batch,
    _load_market_context,
    _load_users_from_csv,
    _parse_utc_time,
    _resolve_market_address,
    available_csv_markets,
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
    parser.add_argument(
        "--time",
        default=None,
        help="UTC timestamp to evaluate; default uses latest block",
    )
    parser.add_argument(
        "--derived-users-dir",
        default="derived_users",
        help="directory containing compound_v3_{market}_users.csv files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="collect without writing to current position tables",
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

    cfg = load_config(args.config)
    cfg.protocol = "v3"
    point_ts = _parse_utc_time(args.time) if args.time else None

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        w3 = None
        try:
            w3 = await _build_web3(cfg)
            await ensure_compound_v3_current_position_tables(pool)

            for market_name in markets:
                market_address = _resolve_market_address(market_name)
                market_symbol = COMPOUND_V3_MARKET_NAMES[market_address]
                csv_path = (
                    derived_users_dir / f"compound_v3_{market_symbol.lower()}_users.csv"
                )
                if not csv_path.exists():
                    raise FileNotFoundError(f"missing user csv: {csv_path}")

                users = _load_users_from_csv(csv_path)
                if not users:
                    print(f"[{market_symbol}] no users found in {csv_path}, skipping")
                    continue

                if point_ts is None:
                    latest_block = await w3.eth.get_block("latest")
                    latest_timestamp = latest_block.get("timestamp")
                    latest_number = latest_block.get("number")
                    if latest_timestamp is None or latest_number is None:
                        raise RuntimeError("latest block missing timestamp or number")
                    market_point_ts = datetime.fromtimestamp(
                        int(latest_timestamp), tz=timezone.utc
                    )
                    block_number = int(latest_number)
                else:
                    market_point_ts = point_ts
                    block_number = await _block_at_timestamp(
                        w3, int(market_point_ts.timestamp()), pool=pool
                    )

                metadata_cache: dict[str, tuple[str | None, int | None]] = {}
                market_ctx = await _load_market_context(
                    w3,
                    market_address=market_address,
                    block_number=block_number,
                    metadata_cache=metadata_cache,
                )

                snapshot_rows = []
                asset_rows = []
                empty_rows = 0
                for user_batch in _chunked(users, max(1, cfg.crawler.batch_size)):
                    results = await _collect_user_snapshots_batch(
                        w3,
                        market_ctx=market_ctx,
                        user_addresses=user_batch,
                        point_ts=market_point_ts,
                        block_number=block_number,
                    )
                    for snapshot_row, asset_row_group in results:
                        snapshot_rows.append(snapshot_row)
                        if snapshot_row.has_open_position:
                            asset_rows.extend(asset_row_group)
                        else:
                            empty_rows += 1

                open_rows = sum(1 for row in snapshot_rows if row.has_open_position)
                if args.dry_run:
                    print(
                        f"[{market_symbol}] dry-run block={block_number} users={len(users)} "
                        f"open={open_rows} empty={empty_rows}"
                    )
                    continue

                touched = await refresh_compound_v3_current_positions(
                    pool,
                    snapshot_rows=snapshot_rows,
                    asset_rows=asset_rows,
                )
                print(
                    f"[{market_symbol}] block={block_number} users={len(users)} "
                    f"open={open_rows} empty={empty_rows} touched={touched}"
                )
        finally:
            await close_web3(w3)
            await pool.close()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
