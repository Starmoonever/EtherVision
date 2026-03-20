from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from aave_crawler.api import service


class _FakePool:
    def __init__(self, symbol_row=None, price_row=None, cache_rows=None):
        self._symbol_row = symbol_row
        self._price_row = price_row
        self._cache_rows = cache_rows or []

    async def fetchrow(self, sql, *_args):
        if "CONCAT('0x', encode(reserve, 'hex'))" in sql:
            return self._symbol_row
        if "decode(replace(lower($1), '0x', ''), 'hex')" in sql:
            return self._price_row
        return None

    async def fetch(self, sql, *_args):
        if "FROM loan.eth_price_timestamp" in sql:
            return self._cache_rows
        return []


class _FakeResponse:
    def __init__(self, payload, status: int = 200):
        self._payload = payload
        self.status = status

    async def json(self):
        return self._payload

    async def text(self):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeClientSession:
    def __init__(self, payload, *args, **kwargs):
        self._payload = payload

    def get(self, _url):
        return _FakeResponse(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_get_eth_price_realtime_supports_compound_v3_asset() -> None:
    pool = _FakePool(
        symbol_row={
            "symbol": "UNI",
            "token_address": "0x1111111111111111111111111111111111111111",
        },
        price_row={
            "price_usd": "12.34",
            "timestamp": datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc),
        },
    )

    original_cache = dict(service._cache)
    service._cache["reserve_tokens_v3"] = [
        SimpleNamespace(
            symbol="WETH",
            token_address="0xc02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        )
    ]

    try:
        with (
            patch.object(service, "_get_common_data", new=AsyncMock()),
            patch.object(
                service,
                "get_assets_prices",
                new=AsyncMock(side_effect=Exception("execution reverted")),
            ),
        ):
            resp = await service.get_eth_price(
                MagicMock(), "uni", pool=cast(asyncpg.Pool, pool)
            )
    finally:
        service._cache.clear()
        service._cache.update(original_cache)

    assert resp.asset == "UNI"
    assert resp.token_address == "0x1111111111111111111111111111111111111111"
    assert resp.price_usd == "12.34"
    assert resp.timestamp == "2026-03-20T12:00:00Z"
    assert resp.source == "compound-snapshot"


@pytest.mark.asyncio
async def test_get_price_period_supports_compound_v3_asset() -> None:
    token_address = "0x2222222222222222222222222222222222222222"
    coin_key = f"ethereum:{token_address.lower()}"
    start_ts = int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp())
    end_ts = int(datetime(2024, 6, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp())
    payload = {
        "coins": {
            coin_key: {
                "prices": [
                    {"timestamp": start_ts, "price": 9.87},
                    {"timestamp": end_ts, "price": 9.91},
                ]
            }
        }
    }
    pool = _FakePool(
        symbol_row={"symbol": "UNI", "token_address": token_address},
        cache_rows=[],
    )

    original_cache = dict(service._cache)
    service._cache["reserve_tokens_v3"] = []

    try:
        with (
            patch.object(service, "_get_common_data", new=AsyncMock()),
            patch.object(service, "upsert_eth_price_timestamp", new=AsyncMock()),
            patch(
                "aiohttp.ClientSession",
                new=lambda *args, **kwargs: _FakeClientSession(
                    payload, *args, **kwargs
                ),
            ),
        ):
            resp = await service.get_price_period(
                MagicMock(),
                "uni",
                start_ts=start_ts,
                end_ts=end_ts,
                interval_minutes=60,
                pool=cast(asyncpg.Pool, pool),
            )
    finally:
        service._cache.clear()
        service._cache.update(original_cache)

    assert resp.asset == "UNI"
    assert resp.token_address == token_address
    assert resp.source == "defillama"
    assert [item.price_usd for item in resp.prices] == ["9.87", "9.91"]
    assert [item.timestamp for item in resp.prices] == [
        "2024-06-01T00:00:00Z",
        "2024-06-01T01:00:00Z",
    ]
