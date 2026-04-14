"""Shared unified backend server entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aave_crawler.api.routes import router as aave_router
from aave_crawler.api.service import _cache
from aave_crawler.config import load_config
from aave_crawler.db import (
    TABLES_V2,
    TABLES_V2_BORROW,
    TABLES_V3,
    TABLES_V3_BORROW,
    create_pool,
    ensure_eth_price_timestamp_table,
    ensure_snapshot_cache_table,
    ensure_tables,
)
from aave_crawler.rpc import build_web3
from compound_crawler.api.routes import router as compound_router
from compound_crawler.db import ensure_compound_event_snapshot_table
from crawler_shared.api.routes import router as common_router
from crawler_shared.database import close_engine, init_engine
from justlend_crawler.api.routes import router as justlend_router
from justlend_crawler.config import load_config as load_justlend_config
from justlend_crawler.db import ensure_justlend_tables
from morpho_crawler.api.routes import router as morpho_router
from morpho_crawler.db import ensure_morpho_tables

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    cfg = load_config()
    logger.info("正在连接 RPC 节点...")
    w3 = await build_web3(cfg)
    application.state.w3 = w3
    application.state.cfg = cfg
    application.state.justlend_cfg = load_justlend_config()
    logger.info("正在连接数据库...")
    pool = await create_pool(cfg.postgres)
    application.state.pool = pool
    init_engine(cfg.postgres)
    logger.info("RPC 节点与数据库就绪，API 服务启动")
    yield
    await pool.close()
    try:
        if w3 is not None:
            await w3.provider.disconnect()
    except Exception:
        logger.debug("关闭 RPC provider 连接失败", exc_info=True)
    await close_engine()
    _cache.clear()
    logger.info("API 服务关闭")


def create_app() -> FastAPI:
    application = FastAPI(
        title="Aave + Compound + JustLend + Morpho API",
        description="统一提供 Aave、Compound、JustLend 与 Morpho 的查询接口",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    application.include_router(aave_router)
    application.include_router(common_router)
    application.include_router(compound_router)
    application.include_router(justlend_router)
    application.include_router(morpho_router)

    @application.get("/aave/health", tags=["系统"])
    async def _aave_health() -> dict:
        return {"status": "ok"}

    @application.get("/compound/health", tags=["系统"])
    async def _compound_health() -> dict:
        return {"status": "ok"}

    @application.get("/justlend/health", tags=["系统"])
    async def _justlend_health() -> dict:
        return {"status": "ok"}

    return application


app = create_app()


def main() -> None:
    import click

    @click.command("api")
    @click.option("--host", default="0.0.0.0", show_default=True, help="监听地址")
    @click.option("--port", default=8000, show_default=True, type=int, help="端口")
    @click.option("--reload", is_flag=True, default=False, help="开发模式热重载")
    @click.option(
        "--workers", default=1, show_default=True, type=int, help="工作进程数"
    )
    @click.option("--log-level", default="info", help="日志级别")
    @click.option(
        "--reload-dir",
        "reload_dirs",
        multiple=True,
        default=None,
        help="热重载监听目录",
    )
    @click.option(
        "--reload-include",
        "reload_includes",
        multiple=True,
        default=None,
        help="额外监听 glob",
    )
    @click.option(
        "--reload-exclude",
        "reload_excludes",
        multiple=True,
        default=None,
        help="排除 glob",
    )
    def _cmd(
        host: str,
        port: int,
        reload: bool,
        workers: int,
        log_level: str,
        reload_dirs: tuple[str, ...],
        reload_includes: tuple[str, ...],
        reload_excludes: tuple[str, ...],
    ) -> None:
        logging.basicConfig(
            level=log_level.upper(),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        uvicorn.run(
            "crawler_shared.server:app",
            host=host,
            port=port,
            reload=reload,
            workers=1 if reload else workers,
            log_level=log_level,
            reload_dirs=list(reload_dirs) or None,
            reload_includes=list(reload_includes) or None,
            reload_excludes=list(reload_excludes) or None,
        )

    _cmd()
