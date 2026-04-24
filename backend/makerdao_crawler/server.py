"""Compatibility wrapper: MakerDAO API shares the unified app entrypoint."""

from __future__ import annotations

from sqlalchemy import create_engine

from crawler_shared.server import app, create_app, main

from .config import load_config
from .db import ensure_makerdao_tables

__all__ = ["app", "create_app", "main"]


def _get_pg_dsn(config):
    pg = config.postgres
    if hasattr(pg, "dsn") and callable(getattr(pg, "dsn")):
        return pg.dsn()
    if hasattr(pg, "dsn"):
        return pg.dsn
    return f"postgresql://{pg.user}:{pg.password}@{pg.host}:{pg.port}/{pg.database}"


def check_and_create_tables():
    import asyncio

    config = load_config()
    dsn = _get_pg_dsn(config)
    engine = create_engine(dsn)
    engine.dispose()

    async def _run() -> None:
        from .db import create_pool

        pool = await create_pool(config.postgres)
        try:
            await ensure_makerdao_tables(pool)
        finally:
            await pool.close()

    asyncio.run(_run())
