"""Click CLI entrypoint for Compound crawler."""

from __future__ import annotations

import asyncio
import logging

import click

from .config import load_config
from .crawler import run_crawler
from .db import create_pool
from .watcher import run_watcher


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@click.group()
def cli() -> None:
    """Compound crawler tools"""


@cli.command("crawl")
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
    "--limit", "-n", default=None, type=int, help="Only process first N users"
)
@click.option("--dry-run", is_flag=True, default=False, help="Do not write to database")
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable DEBUG logging"
)
def cmd_crawl(
    config: str | None,
    protocol: str,
    limit: int | None,
    dry_run: bool,
    verbose: bool,
) -> None:
    _setup_logging(verbose)
    cfg = load_config(config)
    cfg.protocol = protocol

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await run_crawler(cfg, pool, limit=limit, dry_run=dry_run)
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
