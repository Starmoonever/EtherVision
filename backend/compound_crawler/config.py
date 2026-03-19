"""Load config.yaml for Compound crawler."""

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
    ssl: str = "prefer"


@dataclass
class CrawlerConfig:
    concurrency: int = 20
    batch_size: int = 100
    rpc_timeout: int = 20
    retry_count: int = 3


@dataclass
class WatcherConfig:
    interval: int = 60
    lookback_minutes: int = 10


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
    rpc_url: str = ""
    protocol: str = "v3"
    log_level: str = "info"
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    crawler: CrawlerConfig = field(default_factory=CrawlerConfig)
    watcher: WatcherConfig = field(default_factory=WatcherConfig)
    market_state: MarketStateConfig = field(default_factory=MarketStateConfig)


def load_config(path: str | Path | None = None) -> AppConfig:
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
            ms_raw = raw.get("compound_market_state", {})
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
                market_state=MarketStateConfig(
                    **{
                        k: v
                        for k, v in ms_raw.items()
                        if k in MarketStateConfig.__dataclass_fields__
                    }
                ),
            )

    raise FileNotFoundError(
        "Could not find config.yaml. Copy from config.yaml.example."
    )
