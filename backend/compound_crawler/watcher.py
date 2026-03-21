"""Incremental watcher entry for Compound updates."""

from __future__ import annotations

import logging

from .config import AppConfig

logger = logging.getLogger(__name__)


async def run_watcher(
    cfg: AppConfig, pool, interval: int, lookback_minutes: int
) -> None:
    logger.info(
        "Compound watcher scaffold invoked: protocol=%s interval=%s lookback_minutes=%s",
        cfg.protocol,
        interval,
        lookback_minutes,
    )
    _ = pool
