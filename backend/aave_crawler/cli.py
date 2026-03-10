"""Click CLI 入口"""

from __future__ import annotations

import asyncio
import logging

import click

from .config import load_config
from .crawler import run_crawler
from .db import create_pool, get_tables, sync_addresses_from_history
from .models import ReserveConfig, UserPosition
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
    """Aave V2/V3 仓位爬取工具"""


@cli.command("crawl")
@click.option("--config", "-c", default=None, help="config.yaml 路径（默认自动查找）")
@click.option(
    "--protocol",
    "-p",
    default="v3",
    type=click.Choice(["v2", "v3", "v2_borrow", "v3_borrow"]),
    show_default=True,
    help="目标协议版本（写入哪套表）",
)
@click.option(
    "--source",
    "-s",
    default=None,
    type=click.Choice(["v2", "v3"]),
    help="地址来源协议版本（从哪张 weth_collateral 表读取地址）；默认与 --protocol 相同",
)
@click.option(
    "--limit", "-n", default=None, type=int, help="仅处理前 N 个用户（调试用）"
)
@click.option("--dry-run", is_flag=True, default=False, help="只查询，不写入数据库")
@click.option(
    "--incremental",
    "-i",
    is_flag=True,
    default=False,
    help="增量模式：跳过目标仓位表中已存在的地址，仅处理新增地址",
)
@click.option("--verbose", "-v", is_flag=True, default=False, help="输出 DEBUG 日志")
def cmd_crawl(
    config: str | None,
    protocol: str,
    source: str | None,
    limit: int | None,
    dry_run: bool,
    incremental: bool,
    verbose: bool,
) -> None:
    """批量查询所有用户的 Aave 仓位并写入数据库。

    \b
    示例：
      aave-crawler crawl                         # v3 全量覆写
      aave-crawler crawl -p v2                   # v2 全量覆写
      aave-crawler crawl -p v3 -s v2             # 从 v2 地址列表爬 v3 仓位
      aave-crawler crawl --incremental           # v3 增量（跳过已爬地址）
      aave-crawler crawl -p v2 --incremental     # v2 增量
      aave-crawler crawl -p v3_borrow            # v3 借入方分析
    """
    _setup_logging(verbose)
    cfg = load_config(config)
    cfg.protocol = protocol

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await run_crawler(
                cfg,
                pool,
                limit=limit,
                dry_run=dry_run,
                source_protocol=source,
                incremental=incremental,
            )
        finally:
            await pool.close()

    asyncio.run(_run())


@cli.command("watch")
@click.option("--config", "-c", default=None, help="config.yaml 路径")
@click.option(
    "--protocol",
    "-p",
    default="v3",
    type=click.Choice(["v2", "v3", "v2_borrow", "v3_borrow"]),
    show_default=True,
    help="Aave 协议版本",
)
@click.option(
    "--interval",
    "-i",
    default=None,
    type=int,
    help="轮询间隔（秒），默认读取 config.yaml 中 watcher.interval",
)
@click.option(
    "--lookback",
    "-l",
    default=None,
    type=int,
    help="首次启动时回看多少分钟内的历史事件（默认 10）",
)
@click.option("--verbose", "-v", is_flag=True, default=False, help="输出 DEBUG 日志")
def cmd_watch(
    config: str | None,
    protocol: str,
    interval: int | None,
    lookback: int | None,
    verbose: bool,
) -> None:
    """增量监听模式：轮询 aave.aave_history，只重爬有操作的用户（持续运行）"""
    _setup_logging(verbose)
    cfg = load_config(config)
    cfg.protocol = protocol

    _interval = interval if interval is not None else cfg.watcher.interval
    _lookback = lookback if lookback is not None else cfg.watcher.lookback_minutes

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            await run_watcher(cfg, pool, interval=_interval, lookback_minutes=_lookback)
        finally:
            await pool.close()

    asyncio.run(_run())


@cli.command("sync-addresses")
@click.option("--config", "-c", default=None, help="config.yaml 路径")
@click.option(
    "--protocol",
    "-p",
    default=None,
    type=click.Choice(["v2", "v3", "v2_borrow", "v3_borrow"]),
    help="同步哪套来源表；省略时同步全部 4 张表",
)
@click.option(
    "--dry-run", is_flag=True, default=False, help="只查询并预览，不写入数据库"
)
@click.option("--verbose", "-v", is_flag=True, default=False, help="输出 DEBUG 日志")
def cmd_sync_addresses(
    config: str | None,
    protocol: str | None,
    dry_run: bool,
    verbose: bool,
) -> None:
    """从 aave.aave_history 派生用户地址并写入各来源表。

    \b
    来源表（loan schema）：
      aave_v2_eth_weth_collateral   aave_v3_eth_weth_collateral
      aave_v2_eth_weth_borrow       aave_v3_eth_weth_borrow

    \b
    示例：
      aave-crawler sync-addresses               # 同步全部 4 张表
      aave-crawler sync-addresses -p v3_borrow  # 仅同步 v3 借款地址
      aave-crawler sync-addresses --dry-run     # 预览，不写入
    """
    _setup_logging(verbose)
    cfg = load_config(config)

    # 确定要同步哪些协议
    protocols = [protocol] if protocol else ["v2", "v3", "v2_borrow", "v3_borrow"]

    async def _run() -> None:
        pool = await create_pool(cfg.postgres)
        try:
            total_written = 0
            for prot in protocols:
                tables = get_tables(prot)
                count = await sync_addresses_from_history(pool, tables, dry_run=dry_run)
                total_written += count
            verb = "预览" if dry_run else "写入"
            click.echo(
                f"sync-addresses 完成：{verb} {total_written} 条（共 {len(protocols)} 张表）"
            )
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
        EMPTY_POSITION,
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
        configs_list = await asyncio.gather(
            *[get_reserve_config(w3, a) for a in token_addresses],
            return_exceptions=True,
        )
        reserve_configs: dict[str, ReserveConfig] = {  # type: ignore[assignment]
            a: c
            for a, c in zip(token_addresses, configs_list)
            if not isinstance(c, Exception)
        }
        prices = await get_assets_prices(w3, token_addresses)
        asset_prices = dict(zip(token_addresses, prices))

        sem = asyncio.Semaphore(1)
        pos = await fetch_user_position(
            w3, address, reserve_tokens, reserve_configs, asset_prices, sem
        )
        if pos is None:
            click.echo(f"RPC 调用失败，无法查询仓位: {address}")
        elif pos is EMPTY_POSITION:
            click.echo(f"该地址在 Aave 无任何抵押/借贷仓位: {address}")
        else:
            from typing import cast

            click.echo(
                json.dumps(asdict(cast(UserPosition, pos)), indent=2, default=str)
            )

    asyncio.run(_run())
