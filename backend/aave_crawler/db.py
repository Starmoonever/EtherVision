"""
数据库层。
- 建立 asyncpg 连接池
- 读取待处理用户列表
- 写入查询结果（待商议表结构后完善）
"""

from __future__ import annotations

import logging

import asyncpg

from .config import PostgresConfig

logger = logging.getLogger(__name__)


async def create_pool(pg: PostgresConfig) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn=pg.dsn, min_size=2, max_size=10)
    logger.info("PostgreSQL 连接池已创建：%s:%d/%s", pg.host, pg.port, pg.database)
    return pool  # type: ignore[return-value]


async def fetch_user_addresses(
    pool: asyncpg.Pool,
    schema: str = "loan",
    table: str = "all_aave_eth_users",
    address_column: str = "user_address",
    limit: int | None = None,
) -> list[str]:
    """从源表读取所有待查询的用户地址"""
    q = f'SELECT {address_column} FROM {schema}."{table}"'
    if limit:
        q += f" LIMIT {limit}"
    rows = await pool.fetch(q)
    addresses = [row[address_column] for row in rows]
    logger.info("读取到 %d 个用户地址", len(addresses))
    return addresses


# ── 占位：写入函数待表结构确定后实现 ─────────────────────────────────────────

async def upsert_positions(pool: asyncpg.Pool, positions: list) -> None:  # type: ignore[type-arg]
    """
    TODO: 待新表结构确定后实现。
    目前仅做日志输出。
    """
    logger.info("upsert_positions: 待写入 %d 条记录（表结构待商议）", len(positions))
