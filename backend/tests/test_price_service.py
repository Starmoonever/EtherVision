from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from web3.exceptions import BadFunctionCallOutput

from crawler_shared.api import service
from crawler_shared.price_history import bucket_timestamp, get_historical_prices_usd


class _FakePool:
    def __init__(
        self,
        symbol_row=None,
        price_row=None,
        cache_rows=None,
        justlend_current_row=None,
        justlend_snapshot_row=None,
        tron_cache_row=None,
        tron_cache_rows=None,
        justlend_snapshot_bucket_rows=None,
    ):
        self._symbol_row = symbol_row
        self._price_row = price_row
        self._cache_rows = cache_rows or []
        self._justlend_current_row = justlend_current_row
        self._justlend_snapshot_row = justlend_snapshot_row
        self._tron_cache_row = tron_cache_row
        self._tron_cache_rows = tron_cache_rows or []
        self._justlend_snapshot_bucket_rows = justlend_snapshot_bucket_rows or []

    async def fetchrow(self, sql, *_args):
        if "CONCAT('0x', encode(reserve, 'hex'))" in sql:
            return self._symbol_row
        if "decode(replace(lower($1), '0x', ''), 'hex')" in sql:
            return self._price_row
        if "FROM loan.justlend_markets_current" in sql:
            return self._justlend_current_row
        if "FROM loan.justlend_market_snapshots" in sql:
            return self._justlend_snapshot_row
        if "FROM loan.tron_price_timestamp" in sql:
            return self._tron_cache_row
        return None

    async def fetch(self, sql, *_args):
        if "FROM loan.eth_price_timestamp" in sql:
            return self._cache_rows
        if "FROM loan.tron_price_timestamp" in sql:
            return self._tron_cache_rows
        if "FROM loan.justlend_market_snapshots" in sql and "snapshot_bucket" in sql:
            return self._justlend_snapshot_bucket_rows
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


def _fake_w3_with_ratio(raw_ratio: int):
    rate_call = MagicMock()
    rate_call.call = AsyncMock(return_value=raw_ratio)
    functions = MagicMock()
    functions.stEthPerToken.return_value = rate_call
    contract = MagicMock()
    contract.functions = functions
    eth = MagicMock()
    eth.contract.return_value = contract
    w3 = MagicMock()
    w3.eth = eth
    return w3, rate_call


def _fake_w3_with_wsteth_rate_fallback(
    *,
    steth_per_token_exc: Exception,
    get_steth_by_wsteth_raw: int,
):
    steth_per_token_call = MagicMock()
    steth_per_token_call.call = AsyncMock(side_effect=steth_per_token_exc)
    get_steth_by_wsteth_call = MagicMock()
    get_steth_by_wsteth_call.call = AsyncMock(return_value=get_steth_by_wsteth_raw)
    functions = MagicMock()
    functions.stEthPerToken.return_value = steth_per_token_call
    functions.getStETHByWstETH.return_value = get_steth_by_wsteth_call
    contract = MagicMock()
    contract.functions = functions
    eth = MagicMock()
    eth.contract.return_value = contract
    w3 = MagicMock()
    w3.eth = eth
    return w3, steth_per_token_call, get_steth_by_wsteth_call


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
async def test_get_price_realtime_derives_wsteth_from_steth_price_and_onchain_ratio() -> (
    None
):
    w3, rate_call = _fake_w3_with_ratio(int(Decimal("1.15") * Decimal(10**18)))

    with (
        patch.object(service, "get_assets_prices", new=AsyncMock(return_value=[0])),
        patch.object(
            service,
            "_fetch_defillama_current_price",
            new=AsyncMock(return_value=(Decimal("2000"), 1717200000)),
        ),
    ):
        resp = await service.get_price(
            w3,
            symbol="wstETH",
            address=None,
            pool=None,
        )

    assert resp.asset == "wstETH"
    assert resp.token_address == "0x7f39C581F595B53c5cb5bA2D5dA6c935E2Ca0Ae6"
    assert resp.price_usd == "2300.00"
    assert resp.timestamp == "2024-06-01T00:00:00Z"
    assert resp.source == "derived-defillama+onchain"
    rate_call.call.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_get_price_realtime_derives_wsteth_with_selector_fallback() -> None:
    w3, steth_per_token_call, get_steth_by_wsteth_call = (
        _fake_w3_with_wsteth_rate_fallback(
            steth_per_token_exc=BadFunctionCallOutput("empty response"),
            get_steth_by_wsteth_raw=int(Decimal("1.12") * Decimal(10**18)),
        )
    )

    with (
        patch.object(service, "get_assets_prices", new=AsyncMock(return_value=[0])),
        patch.object(
            service,
            "_fetch_defillama_current_price",
            new=AsyncMock(return_value=(Decimal("2000"), 1717200000)),
        ),
    ):
        resp = await service.get_price(
            w3,
            symbol="wstETH",
            address=None,
            pool=None,
        )

    assert resp.price_usd == "2240.00"
    assert resp.source == "derived-defillama+onchain"
    steth_per_token_call.call.assert_awaited_once_with()
    get_steth_by_wsteth_call.call.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_get_price_realtime_prefers_coingecko_for_wsteth_before_derived_price() -> (
    None
):
    with (
        patch.object(service, "get_assets_prices", new=AsyncMock(return_value=[0])),
        patch.object(
            service,
            "_fetch_coingecko_current_price",
            new=AsyncMock(return_value=(Decimal("2456.78"), 1717200000)),
        ),
        patch.object(
            service,
            "_get_current_derived_price",
            new=AsyncMock(side_effect=AssertionError("should not call derived price")),
        ),
    ):
        resp = await service.get_price(
            MagicMock(),
            symbol="wstETH",
            address=None,
            pool=None,
        )

    assert resp.asset == "wstETH"
    assert resp.price_usd == "2456.78"
    assert resp.timestamp == "2024-06-01T00:00:00Z"
    assert resp.source == "coingecko"


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
            "crawler_shared.price_history.upsert_ethereum_price_cache", new=AsyncMock()
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
async def test_get_price_historical_derives_wsteth_with_bucket_block_ratio() -> None:
    w3, rate_call = _fake_w3_with_ratio(int(Decimal("1.08") * Decimal(10**18)))
    requested_ts = int(datetime(2024, 6, 1, 0, 7, 12, tzinfo=timezone.utc).timestamp())
    bucket_ts = bucket_timestamp(requested_ts)

    with (
        patch.object(
            service,
            "get_historical_price_usd",
            new=AsyncMock(return_value=(Decimal("2500"), bucket_ts, "defillama")),
        ),
        patch.object(
            service,
            "_block_at_timestamp",
            new=AsyncMock(return_value=19_000_000),
        ),
    ):
        resp = await service.get_price(
            w3,
            symbol="wstETH",
            address=None,
            pool=None,
            timestamp=requested_ts,
        )

    assert resp.asset == "wstETH"
    assert resp.price_usd == "2700.00"
    assert resp.timestamp == "2024-06-01T00:00:00Z"
    assert resp.source == "derived-defillama+onchain"
    rate_call.call.assert_awaited_once_with(block_identifier=19_000_000)


