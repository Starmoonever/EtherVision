"""Load shared config for Morpho commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from crawler_shared.config import CrawlerConfig
from crawler_shared.config import PostgresConfig
from crawler_shared.config import WatcherConfig
from crawler_shared.config import build_dataclass, load_yaml_config


@dataclass
class AppConfig:
    rpc_url: str = ""
    protocol: str = "blue"
    log_level: str = "info"
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    crawler: CrawlerConfig = field(default_factory=CrawlerConfig)
    watcher: WatcherConfig = field(default_factory=WatcherConfig)


def load_config(path: str | Path | None = None) -> AppConfig:
    raw = load_yaml_config(
        path,
        anchor_file=__file__,
        missing_message="Could not find config.yaml. Copy from config.yaml.example.",
    )
    return AppConfig(
        rpc_url=raw.get("rpc_url", ""),
        protocol=raw.get("protocol", "blue"),
        log_level=raw.get("log_level", "info"),
        postgres=build_dataclass(PostgresConfig, raw.get("postgres")),
        crawler=build_dataclass(CrawlerConfig, raw.get("crawler")),
        watcher=build_dataclass(WatcherConfig, raw.get("watcher")),
    )
