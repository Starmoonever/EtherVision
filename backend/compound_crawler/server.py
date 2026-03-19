"""Compatibility wrapper: Compound API now shares the unified app entrypoint."""

from __future__ import annotations

from aave_crawler.server import app, create_app, main

__all__ = ["app", "create_app", "main"]
