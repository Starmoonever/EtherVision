from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from crawler_shared.api import service
from crawler_shared.price_history import bucket_timestamp, get_historical_prices_usd


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

    def get(self, url):
        if callable(self._payload):
            return _FakeResponse(self._payload(url))
        return _FakeResponse(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _CancelledClientSession:
    def __init__(self, *args, **kwargs):
        pass

    def get(self, _url):
        raise asyncio.CancelledError()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_get_price_realtime_supports_address_compound_snapshot_fallback() -> None:
    token_address = "0x1111111111111111111111111111111111111111"
    pool = _FakePool(
        price_row={
            "price_usd": "12.34",
            "timestamp": datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc),
        },
    )

    with patch.object(
        service,
        "get_assets_prices",
        new=AsyncMock(side_effect=Exception("execution reverted")),
    ):
        resp = await service.get_price(
            MagicMock(),
            symbol=None,
            address=token_address,
            pool=cast(asyncpg.Pool, pool),
        )

    assert resp.asset == token_address
    assert resp.token_address == token_address
    assert resp.price_usd == "12.34"
    assert resp.timestamp == "2026-03-20T12:00:00Z"
    assert resp.source == "compound-snapshot"


@pytest.mark.asyncio
async def test_get_price_period_supports_direct_evm_address() -> None:
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
        cache_rows=[],
    )

    with (
        patch(
            "crawler_shared.price_history.upsert_eth_price_timestamp", new=AsyncMock()
        ),
        patch(
            "aiohttp.ClientSession",
            new=lambda *args, **kwargs: _FakeClientSession(payload, *args, **kwargs),
        ),
    ):
        resp = await service.get_price_period_service(
            MagicMock(),
            cast(asyncpg.Pool, pool),
            symbol=None,
            address=token_address,
            start=start_ts,
            end=end_ts,
            interval=60,
        )

    assert resp.asset == token_address
    assert resp.token_address == token_address
    assert resp.source == "defillama"
    assert [item.price_usd for item in resp.prices] == ["9.87", "9.91"]
    assert [item.timestamp for item in resp.prices] == [
        "2024-06-01T00:00:00Z",
        "2024-06-01T01:00:00Z",
    ]


