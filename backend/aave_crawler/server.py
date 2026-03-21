"""
FastAPI 应用工厂 & 启动入口。

启动方式：
    uv run api                               # 使用 config.yaml，默认 0.0.0.0:8000
    uv run api --host 127.0.0.1 --port 8080
  uv run uvicorn aave_crawler.server:app   # 直接使用 uvicorn（不支持 CLI 参数）
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import common_router as aave_common_router
from .api.routes import router as aave_router
from .api.service import _cache
from .config import load_config
from .database import close_engine, init_engine
from .db import (
    TABLES_V2,
    TABLES_V2_BORROW,
    TABLES_V3,
    TABLES_V3_BORROW,
    create_pool,
    ensure_snapshot_cache_table,
    ensure_eth_price_timestamp_table,
    ensure_tables,
)
from .rpc import build_web3
from compound_crawler.api.routes import router as compound_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """启动时初始化 Web3 客户端和 DB 连接池，关闭时清理资源。"""
    cfg = load_config()
    logger.info("正在连接 RPC 节点...")
    w3 = await build_web3(cfg)
    application.state.w3 = w3
    application.state.cfg = cfg
    logger.info("正在连接数据库...")
    # asyncpg 连接池：供爬虫批量写入 / tx_parser / market_collector 使用
    pool = await create_pool(cfg.postgres)
    application.state.pool = pool
    # SQLAlchemy 异步引擎：供 API 查询层（service.py）使用
    init_engine(cfg.postgres)
    # 确保所有协议表存在并应用 migration（幂等，开销极小）
    for _tables in (TABLES_V3, TABLES_V2, TABLES_V3_BORROW, TABLES_V2_BORROW):
        await ensure_tables(pool, _tables)
    await ensure_snapshot_cache_table(pool)
    await ensure_eth_price_timestamp_table(pool)
    logger.info("RPC 节点与数据库就绪，API 服务启动")
    yield
    await pool.close()
    await close_engine()
    _cache.clear()
    logger.info("API 服务关闭")


def create_app() -> FastAPI:
    application = FastAPI(
        title="Aave + Compound API",
        description="统一提供 Aave 与 Compound 的查询接口",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS：允许前端（任意 origin）访问，生产环境可收窄
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    application.include_router(aave_router)
    application.include_router(aave_common_router)
    application.include_router(compound_router)

    @application.get("/aave/health", tags=["系统"])
    async def health() -> dict:
        return {"status": "ok"}

    @application.get("/compound/health", tags=["系统"])
    async def compound_health() -> dict:
        return {"status": "ok"}

    return application


# 供 uvicorn 直接引用
app = create_app()


def main() -> None:
    """CLI 入口（统一 API：Aave + Compound）"""
    import click

    @click.command("api")
    @click.option("--host", default="0.0.0.0", show_default=True, help="监听地址")
    @click.option("--port", default=8000, show_default=True, type=int, help="端口")
    @click.option("--reload", is_flag=True, default=False, help="开发模式热重载")
    @click.option(
        "--workers",
        default=1,
        show_default=True,
        type=int,
        help="工作进程数（reload 时固定为 1）",
    )
    @click.option(
        "--log-level",
        default=None,
        help="日志级别（默认读取 config.yaml log_level，缺省 info）",
    )
    @click.option(
        "--reload-dir",
        "reload_dirs",
        multiple=True,
        default=None,
        help="热重载监听目录（可多次指定）；默认监听所有 Python 路径",
    )
    @click.option(
        "--reload-include",
        "reload_includes",
        multiple=True,
        default=None,
        help="额外监听的 glob 模式，如 '*.yaml'（可多次指定）",
    )
    @click.option(
        "--reload-exclude",
        "reload_excludes",
        multiple=True,
        default=None,
        help="排除的 glob 模式，如 '__pycache__'（可多次指定）",
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
        """启动统一 API 服务（Aave + Compound）"""
        # --log-level 未显式传入时，读 config.yaml log_level，最终默认 info
        if log_level is None:
            try:
                from .config import load_config as _load_cfg

                log_level = _load_cfg().log_level
            except Exception:
                log_level = "info"
        logging.basicConfig(
            level=log_level.upper(),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        uvicorn.run(
            "aave_crawler.server:app",
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


if __name__ == "__main__":
    main()
