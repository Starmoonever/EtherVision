"""Database helpers for Compound crawler."""

from __future__ import annotations

import asyncpg

from .config import PostgresConfig


async def create_pool(pg: PostgresConfig) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        host=pg.host,
        port=pg.port,
        user=pg.user,
        password=pg.password,
        database=pg.database,
        ssl=pg.ssl,
        min_size=1,
        max_size=10,
    )
