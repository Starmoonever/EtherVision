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
from decimal import Decimal

import asyncpg
from tqdm import tqdm

from .config import AppConfig
from .db import (
    ensure_snapshot_cache_table,
    ensure_tables,
    get_tables,
    upsert_positions,
    upsert_snapshot_cache,
)
from .models import UserPosition
from .rpc import (
    CONTRACTS_V3,
    EMPTY_POSITION,
    WETH_ADDRESS,
    ProtocolContracts,
    build_web3,
    fetch_user_position,
    fetch_user_position_at_block,
    get_all_reserve_tokens,
    get_assets_prices,
    get_contracts,
    get_reserve_config,
)
from .tx_parser import parse_briefs_from_metas

logger = logging.getLogger(__name__)

# ── SQL ───────────────────────────────────────────────────────────────────────

# 查询自水位线以来有活动的地址（aave.aave_history 的地址列是 bytea）
# $1 = watermark datetime，$2 = protocol_version 字符串（'2' 或 '3'）
# UNION 自动去重；target_user_address 为 NULL 的行（如 flashloan 无 borrower）自动过滤
_SQL_CHANGED_USERS = """
SELECT DISTINCT convert_from(addr, 'UTF8') AS address
FROM (
    SELECT user_address AS addr, created_at
      FROM aave.aave_history
     WHERE created_at > $1
       AND protocol_version = $2
    UNION ALL
    SELECT target_user_address AS addr, created_at
      FROM aave.aave_history
     WHERE created_at > $1
       AND protocol_version = $2
       AND target_user_address IS NOT NULL
       AND target_user_address <> user_address
) sub
"""

_SQL_NEW_WATERMARK = """
SELECT MAX(created_at) AT TIME ZONE 'UTC' FROM aave.aave_history
 WHERE created_at > $1
   AND protocol_version = $2
"""

# 查询水位线以来的新 tx 记录（user_address + target_user_address 均纳入）
# 用于 snapshot cache 同步；按 block_number 升序
_SQL_NEW_TX_RECORDS = """
SELECT
    block_number,
    created_at                              AS block_timestamp,
    lower(encode(tx_hash, 'escape'))        AS tx_hash,
    lower(encode(user_address, 'escape'))   AS user_address
FROM aave.aave_history
WHERE created_at > $1
  AND protocol_version = $2
UNION
SELECT
    block_number,
    created_at,
    lower(encode(tx_hash, 'escape')),
    lower(encode(target_user_address, 'escape'))
FROM aave.aave_history
WHERE created_at > $1
  AND protocol_version = $2
  AND target_user_address IS NOT NULL
  AND target_user_address <> user_address
ORDER BY block_number ASC
"""

# snapshot 同步最大并发（archive 节点保护）
_MAX_SNAPSHOT_CONCURRENCY = 3


# ── 公共数据缓存（在同一进程内复用，每次 refresh 价格） ────────────────────────


async def _load_common_data(w3, contracts: ProtocolContracts, cache: dict) -> tuple:
    """倒版 列表和配置只在首次加载，价格每轮实时获取。"""
    if "reserve_tokens" not in cache:
        reserve_tokens = await get_all_reserve_tokens(w3, contracts)
        addresses = [rt.token_address for rt in reserve_tokens]
        configs = await asyncio.gather(
            *[get_reserve_config(w3, a, contracts) for a in addresses],
            return_exceptions=True,
        )
        cache["reserve_tokens"] = reserve_tokens
        cache["reserve_configs"] = {
            a: c for a, c in zip(addresses, configs) if not isinstance(c, Exception)
        }
        cache["token_addresses"] = addresses
        logger.info("公共数据已缓存，储备资产数量: %d", len(reserve_tokens))

    prices = await get_assets_prices(w3, cache["token_addresses"], contracts)
    asset_prices = dict(zip(cache["token_addresses"], prices))

    # V2 oracle 返回 ETH 计价（18 位 精度），需要乘以 ETH/USD 并除以 10^18 转换为 USD（8 位）
    if contracts.oracle_price_in_eth:
        eth_usd_prices = await get_assets_prices(w3, [WETH_ADDRESS], CONTRACTS_V3)
        eth_usd_raw = eth_usd_prices[0]
        if eth_usd_raw > 0:
            asset_prices = {
                addr: (price * eth_usd_raw) // (10**18)
                for addr, price in asset_prices.items()
            }
            logger.debug("V2 oracle 价格已归一化，ETH/USD=%.2f", eth_usd_raw / 10**8)
        else:
            logger.warning("无法获取 ETH/USD 价格，V2 oracle 价格归一化跳过")

    return cache["reserve_tokens"], cache["reserve_configs"], asset_prices


# ── snapshot cache 同步 ──────────────────────────────────────────────────────


