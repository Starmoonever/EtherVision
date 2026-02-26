"""Click CLI 入口"""

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
    # 压制 web3 / httpx 的 DEBUG 噪音
    logging.getLogger("web3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


@click.group()
def cli() -> None:
    """Aave V3 Base 仓位爬取工具"""


@cli.command("crawl")
@click.option("--config", "-c", default=None, help="config.yaml 路径（默认自动查找）")
@click.option("--limit", "-n", default=None, type=int, help="仅处理前 N 个用户（调试用）")
@click.option("--dry-run", is_flag=True, default=False, help="只查询，不写入数据库")
@click.option("--verbose", "-v", is_flag=True, default=False, help="输出 DEBUG 日志")
def cmd_crawl(config: str | None, limit: int | None, dry_run: bool, verbose: bool) -> None:
    """批量查询所有用户的 Aave 仓位并写入数据库"""
    _setup_logging(verbose)
    cfg = load_config(config)

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await run_crawler(cfg, pool, limit=limit, dry_run=dry_run)
        finally:
            await pool.close()

    asyncio.run(_run())


@cli.command("watch")
@click.option("--config", "-c", default=None, help="config.yaml 路径")
@click.option(
    "--interval", "-i", default=None, type=int,
    help="轮询间隔（秒），默认读取 config.yaml 中 watcher.interval",
)
@click.option(
    "--lookback", "-l", default=None, type=int,
    help="首次启动时回看多岑分钟内的历史事件（默认 10）",
)
@click.option("--verbose", "-v", is_flag=True, default=False, help="输出 DEBUG 日志")
def cmd_watch(
    config: str | None, interval: int | None, lookback: int | None, verbose: bool
) -> None:
    """增量监听模式：轮询 aave.aave_history，只重爬有操作的用户（持续运行）"""
    _setup_logging(verbose)
    cfg = load_config(config)

    _interval = interval if interval is not None else cfg.watcher.interval
    _lookback = lookback if lookback is not None else cfg.watcher.lookback_minutes

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await run_watcher(cfg, pool, interval=_interval, lookback_minutes=_lookback)
        finally:
            await pool.close()

    asyncio.run(_run())


@cli.command("check")
@click.argument("address")
@click.option("--config", "-c", default=None, help="config.yaml 路径")
@click.option("--verbose", "-v", is_flag=True, default=False)
def cmd_check(address: str, config: str | None, verbose: bool) -> None:
    """查询单个地址的仓位（调试用，结果输出到终端）"""
    import json
    from dataclasses import asdict

    from .rpc import (
        build_web3,
        fetch_user_position,
        get_all_reserve_tokens,
        get_assets_prices,
        get_reserve_config,
    )

    _setup_logging(verbose)
    cfg = load_config(config)

    async def _run() -> None:
        import asyncio

        w3 = await build_web3(cfg)
        reserve_tokens = await get_all_reserve_tokens(w3)
        token_addresses = [rt.token_address for rt in reserve_tokens]
        configs_list = await asyncio.gather(*[get_reserve_config(w3, a) for a in token_addresses], return_exceptions=True)
        reserve_configs = {a: c for a, c in zip(token_addresses, configs_list) if not isinstance(c, Exception)}
        prices = await get_assets_prices(w3, token_addresses)
        asset_prices = dict(zip(token_addresses, prices))

        sem = asyncio.Semaphore(1)
        pos = await fetch_user_position(w3, address, reserve_tokens, reserve_configs, asset_prices, sem)
        if pos:
            click.echo(json.dumps(asdict(pos), indent=2, default=str))
        else:
            click.echo(f"查询失败或该地址无 Aave 仓位: {address}")

    asyncio.run(_run())
