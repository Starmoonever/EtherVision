"""SQLAlchemy async session setup for Compound API."""

from __future__ import annotations

from typing import Annotated, AsyncGenerator

import asyncpg
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import PostgresConfig

_engine = None
_AsyncSessionLocal: async_sessionmaker | None = None


def init_engine(pg: PostgresConfig) -> None:
    global _engine, _AsyncSessionLocal
    url = (
        f"postgresql+asyncpg://{pg.user}:{pg.password}"
        f"@{pg.host}:{pg.port}/{pg.database}"
    )
    _engine = create_async_engine(url, pool_size=5, max_overflow=10, echo=False)
    _AsyncSessionLocal = async_sessionmaker(_engine, expire_on_commit=False)


async def close_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if _AsyncSessionLocal is None:
        raise RuntimeError("Database engine is not initialized")
    async with _AsyncSessionLocal() as session:
        yield session


async def get_pool(request: Request) -> asyncpg.Pool:
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database pool is not ready")
    return pool


DbSession = Annotated[AsyncSession, Depends(get_db)]
AsyncpgPool = Annotated[asyncpg.Pool, Depends(get_pool)]
