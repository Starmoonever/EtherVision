"""
SQLAlchemy 异步引擎 & 会话工厂，FastAPI 依赖注入。

用法示例（路由层）：
    from .database import DbSession

    @router.get("/positions")
    async def positions(session: DbSession, ...):
        return await get_sorted_positions(session, ...)
"""

from __future__ import annotations

import logging
from typing import Annotated, AsyncGenerator

import asyncpg
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)

from .config import PostgresConfig

logger = logging.getLogger(__name__)

_engine = None
_AsyncSessionLocal: async_sessionmaker | None = None


def init_engine(pg: PostgresConfig) -> None:
    """初始化 SQLAlchemy 异步引擎（程序启动时调用一次）。"""
    global _engine, _AsyncSessionLocal
    # asyncpg driver URL 格式
    url = (
        f"postgresql+asyncpg://{pg.user}:{pg.password}"
        f"@{pg.host}:{pg.port}/{pg.database}"
    )
    _engine = create_async_engine(url, pool_size=5, max_overflow=10, echo=False)
    _AsyncSessionLocal = async_sessionmaker(_engine, expire_on_commit=False)
    logger.info(
        "SQLAlchemy 异步引擎已初始化：%s:%d/%s", pg.host, pg.port, pg.database
    )


async def close_engine() -> None:
    """关闭 SQLAlchemy 异步引擎（程序关闭时调用）。"""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("SQLAlchemy 引擎已关闭")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每次请求创建 AsyncSession，请求结束后自动关闭。"""
    if _AsyncSessionLocal is None:
        raise RuntimeError("数据库引擎尚未初始化，请先调用 init_engine()")
    async with _AsyncSessionLocal() as session:
        yield session


async def get_pool(request: Request) -> asyncpg.Pool:
    """FastAPI 依赖：从 app.state 获取 asyncpg 连接池。

    保留供写密集型基础设施操作使用（bulk COPY、tx_parser、market_collector）。
    """
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="数据库连接尚未就绪，请稍后重试")
    return pool


# ── 带类型标注的快捷 Annotated 别名（供路由签名使用）──────────────────────────
DbSession = Annotated[AsyncSession, Depends(get_db)]
AsyncpgPool = Annotated[asyncpg.Pool, Depends(get_pool)]
