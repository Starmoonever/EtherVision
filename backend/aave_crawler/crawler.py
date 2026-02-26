"""
批量爬取主流程。

流程：
1. 从 DB 读取用户列表
2. 预取公共数据（资产列表、配置、价格）
3. 并发查询每个用户仓位（asyncio.Semaphore 控制并发数）
4. 按批次写入 DB
5. 断点续传（TODO：待表结构确定后记录已处理地址）
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg
from tqdm import tqdm
from web3 import AsyncWeb3

from .config import AppConfig
from .db import fetch_user_addresses, upsert_positions
from .models import UserPosition
from .rpc import (
    build_web3,
    fetch_user_position,
    get_all_reserve_tokens,
    get_assets_prices,
    get_reserve_config,
)

logger = logging.getLogger(__name__)


async def prefetch_common_data(w3: AsyncWeb3) -> tuple:
    """
    预获取不依赖用户地址的公共数据：
    - 所有储备资产列表
    - 每个资产的配置（decimals、LTV 等）
    - 每个资产的当前价格
    返回 (reserve_tokens, reserve_configs, asset_prices)
    """
    logger.info("预获取公共数据（资产列表 / 配置 / 价格）...")
    reserve_tokens = await get_all_reserve_tokens(w3)
    logger.info("储备资产数量: %d", len(reserve_tokens))

    addresses = [rt.token_address for rt in reserve_tokens]

    # 并发获取配置和价格
    config_tasks = [get_reserve_config(w3, addr) for addr in addresses]
    configs_list = await asyncio.gather(*config_tasks, return_exceptions=True)
    reserve_configs = {
        addr: cfg
        for addr, cfg in zip(addresses, configs_list)
        if not isinstance(cfg, Exception)
    }

    prices_list = await get_assets_prices(w3, addresses)
    asset_prices = dict(zip(addresses, prices_list))

    logger.info("公共数据预获取完毕")
    return reserve_tokens, reserve_configs, asset_prices


async def run_crawler(
    cfg: AppConfig,
    pool: asyncpg.Pool,
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> None:
    """
    主爬取入口。

    :param cfg:     应用配置
    :param pool:    asyncpg 连接池
    :param limit:   仅处理前 N 个用户（调试用）
    :param dry_run: 只查询不写入 DB
    """
    w3 = await build_web3(cfg)

    # 预取公共数据（所有用户共享）
    reserve_tokens, reserve_configs, asset_prices = await prefetch_common_data(w3)

    # 读取待处理用户
    users = await fetch_user_addresses(pool, limit=limit)
    if not users:
        logger.warning("用户列表为空，退出")
        return

    semaphore = asyncio.Semaphore(cfg.crawler.concurrency)
    batch_size = cfg.crawler.batch_size
    pending_batch: list[UserPosition] = []
    total_ok = 0
    total_fail = 0

    with tqdm(total=len(users), desc="查询仓位", unit="user") as pbar:
        # 分批提交任务
        for i in range(0, len(users), batch_size * 2):
            chunk = users[i : i + batch_size * 2]
            tasks = [
                fetch_user_position(
                    w3, addr, reserve_tokens, reserve_configs, asset_prices, semaphore
                )
                for addr in chunk
            ]
            results = await asyncio.gather(*tasks)

            for pos in results:
                pbar.update(1)
                if pos is None:
                    total_fail += 1
                    continue
                total_ok += 1
                pending_batch.append(pos)

                # 积攒到 batch_size 后写入
                if len(pending_batch) >= batch_size:
                    if not dry_run:
                        await upsert_positions(pool, pending_batch)
                    pending_batch.clear()

        # 写入剩余
        if pending_batch and not dry_run:
            await upsert_positions(pool, pending_batch)

    logger.info("爬取完成：成功 %d，失败 %d", total_ok, total_fail)
