"""Shared SQLAlchemy async engine and FastAPI DB dependencies."""

from __future__ import annotations

import logging
from typing import Annotated, AsyncGenerator

import asyncpg
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import PostgresConfig

logger = logging.getLogger(__name__)

_engine = None
_async_session_local: async_sessionmaker | None = None


def init_engine(pg: PostgresConfig) -> None:
    global _engine, _async_session_local
    url = (
        f"postgresql+asyncpg://{pg.user}:{pg.password}"
        f"@{pg.host}:{pg.port}/{pg.database}"
    )
    _engine = create_async_engine(url, pool_size=5, max_overflow=10, echo=False)
    _async_session_local = async_sessionmaker(_engine, expire_on_commit=False)
    logger.info("SQLAlchemy 异步引擎已初始化：%s:%d/%s", pg.host, pg.port, pg.database)


async def close_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("SQLAlchemy 引擎已关闭")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if _async_session_local is None:
        raise RuntimeError("数据库引擎尚未初始化，请先调用 init_engine()")
    async with _async_session_local() as session:
        yield session


async def get_pool(request: Request) -> asyncpg.Pool:
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="数据库连接尚未就绪，请稍后重试")
    return pool


DbSession = Annotated[AsyncSession, Depends(get_db)]
AsyncpgPool = Annotated[asyncpg.Pool, Depends(get_pool)]
