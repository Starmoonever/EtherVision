"""Shared TRON RPC client primitives."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.request import Request, urlopen


class TronRpcClient:
    """Minimal JSON-over-HTTP client wrapper for TRON full node endpoints."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"

        def _load() -> dict[str, Any]:
            request = Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))

        return await asyncio.to_thread(_load)

    async def close(self) -> None:
        return None


def build_tron_rpc_client(base_url: str, timeout: float = 10.0) -> TronRpcClient | None:
    if not base_url.strip():
        return None
    return TronRpcClient(base_url=base_url, timeout=timeout)