@pytest.mark.asyncio
async def test_get_historical_prices_usd_supports_multiple_assets() -> None:
    bucket_ts = int(datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    pool = _FakePool(
        cache_rows=[
            {
                "asset_address": "0x1111111111111111111111111111111111111111",
                "price_usd": "1.23",
            }
        ]
    )

    def _payload(url: str):
        assert "0x2222222222222222222222222222222222222222" in url.lower()
        return {
            "coins": {
                "ethereum:0x2222222222222222222222222222222222222222": {
                    "price": 4.56,
                    "timestamp": bucket_ts,
                }
            }
        }

    with (
        patch(
            "crawler_shared.price_history.upsert_eth_price_timestamp", new=AsyncMock()
        ) as upsert_cache,
        patch(
            "aiohttp.ClientSession",
            new=lambda *args, **kwargs: _FakeClientSession(_payload, *args, **kwargs),
        ),
    ):
        prices, used_bucket, source = await get_historical_prices_usd(
            cast(asyncpg.Pool, pool),
            assets=[
                ("0x1111111111111111111111111111111111111111", "USDC"),
                ("0x2222222222222222222222222222222222222222", "WETH"),
            ],
            requested_ts=bucket_ts + 123,
        )

    assert used_bucket == bucket_ts
    assert source == "defillama"
    assert prices["0x1111111111111111111111111111111111111111"] == Decimal("1.23")
    assert prices["0x2222222222222222222222222222222222222222"] == Decimal("4.56")
    upsert_cache.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_price_historical_snaps_timestamp_to_bucket() -> None:
    token_address = "0x8888888888888888888888888888888888888888"
    coin_key = f"ethereum:{token_address.lower()}"
    requested_ts = int(datetime(2024, 6, 1, 0, 7, 12, tzinfo=timezone.utc).timestamp())
    bucket_ts = int(datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    payload = {
        "coins": {
            coin_key: {
                "price": 10.25,
                "timestamp": requested_ts,
            }
        }
    }

    with patch(
        "aiohttp.ClientSession",
        new=lambda *args, **kwargs: _FakeClientSession(payload, *args, **kwargs),
    ):
        resp = await service.get_price(
            MagicMock(),
            symbol=None,
            address=token_address,
            pool=None,
            timestamp=requested_ts,
        )

    assert resp.price_usd == "10.25"
    assert resp.timestamp == "2024-06-01T00:00:00Z"
    assert bucket_timestamp(requested_ts) == bucket_ts


@pytest.mark.asyncio
async def test_get_price_period_snaps_points_to_buckets() -> None:
    token_address = "0x9999999999999999999999999999999999999999"
    coin_key = f"ethereum:{token_address.lower()}"
    start_ts = int(datetime(2024, 6, 1, 0, 7, 0, tzinfo=timezone.utc).timestamp())
    end_ts = int(datetime(2024, 6, 1, 1, 7, 0, tzinfo=timezone.utc).timestamp())
    bucket0 = int(datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    bucket1 = int(datetime(2024, 6, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp())
    payload = {
        "coins": {
            coin_key: {
                "prices": [
                    {"timestamp": bucket0, "price": 9.87},
                    {"timestamp": bucket1, "price": 9.91},
                ]
            }
        }
    }

    with patch(
        "aiohttp.ClientSession",
        new=lambda *args, **kwargs: _FakeClientSession(payload, *args, **kwargs),
    ):
        resp = await service.get_price_period_service(
            MagicMock(),
            None,
            symbol=None,
            address=token_address,
            start=start_ts,
            end=end_ts,
            interval=60,
        )

    assert [item.timestamp for item in resp.prices] == [
        "2024-06-01T00:00:00Z",
        "2024-06-01T01:00:00Z",
    ]


@pytest.mark.asyncio
async def test_get_eth_price_realtime_supports_evm_address_defillama_fallback() -> None:
    token_address = "0x3333333333333333333333333333333333333333"
    coin_key = f"ethereum:{token_address.lower()}"
    payload = {
        "coins": {
            coin_key: {
                "price": 123.456,
                "timestamp": 1717200000,
            }
        }
    }

    with (
        patch.object(service, "get_assets_prices", new=AsyncMock(return_value=[0])),
        patch(
            "aiohttp.ClientSession",
            new=lambda *args, **kwargs: _FakeClientSession(payload, *args, **kwargs),
        ),
    ):
        resp = await service.get_price(
            MagicMock(),
            symbol=None,
            address=token_address,
            pool=None,
        )

    assert resp.asset == token_address
    assert resp.token_address == token_address
    assert resp.price_usd == "123.46"
    assert resp.timestamp == "2024-06-01T00:00:00Z"
    assert resp.source == "defillama"


@pytest.mark.asyncio
async def test_get_price_realtime_falls_back_to_defillama_historical_now() -> None:
    token_address = "0x5555555555555555555555555555555555555555"
    coin_key = f"ethereum:{token_address.lower()}"

    def _payload(url: str):
        if "/prices/current/" in url:
            return {"coins": {}}
        return {
            "coins": {
                coin_key: {
                    "price": 456.789,
                    "timestamp": 1717200000,
                }
            }
        }

    with (
        patch.object(
            service,
            "get_assets_prices",
            new=AsyncMock(side_effect=Exception("execution reverted")),
        ),
        patch(
            "aiohttp.ClientSession",
            new=lambda *args, **kwargs: _FakeClientSession(_payload, *args, **kwargs),
        ),
    ):
        resp = await service.get_price(
            MagicMock(),
            symbol=None,
            address=token_address,
            pool=None,
        )

    assert resp.asset == token_address
    assert resp.token_address == token_address
    assert resp.price_usd == "456.79"
    assert resp.timestamp == "2024-06-01T00:00:00Z"
    assert resp.source == "defillama"


@pytest.mark.asyncio
async def test_get_price_realtime_falls_back_to_coingecko() -> None:
    token_address = "0x6666666666666666666666666666666666666666"
    normalized = token_address.lower()

    def _payload(url: str):
        if "coins.llama.fi" in url:
            return {"coins": {}}
        if "/simple/token_price/ethereum" in url:
            return {
                normalized: {
                    "usd": 789.1234,
                    "last_updated_at": 1717200000,
                }
            }
        return {}

    with (
        patch.object(
            service,
            "get_assets_prices",
            new=AsyncMock(side_effect=Exception("execution reverted")),
        ),
        patch(
            "aiohttp.ClientSession",
            new=lambda *args, **kwargs: _FakeClientSession(_payload, *args, **kwargs),
        ),
    ):
        resp = await service.get_price(
            MagicMock(),
            symbol=None,
            address=token_address,
            pool=None,
        )

    assert resp.asset == token_address
    assert resp.token_address == token_address
    assert resp.price_usd == "789.12"
    assert resp.timestamp == "2024-06-01T00:00:00Z"
    assert resp.source == "coingecko"


@pytest.mark.asyncio
async def test_get_price_realtime_cancelled_http_fallback_returns_502() -> None:
    token_address = "0x7777777777777777777777777777777777777777"

    with (
        patch.object(
            service,
            "get_assets_prices",
            new=AsyncMock(side_effect=Exception("execution reverted")),
        ),
        patch(
            "aiohttp.ClientSession",
            new=lambda *args, **kwargs: _CancelledClientSession(*args, **kwargs),
        ),
    ):
        with pytest.raises(Exception) as exc_info:
            await service.get_price(
                MagicMock(),
                symbol=None,
                address=token_address,
                pool=None,
            )

    assert "无法连接 DeFiLlama" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_price_period_supports_registered_symbol() -> None:
    token_address = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    coin_key = f"ethereum:{token_address.lower()}"
    start_ts = int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp())
    end_ts = int(datetime(2024, 6, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp())
    payload = {
        "coins": {
            coin_key: {
                "prices": [
                    {"timestamp": start_ts, "price": 1.23},
                    {"timestamp": end_ts, "price": 1.45},
                ]
            }
        }
    }

    with (
        patch(
            "crawler_shared.price_history.upsert_eth_price_timestamp", new=AsyncMock()
        ),
        patch(
            "aiohttp.ClientSession",
            new=lambda *args, **kwargs: _FakeClientSession(payload, *args, **kwargs),
        ),
    ):
        resp = await service.get_price_period_service(
            MagicMock(),
            None,
            symbol="eth",
            address=None,
            start=start_ts,
            end=end_ts,
            interval=60,
        )

    assert resp.asset == "ETH"
    assert resp.token_address == token_address
    assert [item.price_usd for item in resp.prices] == ["1.23", "1.45"]


@pytest.mark.asyncio
async def test_get_price_rejects_unknown_symbol() -> None:
    with pytest.raises(Exception) as exc_info:
        await service.get_price(
            MagicMock(),
            symbol="UNI",
            address=None,
            pool=None,
        )
    assert "受支持资产" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_price_rejects_invalid_address() -> None:
    with pytest.raises(Exception) as exc_info:
        await service.get_price(
            MagicMock(),
            symbol=None,
            address="not-an-address",
            pool=None,
        )
    assert "有效的 EVM 地址" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_price_period_rejects_symbol_and_address_together() -> None:
    token_address = "0x4444444444444444444444444444444444444444"
    with pytest.raises(Exception) as exc_info:
        await service.get_price_period_service(
            MagicMock(),
            None,
            symbol="eth",
            address=token_address,
            start=1,
            end=2,
            interval=60,
        )
    assert "只能提供其中一个" in str(exc_info.value)
