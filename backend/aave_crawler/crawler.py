"""
批量爬取主流程。

流程：
1. 自动建表（ensure_tables）
2. 从 DB 读取用户列表
3. 预取公共数据（资产列表、配置、价格）
4. 并发查询每个用户仓位（asyncio.Semaphore 控制并发数）
5. 按批次 UPSERT 写入 DB
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg
from tqdm import tqdm
from web3 import AsyncWeb3

from .config import AppConfig
from .db import (ensure_tables, fetch_user_addresses, get_tables,
                 upsert_positions)
from .models import UserPosition
from .rpc import (CONTRACTS_V3, EMPTY_POSITION, WETH_ADDRESS,
                  ProtocolContracts, build_web3, fetch_user_position,
                  get_all_reserve_tokens, get_assets_prices, get_contracts,
                  get_reserve_config)

logger = logging.getLogger(__name__)


async def prefetch_common_data(w3: AsyncWeb3, contracts: ProtocolContracts) -> tuple:
    """
    预获取不依赖用户地址的公共数据：
    - 所有储备资产列表
    - 每个资产的配置（decimals、LTV 等）
    - 每个资产的当前价格
    返回 (reserve_tokens, reserve_configs, asset_prices)
    """
    logger.info("预获取公共数据（资产列表 / 配置 / 价格）...")
    reserve_tokens = await get_all_reserve_tokens(w3, contracts)
    logger.info("储备资产数量: %d", len(reserve_tokens))

    addresses = [rt.token_address for rt in reserve_tokens]

    # 并发获取配置和价格
    config_tasks = [get_reserve_config(w3, addr, contracts) for addr in addresses]
    configs_list = await asyncio.gather(*config_tasks, return_exceptions=True)
    reserve_configs = {
        addr: cfg
        for addr, cfg in zip(addresses, configs_list)
        if not isinstance(cfg, Exception)
    }

    prices_list = await get_assets_prices(w3, addresses, contracts)
    asset_prices = dict(zip(addresses, prices_list))

    # V2 oracle 返回 ETH 计价（18 位精度），需转换为 USD（8 位精度）以兼容下游计算
    # 转换公式：price_usd_8dec = price_eth_18dec * eth_usd_8dec // 10^18
    if contracts.oracle_price_in_eth:
        eth_usd_prices = await get_assets_prices(w3, [WETH_ADDRESS], CONTRACTS_V3)
        eth_usd_raw = eth_usd_prices[0]  # V3 oracle 的 WETH 价格，8 位精度 USD
        if eth_usd_raw > 0:
            asset_prices = {
                addr: (price * eth_usd_raw) // (10 ** 18)
                for addr, price in asset_prices.items()
            }
            logger.info(
                "V2 oracle 价格已从 ETH（18位）转换为 USD（8位），ETH/USD=%.2f",
                eth_usd_raw / 10 ** 8,
            )
        else:
            logger.warning("无法从 V3 oracle 获取 ETH/USD 价格，V2 oracle 价格归一化跳过")

    logger.info("公共数据预获取完毕")
    return reserve_tokens, reserve_configs, asset_prices


async def run_crawler(
    cfg: AppConfig,
    pool: asyncpg.Pool,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    source_protocol: str | None = None,
    incremental: bool = False,
) -> None:
    """
    主爬取入口。

    :param cfg:             应用配置
    :param pool:            asyncpg 连接池
    :param limit:           仅处理前 N 个用户（调试用）
    :param dry_run:         只查询不写入 DB
    :param source_protocol: 地址来源表协议版本（v2/v3）；默认与 cfg.protocol 相同
    :param incremental:     True 时跳过目标表已存在的地址（增量模式）
    """
    w3 = await build_web3(cfg)

    # 将 protocol 字符串转换为合约地址和表名配置
    contracts = get_contracts(cfg.protocol)
    tables = get_tables(cfg.protocol)
    logger.info("协议版本: %s", cfg.protocol.upper())

    # 地址来源表（可与目标协议不同）
    src_proto = source_protocol if source_protocol is not None else cfg.protocol
    src_tables = get_tables(src_proto)
    if src_proto != cfg.protocol:
        logger.info("地址来源：%s（目标协议：%s）", src_proto.upper(), cfg.protocol.upper())

    # 确保目标表已存在
    await ensure_tables(pool, tables)

    # 预取公共数据（所有用户共享）
    reserve_tokens, reserve_configs, asset_prices = await prefetch_common_data(w3, contracts)

    # 读取待处理用户
    users = await fetch_user_addresses(
        pool, src_tables, limit=limit,
        incremental=incremental, target_tables=tables,
    )
    if not users:
        logger.warning("用户列表为空，退出")
        return

    semaphore = asyncio.Semaphore(cfg.crawler.concurrency)
    batch_size = cfg.crawler.batch_size
    pending_batch: list[UserPosition] = []
    total_ok = 0
    total_fail = 0
    total_skip = 0

    # 将所有用户任务一次性提交，由 semaphore 控制实际并发数。
    # 使用 asyncio.as_completed 流式收取结果，避免慢用户阻塞整批；
    # DB 写入与后续 RPC 查询并发执行，充分利用网络和数据库 I/O 窗口。
    all_tasks = [
        asyncio.ensure_future(
            fetch_user_position(
                w3, addr, reserve_tokens, reserve_configs, asset_prices, semaphore
            )
        )
        for addr in users
    ]

    db_write_task: asyncio.Task | None = None  # 当前正在后台写入的任务

    with tqdm(total=len(users), desc="查询仓位", unit="user") as pbar:
        for coro in asyncio.as_completed(all_tasks):
            pos = await coro
            pbar.update(1)
            if pos is EMPTY_POSITION:
                total_skip += 1
                continue
            if pos is None:
                total_fail += 1
                continue
            total_ok += 1
            pending_batch.append(pos)

            if len(pending_batch) >= batch_size:
                # 等待上一次 DB 写入完成，再发起新的写入
                if db_write_task is not None:
                    await db_write_task
                if not dry_run:
                    db_write_task = asyncio.ensure_future(
                        upsert_positions(pool, list(pending_batch), tables)
                    )
                pending_batch.clear()

    # 等待最后一次后台写入完成
    if db_write_task is not None:
        await db_write_task
    if pending_batch and not dry_run:
        await upsert_positions(pool, pending_batch, tables)

    logger.info("爬取完成：有仓位 %d，无仓位跳过 %d，RPC 报错 %d", total_ok, total_skip, total_fail)
