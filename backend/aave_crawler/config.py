"""从 config.yaml 加载配置"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from crawler_shared.config import CrawlerConfig
from crawler_shared.config import PostgresConfig
from crawler_shared.config import WatcherConfig as BaseWatcherConfig
from crawler_shared.config import build_dataclass, load_yaml_config


@dataclass
class ClickHouseConfig:
    host: str = "127.0.0.1"
    port: int = 9000
    user: str = "default"
    password: str = ""
    database: str = "default"


@dataclass
class WatcherConfig(BaseWatcherConfig):
    history_schema: str = "aave"  # aave_history 所在 schema


@dataclass
class AppConfig:
    rpc_url: str = ""
    protocol: str = "v3"  # aave 协议版本: v2 或 v3
    log_level: str = "info"  # 日志级别：debug / info / warning / error
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    clickhouse: ClickHouseConfig = field(default_factory=ClickHouseConfig)
    crawler: CrawlerConfig = field(default_factory=CrawlerConfig)
    watcher: WatcherConfig = field(default_factory=WatcherConfig)


def load_config(path: str | Path | None = None) -> AppConfig:
    raw = load_yaml_config(
        path,
        anchor_file=__file__,
        missing_message="找不到 config.yaml，请参照 config.yaml.example 创建。",
    )
    return AppConfig(
        rpc_url=raw.get("rpc_url", ""),
        log_level=raw.get("log_level", "info"),
        postgres=build_dataclass(PostgresConfig, raw.get("postgres")),
        clickhouse=build_dataclass(ClickHouseConfig, raw.get("clickhouse")),
        crawler=build_dataclass(CrawlerConfig, raw.get("crawler")),
        watcher=build_dataclass(WatcherConfig, raw.get("watcher")),
    )