async def _sync_snapshot_cache(
    w3,
    pool: asyncpg.Pool,
    watermark: datetime,
    protocol_version: str,  # '2' 或 '3'
    common_cache: dict,
    contracts: ProtocolContracts,
) -> None:
    """将水位线以来的新 tx 写入 aave_position_snapshots（幂等 UPSERT）。

    每个 (user_address, block_number) 对只查一次 RPC；同一区块多条 tx 取首条 tx_hash。
    """
    tx_rows = await pool.fetch(_SQL_NEW_TX_RECORDS, watermark, protocol_version)
    if not tx_rows:
        return

    # 按 (user_address, block_number) 去重，同一区块同一用户只需查一次链上状态
    seen: dict[tuple[str, int], dict] = {}
    for r in tx_rows:
        key = (r["user_address"], r["block_number"])
        if key not in seen:
            seen[key] = dict(r)
    deduped = list(seen.values())
    logger.info(
        "快照同步：本轮 %d 条新 tx → 去重后 %d 个 (user, block) 对",
        len(tx_rows),
        len(deduped),
    )

    reserve_tokens = common_cache.get("reserve_tokens", [])
    reserve_configs = common_cache.get("reserve_configs", {})
    semaphore = asyncio.Semaphore(_MAX_SNAPSHOT_CONCURRENCY)
    proto = f"v{protocol_version}"  # '2' → 'v2', '3' → 'v3'

    tasks = [
        fetch_user_position_at_block(
            w3,
            t["user_address"],
            reserve_tokens,
            reserve_configs,
            t["block_number"],
            semaphore,
            contracts,
        )
        for t in deduped
    ]
    results = await asyncio.gather(*tasks)

    positions = []
    metas = []
    for t, res in zip(deduped, results):
        if res is None or res is EMPTY_POSITION:
            continue
        pos, eth_price_raw = res  # type: ignore[misc]
        eth_price_dec = Decimal(eth_price_raw) / Decimal(10**8)
        positions.append(pos)
        metas.append(
            {
                "tx_hash": t["tx_hash"],
                "block_timestamp": t["block_timestamp"],
                "eth_price_usd": eth_price_dec,
                "protocol": proto,
                "prices": {
                    r.token_address.lower(): Decimal(r.price_raw) / Decimal(10**8)
                    for r in pos.reserves
                },
            }
        )

    if positions:
        briefs = await parse_briefs_from_metas(pool, metas)
        written = await upsert_snapshot_cache(pool, positions, metas, briefs=briefs)
        logger.info("快照同步完成：写入 %d 条", written)
    else:
        logger.debug("快照同步：本轮无可写入的仓位数据")


# ── 单轮处理 ──────────────────────────────────────────────────────────────────


async def _process_round(
    w3,
    pool: asyncpg.Pool,
    watermark: datetime,
    concurrency: int,
    batch_size: int,
    common_cache: dict,
    contracts: ProtocolContracts,
    tables,
    protocol_version: str = "3",
) -> datetime:
    """
    处理一轮：查询新事件 → 重爬涉及地址 → UPSERT → 返回新水位线。
    若本轮无新事件，原样返回 watermark。

    :param protocol_version: aave_history.protocol_version 的过滤值，'2' 或 '3'
    """
    # 1. 找出有变化的地址
    rows = await pool.fetch(_SQL_CHANGED_USERS, watermark, protocol_version)
    if not rows:
        return watermark

    addresses = [row["address"] for row in rows]
    logger.info("本轮发现 %d 个有活动的地址，开始重查链上仓位...", len(addresses))

    # 2. 预取公共链上数据（token 列表/配置缓存，价格实时拉取）
    reserve_tokens, reserve_configs, asset_prices = await _load_common_data(
        w3, contracts, common_cache
    )

    # 3. 并发查询这批地址
    semaphore = asyncio.Semaphore(concurrency)
    all_tasks = [
        asyncio.ensure_future(
            fetch_user_position(
                w3,
                addr,
                reserve_tokens,
                reserve_configs,
                asset_prices,
                semaphore,
                contracts,
            )
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
            from typing import cast

            ok += 1
            pending.append(cast(UserPosition, pos))
            if len(pending) >= batch_size:
                if db_task is not None:
                    await db_task
                db_task = asyncio.ensure_future(
                    upsert_positions(pool, list(pending), tables)
                )
                pending.clear()
        if db_task is not None:
            await db_task
        if pending:
            await upsert_positions(pool, pending, tables)

    logger.info(
        "本轮完成：更新 %d 人，已平仓跳过 %d 人，RPC 报错 %d 人", ok, skip, fail
    )

    # 4. 推进水位线
    row = await pool.fetchrow(_SQL_NEW_WATERMARK, watermark, protocol_version)
    new_wm = row[0] if row and row[0] else watermark
    if isinstance(new_wm, datetime) and new_wm.tzinfo is None:
        new_wm = new_wm.replace(tzinfo=timezone.utc)

    # 5. 同步 snapshot cache（本轮新 tx 的链上仓位快照）
    try:
        await _sync_snapshot_cache(
            w3, pool, watermark, protocol_version, common_cache, contracts
        )
    except Exception as exc:
        logger.warning("快照同步失败（不影响主流程）：%s", exc, exc_info=True)

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
    w3 = await build_web3(cfg)
    contracts = get_contracts(cfg.protocol)
    tables = get_tables(cfg.protocol)
    await ensure_tables(pool, tables)
    await ensure_snapshot_cache_table(pool)
    # cfg.protocol 为 'v2'/'v3'/'v2_borrow'/'v3_borrow'
    # aave_history.protocol_version 字段值为 '2'或'3'，取主版本号
    _proto_base = cfg.protocol.lstrip("v").split("_")[0]
    protocol_version = _proto_base  # '2' 或 '3'
    logger.info("协议版本: %s", cfg.protocol.upper())
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
                w3,
                pool,
                watermark,
                concurrency=cfg.crawler.concurrency,
                batch_size=cfg.crawler.batch_size,
                common_cache=common_cache,
                contracts=contracts,
                tables=tables,
                protocol_version=protocol_version,
            )
        except Exception as exc:
            logger.error("本轮处理异常，跳过本轮：%s", exc, exc_info=True)

        logger.debug("等待 %ds 后进行下一轮...", interval)
        await asyncio.sleep(interval)
