"""从 config.yaml 加载配置"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class PostgresConfig:
    host: str = "127.0.0.1"
    port: int = 5432
    user: str = "postgres"
    password: str = ""
    database: str = "postgres"

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


@dataclass
class CrawlerConfig:
    concurrency: int = 20
    batch_size: int = 100
    rpc_timeout: int = 20
    retry_count: int = 3


@dataclass
class WatcherConfig:
    interval: int = 60  # 轮询间隔（秒）
    lookback_minutes: int = 10  # 首次启动时水位线回退多少分钟
    history_schema: str = "aave"  # aave_history 所在 schema


@dataclass
class AppConfig:
    rpc_url: str = ""
    protocol: str = "v3"  # aave 协议版本: v2 或 v3
    log_level: str = "info"  # 日志级别：debug / info / warning / error
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    crawler: CrawlerConfig = field(default_factory=CrawlerConfig)
    watcher: WatcherConfig = field(default_factory=WatcherConfig)


def load_config(path: str | Path | None = None) -> AppConfig:
    """
    加载 config.yaml。
    默认查找顺序：
      1. 传入的 path
      2. 当前工作目录 config.yaml
      3. 本文件所在目录的父目录（backend/）config.yaml
    """
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    candidates.append(Path.cwd() / "config.yaml")
    candidates.append(Path(__file__).parent.parent / "config.yaml")

    for candidate in candidates:
        if candidate.exists():
            raw = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            pg_raw = raw.get("postgres", {})
            cr_raw = raw.get("crawler", {})
            wt_raw = raw.get("watcher", {})
            return AppConfig(
                rpc_url=raw.get("rpc_url", ""),
                log_level=raw.get("log_level", "info"),
                postgres=PostgresConfig(
                    **{
                        k: v
                        for k, v in pg_raw.items()
                        if k in PostgresConfig.__dataclass_fields__
                    }
                ),
                crawler=CrawlerConfig(
                    **{
                        k: v
                        for k, v in cr_raw.items()
                        if k in CrawlerConfig.__dataclass_fields__
                    }
                ),
                watcher=WatcherConfig(
                    **{
                        k: v
                        for k, v in wt_raw.items()
                        if k in WatcherConfig.__dataclass_fields__
                    }
                ),
            )

    raise FileNotFoundError("找不到 config.yaml，请参照 config.yaml.example 创建。")
