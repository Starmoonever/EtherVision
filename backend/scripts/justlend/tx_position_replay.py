"""Run JustLend tx-position replay backfill by reusing API service logic.

Examples:
    uv run python scripts/justlend/tx_position_replay.py --start 2026-04-01 --end 2026-04-10 --limit 20
    uv run python scripts/justlend/tx_position_replay.py --address TGBNfmp8j3rQKm9G6HzzKkrz9DXQpnTf5f --start 2026-04-01 --end 2026-04-10 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(os.path.abspath(str(ROOT)))

from crawler_shared.logging import setup_cli_logging  # noqa: E402
from crawler_shared.tron_rpc import build_tron_rpc_client  # noqa: E402
from justlend_crawler.api.service import (  # noqa: E402
    _tron_bytes_to_base58,
    get_position_replay,
)
from justlend_crawler.config import load_config  # noqa: E402
from justlend_crawler.db import (  # noqa: E402
    create_pool,
    ensure_justlend_tables,
    fetch_justlend_replay_candidate_addresses,
)


def _parse_utc_time(time_str: str) -> int:
    formats = (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            return int(
                datetime.strptime(time_str, fmt)
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
        except ValueError:
            continue
    raise SystemExit(f"unsupported UTC time format: {time_str}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None, help="config.yaml path")
    parser.add_argument(
        "--address",
        action="append",
        dest="addresses",
        default=None,
        help="target TRON address, repeatable; default selects candidate users from justlend_history",
    )
    parser.add_argument("--start", required=True, help="UTC start time")
    parser.add_argument("--end", required=True, help="UTC end time")
    parser.add_argument("--protocol", default="trx", help="protocol selector")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="max addresses to process; 0 means no limit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="rebuild replay points without writing justlend_position_snapshots",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        default=False,
        help="include asset detail payload in replay response",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="ignore existing replay cache and rebuild from history",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="enable DEBUG logging",
    )
    return parser


async def _resolve_addresses(
    *,
    pool,
    start_ts: int,
    end_ts: int,
    raw_addresses: list[str] | None,
    limit: int,
) -> list[str]:
    if raw_addresses:
        addresses = [addr.strip() for addr in raw_addresses if addr.strip()]
        return addresses[:limit] if limit > 0 else addresses

    user_rows = await fetch_justlend_replay_candidate_addresses(
        pool,
        from_dt=datetime.fromtimestamp(start_ts, tz=timezone.utc),
        to_dt=datetime.fromtimestamp(end_ts, tz=timezone.utc),
        only_success=True,
        limit=limit,
    )
    return [_tron_bytes_to_base58(user) for user in user_rows]


async def _run() -> None:
    args = _build_parser().parse_args()
    setup_cli_logging(args.verbose)

    start_ts = _parse_utc_time(args.start)
    end_ts = _parse_utc_time(args.end)
    if start_ts > end_ts:
        raise SystemExit("--start must be earlier than or equal to --end")

    cfg = load_config(args.config)
    pool = await create_pool(cfg.postgres)
    tron_rpc = build_tron_rpc_client(
        cfg.tron_rpc_url,
        timeout=float(cfg.crawler.rpc_timeout),
    )

    try:
        await ensure_justlend_tables(pool)
        addresses = await _resolve_addresses(
            pool=pool,
            start_ts=start_ts,
            end_ts=end_ts,
            raw_addresses=args.addresses,
            limit=args.limit,
        )
        if not addresses:
            print("no JustLend replay candidates found")
            return

        ok = 0
        failed = 0
        total_points = 0
        total_txs = 0
        for index, address in enumerate(addresses, start=1):
            try:
                result = await get_position_replay(
                    pool=pool,
                    cfg=cfg,
                    tron_rpc=tron_rpc,
                    address=address,
                    protocol=args.protocol,
                    from_ts=start_ts,
                    to_ts=end_ts,
                    use_cache=not args.no_cache,
                    detail=args.detail,
                    persist_cache=not args.dry_run,
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"[{index}/{len(addresses)}] {address} failed: {exc}")
                continue

            ok += 1
            total_points += result.total_points
            total_txs += result.total_tx_count
            print(
                f"[{index}/{len(addresses)}] {address} "
                f"txs={result.total_tx_count} points={result.total_points} "
                f"source={result.data_source} cache_hit_rate={result.cache_hit_rate}"
            )

        label = "dry-run " if args.dry_run else ""
        print(
            f"{label}done: addresses={len(addresses)} ok={ok} failed={failed} "
            f"txs={total_txs} points={total_points}"
        )
        if failed:
            raise SystemExit(1)
    finally:
        if tron_rpc is not None:
            await tron_rpc.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
