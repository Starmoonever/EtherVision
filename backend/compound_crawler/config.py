"""Load config.yaml for Compound crawler."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from crawler_shared.config import CrawlerConfig
from crawler_shared.config import PostgresConfig
from crawler_shared.config import WatcherConfig
from crawler_shared.config import build_dataclass, load_yaml_config


@dataclass
class MarketStateConfig:
    # 采样周期，默认每小时一条
    snapshot_interval_minutes: int = 60
    # TimescaleDB 为可选能力，默认关闭
    use_timescaledb: bool = False
    # 目标 market 地址列表（0x...），为空时使用占位 market 写入
    v2_markets: list[str] = field(default_factory=list)
    v3_markets: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    eth_rpc_url: str = ""
    protocol: str = "v3"
    log_level: str = "info"
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    crawler: CrawlerConfig = field(default_factory=CrawlerConfig)
    watcher: WatcherConfig = field(default_factory=WatcherConfig)
    market_state: MarketStateConfig = field(default_factory=MarketStateConfig)


def load_config(path: str | Path | None = None) -> AppConfig:
    raw = load_yaml_config(
        path,
        anchor_file=__file__,
        missing_message="Could not find config.yaml. Copy from config.yaml.example.",
    )
    return AppConfig(
        eth_rpc_url=raw.get("eth_rpc_url", ""),
        log_level=raw.get("log_level", "info"),
        postgres=build_dataclass(PostgresConfig, raw.get("postgres")),
        crawler=build_dataclass(CrawlerConfig, raw.get("crawler")),
        watcher=build_dataclass(WatcherConfig, raw.get("watcher")),
        market_state=build_dataclass(
            MarketStateConfig, raw.get("compound_market_state")
        ),
    )
