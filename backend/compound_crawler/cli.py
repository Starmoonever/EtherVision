"""Click CLI entrypoint for Compound crawler."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import click
from crawler_shared.logging import setup_cli_logging

from .config import load_config
from .crawler import run_crawler
from .db import create_pool, ensure_market_state_tables
from .watcher import run_watcher


def _setup_logging(verbose: bool) -> None:
    setup_cli_logging(verbose)


@click.group()
def cli() -> None:
    """Compound crawler tools"""


@cli.command("crawl_market_state")
@click.option("--config", "-c", default=None, help="config.yaml path")
@click.option(
    "--protocol",
    "-p",
    default="v3",
    type=click.Choice(["v2", "v3"]),
    show_default=True,
    help="Compound protocol version",
)
@click.option(
    "--start",
    type=click.DateTime(formats=["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]),
    default=None,
    help="Range start in UTC (e.g. 2026-03-01 or 2026-03-01T00:00:00)",
)
@click.option(
    "--end",
    type=click.DateTime(formats=["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]),
    default=None,
    help="Range end in UTC (inclusive)",
)
@click.option(
    "--interval",
    "-i",
    type=click.IntRange(min=1),
    default=1,
    show_default=True,
    help="Sampling interval in hours",
)
@click.option(
    "--skip-existing",
    is_flag=True,
    default=False,
    help="Skip existing rows by (timestamp, market, reserve)",
)
@click.option("--dry-run", is_flag=True, default=False, help="Do not write to database")
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable DEBUG logging"
)
def cmd_crawl_market_state(
    config: str | None,
    protocol: str,
    start: datetime | None,
    end: datetime | None,
    interval: int,
    skip_existing: bool,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Collect Compound market state snapshots in a time range."""
    _setup_logging(verbose)
    cfg = load_config(config)
    cfg.protocol = protocol

    start_at = (
        start.replace(tzinfo=timezone.utc) if start and start.tzinfo is None else start
    )
    end_at = end.replace(tzinfo=timezone.utc) if end and end.tzinfo is None else end
    if start_at and end_at and start_at > end_at:
        raise click.BadParameter("--end must be greater than or equal to --start")

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await run_crawler(
                cfg,
                pool,
                start_at=start_at,
                end_at=end_at,
                interval_hours=interval,
                skip_existing=skip_existing,
                dry_run=dry_run,
            )
        finally:
            await pool.close()

    asyncio.run(_run())


@cli.command("watch")
@click.option("--config", "-c", default=None, help="config.yaml path")
@click.option(
    "--protocol",
    "-p",
    default="v3",
    type=click.Choice(["v2", "v3"]),
    show_default=True,
    help="Compound protocol version",
)
@click.option(
    "--interval", "-i", default=60, type=int, help="Polling interval in seconds"
)
@click.option(
    "--lookback", "-l", default=10, type=int, help="Lookback window in minutes"
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable DEBUG logging"
)
def cmd_watch(
    config: str | None,
    protocol: str,
    interval: int,
    lookback: int,
    verbose: bool,
) -> None:
    _setup_logging(verbose)
    cfg = load_config(config)
    cfg.protocol = protocol

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await run_watcher(cfg, pool, interval=interval, lookback_minutes=lookback)
        finally:
            await pool.close()

    asyncio.run(_run())


@cli.command("init_market_state")
@click.option("--config", "-c", default=None, help="config.yaml path")
@click.option(
    "--protocol",
    "-p",
    default="all",
    type=click.Choice(["v2", "v3", "all"]),
    show_default=True,
    help="Target protocol version(s)",
)
@click.option(
    "--timescale/--no-timescale",
    default=None,
    help="Enable TimescaleDB hypertable when extension exists",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable DEBUG logging"
)
def cmd_init_market_state(
    config: str | None,
    protocol: str,
    timescale: bool | None,
    verbose: bool,
) -> None:
    """Create Compound market_state tables under loan schema."""
    _setup_logging(verbose)
    cfg = load_config(config)
    use_timescaledb = (
        cfg.market_state.use_timescaledb if timescale is None else timescale
    )

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await ensure_market_state_tables(
                pool,
                protocol=protocol,
                use_timescaledb=use_timescaledb,
            )
        finally:
            await pool.close()

    asyncio.run(_run())