@pytest.mark.asyncio
async def test_get_price_period_derives_wsteth_from_bucket_prices_and_block_rates() -> (
    None
):
    bucket0 = int(datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    bucket1 = int(datetime(2024, 6, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp())
    rate_call = MagicMock()
    rate_call.call = AsyncMock(
        side_effect=[
            int(Decimal("1.10") * Decimal(10**18)),
            int(Decimal("1.20") * Decimal(10**18)),
        ]
    )
    functions = MagicMock()
    functions.stEthPerToken.return_value = rate_call
    contract = MagicMock()
    contract.functions = functions
    eth = MagicMock()
    eth.contract.return_value = contract
    w3 = MagicMock()
    w3.eth = eth

    with (
        patch.object(
            service,
            "get_historical_bucket_prices_usd",
            new=AsyncMock(
                return_value={bucket0: Decimal("2000"), bucket1: Decimal("2100")}
            ),
        ),
        patch.object(
            service,
            "_block_at_timestamp",
            new=AsyncMock(side_effect=[18_000_000, 18_000_300]),
        ),
    ):
        resp = await service.get_price_period_service(
            w3,
            None,
            symbol="wstETH",
            address=None,
            start=bucket0,
            end=bucket1,
            interval=60,
        )

    assert resp.asset == "wstETH"
    assert resp.token_address == "0x7f39C581F595B53c5cb5bA2D5dA6c935E2Ca0Ae6"
    assert resp.source == "derived-defillama+onchain"
    assert [item.price_usd for item in resp.prices] == ["2200.00", "2520.00"]
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
            "crawler_shared.price_history.upsert_ethereum_price_cache", new=AsyncMock()
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
            "crawler_shared.price_history.upsert_ethereum_price_cache", new=AsyncMock()
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
async def test_get_price_supports_tron_symbol_from_current_snapshot() -> None:
    token_address = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    pool = _FakePool(
        justlend_current_row={
            "price_usd": "1.00",
            "snapshot_at": datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc),
        }
    )

    with (
        patch(
            "crawler_shared.api.service.ensure_tron_price_cache_table",
            new=AsyncMock(),
        ),
        patch(
            "crawler_shared.api.service.upsert_tron_price_cache",
            new=AsyncMock(),
        ) as upsert_cache,
    ):
        resp = await service.get_price(
            MagicMock(),
            symbol="USDT",
            address=None,
            chain="tron",
            pool=cast(asyncpg.Pool, pool),
        )

    assert resp.asset == "USDT"
    assert resp.token_address == token_address
    assert resp.price_usd == "1.00"
    assert resp.source == "justlend-current"
    upsert_cache.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_price_tron_address_query_writes_symbol_in_cache() -> None:
    token_address = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    pool = _FakePool(
        justlend_current_row={
            "price_usd": "1.00",
            "snapshot_at": datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc),
        }
    )

    with (
        patch(
            "crawler_shared.api.service.ensure_tron_price_cache_table",
            new=AsyncMock(),
        ),
        patch(
            "crawler_shared.api.service.upsert_tron_price_cache",
            new=AsyncMock(),
        ) as upsert_cache,
    ):
        resp = await service.get_price(
            MagicMock(),
            symbol=None,
            address=token_address,
            chain="tron",
            pool=cast(asyncpg.Pool, pool),
        )

    assert resp.asset == "USDT"
    assert resp.token_address == token_address
    assert resp.price_usd == "1.00"
    assert resp.source == "justlend-current"
    upsert_cache.assert_awaited_once()
    assert upsert_cache.await_args is not None
    assert upsert_cache.await_args.args[3] == "USDT"


