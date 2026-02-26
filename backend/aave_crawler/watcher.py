"""
增量 Watch 模式。

通过轮询 chain-data-collector 写入的 aave.aave_history 表，
获取自上次处理以来有过操作的用户地址，只对这些地址做链上重查 + DB UPSERT，
避免每次全量爬取。

水位线（watermark）存储在内存中：
  - 首次启动时设为 NOW() - lookback_minutes（秒级）
  - 每轮处理后更新为本轮最大 created_at
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import asyncpg
from tqdm import tqdm

from .config import AppConfig
from .db import ensure_tables, upsert_positions
from .models import UserPosition
from .rpc import (
    EMPTY_POSITION,
    build_web3,
    fetch_user_position,
    get_all_reserve_tokens,
    get_assets_prices,
    get_reserve_config,
)

logger = logging.getLogger(__name__)

# ── SQL ───────────────────────────────────────────────────────────────────────

# 查询自水位线以来有活动的地址（aave.aave_history 的地址列是 bytea）
# UNION 自动去重；target_user_address 为 NULL 的行（如 flashloan 无 borrower）自动过滤
_SQL_CHANGED_USERS = """
SELECT DISTINCT '0x' || encode(addr, 'hex') AS address
FROM (
    SELECT user_address AS addr, created_at
      FROM aave.aave_history
     WHERE created_at > $1
    UNION ALL
    SELECT target_user_address AS addr, created_at
      FROM aave.aave_history
     WHERE created_at > $1
       AND target_user_address IS NOT NULL
       AND target_user_address <> user_address
) sub
"""

_SQL_NEW_WATERMARK = """
SELECT MAX(created_at) FROM aave.aave_history WHERE created_at > $1
"""


# ── 公共数据缓存（在同一进程内复用，每次 refresh 价格） ────────────────────────

async def _load_common_data(w3, cache: dict) -> tuple:
    """token 列表和配置只在首次加载，价格每轮实时获取。"""
    if "reserve_tokens" not in cache:
        reserve_tokens = await get_all_reserve_tokens(w3)
        addresses = [rt.token_address for rt in reserve_tokens]
        configs = await asyncio.gather(
            *[get_reserve_config(w3, a) for a in addresses],
            return_exceptions=True,
        )
        cache["reserve_tokens"] = reserve_tokens
        cache["reserve_configs"] = {
            a: c for a, c in zip(addresses, configs) if not isinstance(c, Exception)
        }
        cache["token_addresses"] = addresses
        logger.info("公共数据已缓存，储备资产数量: %d", len(reserve_tokens))

    prices = await get_assets_prices(w3, cache["token_addresses"])
    asset_prices = dict(zip(cache["token_addresses"], prices))
    return cache["reserve_tokens"], cache["reserve_configs"], asset_prices


# ── 单轮处理 ──────────────────────────────────────────────────────────────────

async def _process_round(
    w3,
    pool: asyncpg.Pool,
    watermark: datetime,
    concurrency: int,
    batch_size: int,
    common_cache: dict,
) -> datetime:
    """
    处理一轮：查询新事件 → 重爬涉及地址 → UPSERT → 返回新水位线。
    若本轮无新事件，原样返回 watermark。
    """
    # 1. 找出有变化的地址
    rows = await pool.fetch(_SQL_CHANGED_USERS, watermark)
    if not rows:
        return watermark

    addresses = [row["address"] for row in rows]
    logger.info("本轮发现 %d 个有活动的地址，开始重查链上仓位...", len(addresses))

    # 2. 预取公共链上数据（token 列表/配置缓存，价格实时拉取）
    reserve_tokens, reserve_configs, asset_prices = await _load_common_data(w3, common_cache)

    # 3. 并发查询这批地址
    semaphore = asyncio.Semaphore(concurrency)
    all_tasks = [
        asyncio.ensure_future(
            fetch_user_position(w3, addr, reserve_tokens, reserve_configs, asset_prices, semaphore)
        )
        for addr in addresses
    ]

    pending: list[UserPosition] = []
    ok = skip = fail = 0
    with tqdm(total=len(addresses), desc="重查仓位", unit="user", leave=False) as pbar:
        db_task: asyncio.Task | None = None
        for coro in asyncio.as_completed(all_tasks):
            pos = await coro
            pbar.update(1)
            if pos is EMPTY_POSITION:
                skip += 1
                continue
            if pos is None:
                fail += 1
                continue
            ok += 1
            pending.append(pos)
            if len(pending) >= batch_size:
                if db_task is not None:
                    await db_task
                db_task = asyncio.ensure_future(upsert_positions(pool, list(pending)))
                pending.clear()
        if db_task is not None:
            await db_task
        if pending:
            await upsert_positions(pool, pending)

    logger.info("本轮完成：更新 %d 人，已平仓跳过 %d 人，RPC 报错 %d 人", ok, skip, fail)

    # 4. 推进水位线
    row = await pool.fetchrow(_SQL_NEW_WATERMARK, watermark)
    new_wm = row[0] if row and row[0] else watermark
    return new_wm


# ── 主循环 ────────────────────────────────────────────────────────────────────

async def run_watcher(
    cfg: AppConfig,
    pool: asyncpg.Pool,
    *,
    interval: int = 60,
    lookback_minutes: int = 10,
) -> None:
    """
    增量 Watch 主循环，持续运行直到进程被杀。

    :param cfg:              应用配置
    :param pool:             asyncpg 连接池
    :param interval:         每轮轮询间隔（秒）
    :param lookback_minutes: 首次启动时水位线回退多少分钟（覆盖近期历史）
    """
    await ensure_tables(pool)

    w3 = await build_web3(cfg)
    common_cache: dict = {}

    # 初始水位线：NOW() - lookback，确保启动时能刷新近期有活动的用户
    watermark = datetime.now(tz=timezone.utc) - timedelta(minutes=lookback_minutes)
    logger.info(
        "Watch 模式启动。初始水位线: %s，轮询间隔: %ds",
        watermark.strftime("%Y-%m-%dT%H:%M:%SZ"),
        interval,
    )

    while True:
        try:
            watermark = await _process_round(
                w3, pool, watermark,
                concurrency=cfg.crawler.concurrency,
                batch_size=cfg.crawler.batch_size,
                common_cache=common_cache,
            )
        except Exception as exc:
            logger.error("本轮处理异常，跳过本轮：%s", exc, exc_info=True)

        logger.debug("等待 %ds 后进行下一轮...", interval)
        await asyncio.sleep(interval)
