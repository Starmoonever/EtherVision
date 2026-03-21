"""
ClickHouse 连接与查询封装。

使用 clickhouse-connect（HTTP 协议），支持同步查询和 asyncio.to_thread 异步包装。
ClickHouse HTTP 接口通常运行在非标准端口（如 5887），与原生 TCP（9000）不同。

用法示例：
    from aave_crawler.clickhouse import ClickHouseClient
    from aave_crawler.config import load_config

    cfg = load_config()
    ch = ClickHouseClient(cfg.clickhouse)
    rows = ch.query("SELECT count() FROM eth_defi.rrmt_logs")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from aave_crawler.config import ClickHouseConfig

logger = logging.getLogger(__name__)


class ClickHouseClient:
    """轻量封装 clickhouse-connect Client，提供同步和异步查询接口。"""

    def __init__(self, cfg: ClickHouseConfig) -> None:
        self._cfg = cfg
        self._client: Client | None = None

    def _get_client(self) -> Client:
        """懒初始化：首次调用时建立 HTTP 连接，后续复用。"""
        if self._client is None:
            self._client = clickhouse_connect.get_client(
                host=self._cfg.host,
                port=self._cfg.port,
                username=self._cfg.user,
                password=self._cfg.password,
                database=self._cfg.database,
                connect_timeout=10,
                query_limit=0,  # 不限返回行数
                compress=False,
            )
            logger.debug(
                "ClickHouse 连接建立：%s:%d / %s",
                self._cfg.host,
                self._cfg.port,
                self._cfg.database,
            )
        return self._client

    def query(
        self,
        sql: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[tuple]:
        """同步执行查询，返回行列表（每行为 tuple）。

        参数占位符使用 {name} 格式（clickhouse-connect 风格）。
        """
        client = self._get_client()
        result = client.query(sql, parameters=parameters or {})
        return result.result_rows  # type: ignore[return-value]

    def query_with_names(
        self,
        sql: str,
        parameters: dict[str, Any] | None = None,
    ) -> tuple[list[str], list[tuple]]:
        """同步查询，同时返回 (column_names, rows)。"""
        client = self._get_client()
        result = client.query(sql, parameters=parameters or {})
        return result.column_names, result.result_rows  # type: ignore[return-value]

    async def query_async(
        self,
        sql: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[tuple]:
        """在线程池中执行同步查询，供 async 上下文使用。"""
        result = await asyncio.to_thread(self.query, sql, parameters)
        return result

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            logger.debug("ClickHouse 连接已关闭")

    def __enter__(self) -> "ClickHouseClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
