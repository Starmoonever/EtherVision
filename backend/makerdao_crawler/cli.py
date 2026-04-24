"""Click entrypoint for the MakerDAO scaffold."""

from __future__ import annotations

import asyncio

import click

from crawler_shared.logging import setup_cli_logging

from .config import load_config
from .crawler import run_crawler
from .db import create_pool, ensure_makerdao_tables


def _setup_logging(verbose: bool) -> None:
    setup_cli_logging(verbose)


@click.group()
def cli() -> None:
    """MakerDAO crawler tools"""


@cli.command("init-db")
@click.option("--config", "-c", default=None, help="config.yaml path")
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable DEBUG logging"
)
def cmd_init_db(config: str | None, verbose: bool) -> None:
    """Create scaffold tables for MakerDAO."""
    _setup_logging(verbose)
    cfg = load_config(config)

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await ensure_makerdao_tables(pool)
        finally:
            await pool.close()

    asyncio.run(_run())


@cli.command("crawl")
@click.option("--config", "-c", default=None, help="config.yaml path")
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable DEBUG logging"
)
def cmd_crawl(config: str | None, verbose: bool) -> None:
    """Reserved command for future MakerDAO crawling."""
    _setup_logging(verbose)
    cfg = load_config(config)

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await run_crawler(cfg, pool)
        finally:
            await pool.close()

    asyncio.run(_run())
