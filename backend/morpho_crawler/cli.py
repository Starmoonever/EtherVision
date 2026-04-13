"""Click entrypoint for the Morpho scaffold."""

from __future__ import annotations

import asyncio

import click
from crawler_shared.logging import setup_cli_logging

from .config import load_config
from .crawler import run_crawler
from .db import create_pool, ensure_morpho_tables
from .watcher import run_watcher


def _setup_logging(verbose: bool) -> None:
    setup_cli_logging(verbose)


@click.group()
def cli() -> None:
    """Morpho crawler tools"""


@cli.command("init-db")
@click.option("--config", "-c", default=None, help="config.yaml path")
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable DEBUG logging"
)
def cmd_init_db(config: str | None, verbose: bool) -> None:
    """Create the scaffold tables for Morpho."""
    _setup_logging(verbose)
    cfg = load_config(config)

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await ensure_morpho_tables(pool)
        finally:
            await pool.close()

    asyncio.run(_run())


@cli.command("crawl")
@click.option("--config", "-c", default=None, help="config.yaml path")
@click.option(
    "--protocol",
    "-p",
    default="blue",
    type=click.Choice(["blue"]),
    show_default=True,
    help="Morpho protocol selector",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable DEBUG logging"
)
def cmd_crawl(config: str | None, protocol: str, verbose: bool) -> None:
    """Reserved command for future Morpho crawling."""
    _setup_logging(verbose)
    cfg = load_config(config)
    cfg.protocol = protocol

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await run_crawler(cfg, pool)
        finally:
            await pool.close()

    asyncio.run(_run())


@cli.command("watch")
@click.option("--config", "-c", default=None, help="config.yaml path")
@click.option(
    "--protocol",
    "-p",
    default="blue",
    type=click.Choice(["blue"]),
    show_default=True,
    help="Morpho protocol selector",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable DEBUG logging"
)
def cmd_watch(config: str | None, protocol: str, verbose: bool) -> None:
    """Reserved command for future Morpho watcher."""
    _setup_logging(verbose)
    cfg = load_config(config)
    cfg.protocol = protocol

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await run_watcher(cfg, pool)
        finally:
            await pool.close()

    asyncio.run(_run())
