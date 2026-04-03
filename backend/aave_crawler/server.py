"""Compatibility wrapper: unified backend server now lives in crawler_shared."""

from __future__ import annotations

from crawler_shared.server import app, create_app, main

__all__ = ["app", "create_app", "main"]
