"""Fetch and persist latest JustLend market states.

Examples:
    uv run python scripts/justlend/market_state_backfill.py --dry-run
    uv run python scripts/justlend/market_state_backfill.py --market TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd
    uv run python scripts/justlend/market_state_backfill.py --limit 10 --skip-snapshots
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
from justlend_crawler.api.service import (  # noqa: E402
    fetch_and_optionally_persist_market_states,
)
from justlend_crawler.config import load_config  # noqa: E402
from justlend_crawler.db import create_pool, ensure_justlend_tables  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="回填 JustLend 市场最新状态到 current/snapshot 表"
    )
    parser.add_argument("--config", default=None, help="config.yaml path")
    parser.add_argument(
        "--market",
        action="append",
        dest="markets",
        default=None,
        help="target market address, repeatable; default uses config or all API markets",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="max markets to process; 0 means no limit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="fetch market states without writing database",
    )
    parser.add_argument(
        "--skip-current",
        action="store_true",
        default=False,
        help="do not update justlend_markets_current",
    )
    parser.add_argument(
        "--skip-snapshots",
        action="store_true",
        default=False,
        help="do not insert justlend_market_snapshots",
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

    try:
        await ensure_justlend_tables(pool)
        rows = await fetch_and_optionally_persist_market_states(
            pool=pool,
            cfg=cfg,
            tron_rpc=tron_rpc,
            market_addresses=args.markets,
            limit=args.limit,
            persist_current=not args.dry_run and not args.skip_current,
            persist_snapshots=not args.dry_run and not args.skip_snapshots,
        )
        print(
            "done: "
            f"markets={len(rows)} "
            f"dry_run={args.dry_run} "
            f"update_current={not args.skip_current} "
            f"insert_snapshots={not args.skip_snapshots}"
        )
        for row in rows[:10]:
            print(
                f"{row.market_address} "
                f"symbol={row.symbol or '-'} "
                f"underlying={row.underlying_symbol or '-'} "
                f"price_usd={row.price_usd if row.price_usd is not None else '-'} "
                f"utilization={row.utilization if row.utilization is not None else '-'}"
            )
    finally:
        if tron_rpc is not None:
            await tron_rpc.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
