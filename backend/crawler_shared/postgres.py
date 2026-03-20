"""Shared asyncpg helpers."""

from __future__ import annotations

import asyncio
import logging

import asyncpg

from .config import PostgresConfig

logger = logging.getLogger(__name__)


def normalize_ssl_mode(ssl_mode: str) -> bool | str:
    return False if ssl_mode == "disable" else ssl_mode


async def create_pool(
    pg: PostgresConfig,
    *,
    timeout: float | None = None,
    min_size: int = 1,
    max_size: int = 10,
) -> asyncpg.Pool:
    kwargs = {
        "dsn": pg.dsn,
        "ssl": normalize_ssl_mode(pg.ssl),
        "min_size": min_size,
        "max_size": max_size,
    }
    try:
        pool_coro = asyncpg.create_pool(**kwargs)
        pool = (
            await asyncio.wait_for(pool_coro, timeout=timeout)
            if timeout is not None
            else await pool_coro
        )
    except asyncio.TimeoutError as exc:
        raise RuntimeError(
            f"PostgreSQL 连接超时（>{timeout}s）：{pg.host}:{pg.port}/{pg.database}"
        ) from exc
    logger.info("PostgreSQL 连接池已创建：%s:%d/%s", pg.host, pg.port, pg.database)
    return pool
