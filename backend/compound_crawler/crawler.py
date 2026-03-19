"""Batch crawler entry for Compound positions."""

from __future__ import annotations

import logging

from .config import AppConfig

logger = logging.getLogger(__name__)


async def run_crawler(
    cfg: AppConfig, pool, limit: int | None = None, dry_run: bool = False
) -> None:
    logger.info(
        "Compound crawler scaffold invoked: protocol=%s limit=%s dry_run=%s",
        cfg.protocol,
        limit,
        dry_run,
    )
    _ = pool
