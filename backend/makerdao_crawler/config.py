"""Load config.yaml for MakerDAO scaffold."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from crawler_shared.config import CrawlerConfig
from crawler_shared.config import PostgresConfig
from crawler_shared.config import WatcherConfig
from crawler_shared.config import build_dataclass, load_yaml_config


@dataclass
class MakerDaoConfig:
    chain: str = "ethereum"
    vat_address: str = ""
    spotter_address: str = ""
    dog_address: str = ""
    ilk_names: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    eth_rpc_url: str = ""
    tron_rpc_url: str = ""
    log_level: str = "info"
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    crawler: CrawlerConfig = field(default_factory=CrawlerConfig)
    watcher: WatcherConfig = field(default_factory=WatcherConfig)
    makerdao: MakerDaoConfig = field(default_factory=MakerDaoConfig)


def load_config(path: str | Path | None = None) -> AppConfig:
    raw = load_yaml_config(
        path,
        anchor_file=__file__,
        missing_message="Could not find config.yaml. Copy from config.yaml.example.",
    )
    return AppConfig(
        eth_rpc_url=raw.get("eth_rpc_url", ""),
        tron_rpc_url=raw.get("tron_rpc_url", ""),
        log_level=raw.get("log_level", "info"),
        postgres=build_dataclass(PostgresConfig, raw.get("postgres")),
        crawler=build_dataclass(CrawlerConfig, raw.get("crawler")),
        watcher=build_dataclass(WatcherConfig, raw.get("watcher")),
        makerdao=build_dataclass(MakerDaoConfig, raw.get("makerdao")),
    )
