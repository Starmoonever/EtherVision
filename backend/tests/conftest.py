"""pytest 公共 fixtures"""

from __future__ import annotations

from typing import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from aave_crawler.api.routes import common_router, router
from aave_crawler.database import get_db, get_pool
from fastapi import FastAPI
from starlette.testclient import TestClient

# ── fixtures ──────────────────────────────────────────────────────────────────


def _make_app(w3=..., pool=...) -> FastAPI:
    """创建含路由的测试 FastAPI 实例；使用 ... 表示使用默认 MagicMock。"""
    _app = FastAPI()
    _app.include_router(router)
    _app.include_router(common_router)
    _app.state.w3 = MagicMock() if w3 is ... else w3
    _app.state.pool = MagicMock() if pool is ... else pool

    # Override 依赖注入：提供 mock session 和 pool
    async def override_get_db():
        """Mock AsyncSession for dependency injection"""
        mock_session = AsyncMock()
        yield mock_session

    async def override_get_pool():
        """Mock asyncpg.Pool for dependency injection, with 503 check"""
        from fastapi import HTTPException

        pool = _app.state.pool
        if pool is None:
            raise HTTPException(
                status_code=503, detail="数据库连接尚未就绪，请稍后重试"
            )
        return pool

    _app.dependency_overrides[get_db] = override_get_db
    _app.dependency_overrides[get_pool] = override_get_pool

    return _app


@pytest.fixture
def app() -> FastAPI:
    """默认测试 app：w3 和 pool 均为 MagicMock（非 None，通过守卫检查）。"""
    return _make_app()


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def app_no_w3() -> FastAPI:
    """w3=None 的 app，用于测试 503 场景。"""
    return _make_app(w3=None)  # type: ignore[arg-type]


@pytest.fixture
def app_no_pool() -> FastAPI:
    """pool=None 的 app，用于测试 503 场景。"""
    return _make_app(pool=None)  # type: ignore[arg-type]
