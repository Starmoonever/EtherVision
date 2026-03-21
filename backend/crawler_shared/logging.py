"""Shared logging helpers for CLI entrypoints."""

from __future__ import annotations

import logging
from collections.abc import Iterable


def setup_cli_logging(verbose: bool, *, quiet_loggers: Iterable[str] = ()) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for logger_name in quiet_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
