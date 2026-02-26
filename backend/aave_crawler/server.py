"""
FastAPI 应用工厂 & 启动入口。

启动方式：
  uv run aave-api                          # 使用 config.yaml，默认 0.0.0.0:8000
  uv run aave-api --host 127.0.0.1 --port 8080
  uv run uvicorn aave_crawler.server:app   # 直接使用 uvicorn（不支持 CLI 参数）
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .api.service import _cache
from .config import load_config
from .db import create_pool
from .rpc import build_web3

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
    pool = await create_pool(cfg.postgres)
    application.state.pool = pool
    logger.info("RPC 节点与数据库就绪，API 服务启动")
    yield
    await pool.close()
    _cache.clear()
    logger.info("API 服务关闭")


def create_app() -> FastAPI:
    application = FastAPI(
        title="Aave V3 ETH 仓位查询 API",
        description="实时查询以太主网 Aave V3 用户仓位及 ETH liq_price",
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

    application.include_router(router)

    @application.get("/health", tags=["系统"])
    async def health() -> dict:
        return {"status": "ok"}

    return application


# 供 uvicorn 直接引用
app = create_app()


def main() -> None:
    """CLI 入口（aave-api 命令）"""
    import click

    @click.command("aave-api")
    @click.option("--host", default="0.0.0.0", show_default=True, help="监听地址")
    @click.option("--port", default=8000, show_default=True, type=int, help="端口")
    @click.option("--reload", is_flag=True, default=False, help="开发模式热重载")
    @click.option("--workers", default=1, show_default=True, type=int, help="工作进程数（reload 时固定为 1）")
    @click.option("--log-level", default="info", show_default=True, help="日志级别")
    def _cmd(host: str, port: int, reload: bool, workers: int, log_level: str) -> None:
        """启动 Aave 仓位查询 API 服务"""
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
        )

    _cmd()


if __name__ == "__main__":
    main()