@pytest.mark.asyncio
async def test_get_price_tron_historical_falls_back_to_snapshot_when_cache_misses() -> (
    None
):
    token_address = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    requested_ts = int(datetime(2026, 4, 16, 2, 13, 0, tzinfo=timezone.utc).timestamp())
    pool = _FakePool(
        justlend_snapshot_row={
            "price_usd": "1.01",
            "snapshot_at": datetime(2026, 4, 16, 0, 0, 0, tzinfo=timezone.utc),
        }
    )

    with (
        patch(
            "crawler_shared.api.service.ensure_tron_price_cache_table",
            new=AsyncMock(),
        ),
        patch(
            "crawler_shared.api.service.upsert_tron_price_cache",
            new=AsyncMock(),
        ) as upsert_cache,
    ):
        resp = await service.get_price(
            MagicMock(),
            symbol="USDT",
            address=None,
            chain="tron",
            pool=cast(asyncpg.Pool, pool),
            timestamp=requested_ts,
        )

    assert resp.asset == "USDT"
    assert resp.token_address == token_address
    assert resp.price_usd == "1.01"
    assert resp.source == "justlend-snapshot"
    upsert_cache.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_price_period_supports_tron_cache_and_snapshot_mix() -> None:
    token_address = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    bucket0 = int(datetime(2026, 4, 16, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    bucket1 = int(datetime(2026, 4, 16, 1, 0, 0, tzinfo=timezone.utc).timestamp())
    pool = _FakePool(
        tron_cache_rows=[{"timestamp_bucket": bucket0, "price_usd": "1.00"}],
        justlend_snapshot_bucket_rows=[
            {"timestamp_bucket": bucket1, "price_usd": "1.02"},
        ],
    )

    with patch(
        "crawler_shared.api.service.ensure_tron_price_cache_table",
        new=AsyncMock(),
    ):
        resp = await service.get_price_period_service(
            MagicMock(),
            cast(asyncpg.Pool, pool),
            symbol="USDT",
            address=None,
            chain="tron",
            start=bucket0,
            end=bucket1,
            interval=60,
        )

    assert resp.asset == "USDT"
    assert resp.token_address == token_address
    assert resp.source == "justlend-mixed"
    assert [item.price_usd for item in resp.prices] == ["1.00", "1.02"]


@pytest.mark.asyncio
async def test_get_price_period_tron_snapshot_fallback_does_not_forward_fill_buckets() -> (
    None
):
    bucket0 = int(datetime(2026, 4, 16, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    bucket1 = int(datetime(2026, 4, 16, 1, 0, 0, tzinfo=timezone.utc).timestamp())
    bucket2 = int(datetime(2026, 4, 16, 2, 0, 0, tzinfo=timezone.utc).timestamp())
    pool = _FakePool(
        justlend_snapshot_bucket_rows=[
            {"timestamp_bucket": bucket1, "price_usd": "1.02"},
        ],
    )

    with patch(
        "crawler_shared.api.service.ensure_tron_price_cache_table",
        new=AsyncMock(),
    ):
        resp = await service.get_price_period_service(
            MagicMock(),
            cast(asyncpg.Pool, pool),
            symbol="USDT",
            address=None,
            chain="tron",
            start=bucket0,
            end=bucket2,
            interval=60,
        )

    assert [item.timestamp for item in resp.prices] == [
        "2026-04-16T01:00:00Z",
    ]
    assert [item.price_usd for item in resp.prices] == ["1.02"]


@pytest.mark.asyncio
async def test_get_price_period_rejects_interval_under_15_minutes() -> None:
    with pytest.raises(Exception) as exc_info:
        await service.get_price_period_service(
            MagicMock(),
            None,
            symbol="eth",
            address=None,
            start=1,
            end=2,
            interval=14,
        )
    assert ">= 15" in str(exc_info.value)


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
    assert "EVM 或 TRON" in str(exc_info.value)


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
