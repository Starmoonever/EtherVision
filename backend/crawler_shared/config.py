"""Shared config primitives and YAML loading helpers."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping, TypeVar

import yaml

T = TypeVar("T")


@dataclass
class PostgresConfig:
    host: str = "127.0.0.1"
    port: int = 5432
    user: str = "postgres"
    password: str = ""
    database: str = "postgres"
    ssl: str = "prefer"

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
    interval: int = 60
    lookback_minutes: int = 10


def load_yaml_config(
    path: str | Path | None = None,
    *,
    anchor_file: str | Path,
    missing_message: str,
) -> dict[str, Any]:
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    candidates.append(Path.cwd() / "config.yaml")
    candidates.append(Path(anchor_file).resolve().parent.parent / "config.yaml")

    for candidate in candidates:
        if candidate.exists():
            raw = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"配置文件顶层必须是对象: {candidate}")
            return raw

    raise FileNotFoundError(missing_message)


def build_dataclass(dataclass_type: type[T], raw: Mapping[str, Any] | None) -> T:
    if not is_dataclass(dataclass_type):
        raise TypeError(f"Expected dataclass type, got {dataclass_type!r}")
    values = raw or {}
    allowed_keys = {field.name for field in fields(dataclass_type)}
    return dataclass_type(
        **{key: value for key, value in values.items() if key in allowed_keys}
    )
