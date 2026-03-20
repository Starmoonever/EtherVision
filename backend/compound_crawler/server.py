"""Compatibility wrapper: Compound API now shares the unified app entrypoint."""

from __future__ import annotations

from aave_crawler.server import app, create_app, main
from .db import ensure_compound_v3_user_positions_table
from sqlalchemy import create_engine
from .config import load_config

__all__ = ["app", "create_app", "main"]


def _get_pg_dsn(config):
    # 兼容 aave_crawler.config 和 compound_crawler.config
    pg = config.postgres
    if hasattr(pg, "dsn") and callable(getattr(pg, "dsn")):
        return pg.dsn()
    if hasattr(pg, "dsn"):
        return pg.dsn
    # fallback
    return f"postgresql://{pg.user}:{pg.password}@{pg.host}:{pg.port}/{pg.database}"


def check_and_create_tables():
    config = load_config()
    dsn = _get_pg_dsn(config)
    engine = create_engine(dsn)
    ensure_compound_v3_user_positions_table(engine)
