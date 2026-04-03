from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from web3 import AsyncWeb3

from compound_crawler import crawler
from compound_crawler.config import AppConfig


class _FakeEth:
    def __init__(self, code: bytes):
        self._code = code
        self.calls: list[tuple[str, int | None]] = []

    async def get_code(self, address, block_identifier=None):
        self.calls.append((str(address), block_identifier))
        return self._code


class _FakeW3:
    def __init__(self, code: bytes):
        self.eth = _FakeEth(code)


class _FakeFeedCall:
    def __init__(
        self,
        *,
        historical_result: object | None = None,
        latest_result: object | None = None,
        historical_exc: Exception | None = None,
        latest_exc: Exception | None = None,
    ) -> None:
        self._historical_result = historical_result
        self._latest_result = latest_result
        self._historical_exc = historical_exc
        self._latest_exc = latest_exc

    async def call(self, block_identifier=None):
        if block_identifier is None:
            if self._latest_exc is not None:
                raise self._latest_exc
            return self._latest_result
        if self._historical_exc is not None:
            raise self._historical_exc
        return self._historical_result


class _FakeFeedFunctions:
    def __init__(
        self,
        *,
        historical_exc: Exception | None = None,
        latest_exc: Exception | None = None,
    ) -> None:
        self._historical_exc = historical_exc
        self._latest_exc = latest_exc

    def decimals(self) -> _FakeFeedCall:
        return _FakeFeedCall(
            historical_result=8,
            latest_result=8,
            historical_exc=self._historical_exc,
            latest_exc=self._latest_exc,
        )

    def latestRoundData(self) -> _FakeFeedCall:
        return _FakeFeedCall(
            historical_result=(0, 200_000_000_000, 0, 0, 0),
            latest_result=(0, 200_000_000_000, 0, 0, 0),
            historical_exc=self._historical_exc,
            latest_exc=self._latest_exc,
        )


class _FakeFeedContract:
    def __init__(
        self,
        *,
        historical_exc: Exception | None = None,
        latest_exc: Exception | None = None,
    ) -> None:
        self.functions = _FakeFeedFunctions(
            historical_exc=historical_exc,
            latest_exc=latest_exc,
        )


class _FakeFeedEth(_FakeEth):
    def __init__(
        self,
        code: bytes,
        *,
        historical_exc: Exception | None = None,
        latest_exc: Exception | None = None,
    ) -> None:
        super().__init__(code)
        self._historical_exc = historical_exc
        self._latest_exc = latest_exc

    def contract(self, address, abi):
        return _FakeFeedContract(
            historical_exc=self._historical_exc,
            latest_exc=self._latest_exc,
        )


class _FakeFeedW3:
    def __init__(
        self,
        code: bytes,
        *,
        historical_exc: Exception | None = None,
        latest_exc: Exception | None = None,
    ) -> None:
        self.eth = _FakeFeedEth(
            code,
            historical_exc=historical_exc,
            latest_exc=latest_exc,
        )


@pytest.mark.asyncio
async def test_collect_v3_markets_skips_undeployed_market() -> None:
    cfg = cast(
        AppConfig,
        SimpleNamespace(crawler=SimpleNamespace(concurrency=2), protocol="v3"),
    )
    w3 = cast(AsyncWeb3, _FakeW3(b""))
    point_ts = datetime(2022, 8, 28, 11, 0, 0, tzinfo=timezone.utc)
    deployment_cache: dict[str, dict[str, int]] = {}

    with patch.object(
        crawler, "_collect_v3_market_at_block", new=AsyncMock()
    ) as collect:
        (
            market_rows,
            reserve_rows,
            config_rows,
            config_asset_rows,
            status_rows,
        ) = await crawler._collect_v3_markets_at_block(
            cfg,
            w3,
            point_ts=point_ts,
            block_number=15427392,
            markets=["0x3Afdc9BCA9213A35503b077a6072F3D0d5AB0840"],
            metadata_cache={},
            deployment_cache=deployment_cache,
        )

    assert market_rows == []
    assert reserve_rows == []
    assert config_rows == []
    assert config_asset_rows == []
    assert status_rows == []
    assert collect.await_count == 0
    assert len(cast(_FakeW3, w3).eth.calls) == 1
    assert (
        deployment_cache["0x3afdc9bca9213a35503b077a6072f3d0d5ab0840"][
            "missing_through"
        ]
        == 15427392
    )


@pytest.mark.asyncio
async def test_collect_v3_markets_reuses_missing_code_cache() -> None:
    cfg = cast(
        AppConfig,
        SimpleNamespace(crawler=SimpleNamespace(concurrency=2), protocol="v3"),
    )
    w3 = cast(AsyncWeb3, _FakeW3(b""))
    point_ts = datetime(2022, 8, 28, 11, 0, 0, tzinfo=timezone.utc)
    deployment_cache: dict[str, dict[str, int]] = {}
    market = "0x5D409e56D886231aDAf00c8775665AD0f9897b56"

    with patch.object(
        crawler, "_collect_v3_market_at_block", new=AsyncMock()
    ) as collect:
        await crawler._collect_v3_markets_at_block(
            cfg,
            w3,
            point_ts=point_ts,
            block_number=15427392,
            markets=[market],
            metadata_cache={},
            deployment_cache=deployment_cache,
        )
        await crawler._collect_v3_markets_at_block(
            cfg,
            w3,
            point_ts=point_ts,
            block_number=15427300,
            markets=[market],
            metadata_cache={},
            deployment_cache=deployment_cache,
        )

    assert collect.await_count == 0
    assert len(cast(_FakeW3, w3).eth.calls) == 1


@pytest.mark.asyncio
async def test_collect_v2_markets_skips_undeployed_market() -> None:
    cfg = cast(
        AppConfig,
        SimpleNamespace(crawler=SimpleNamespace(concurrency=2), protocol="v2"),
    )
    w3 = cast(AsyncWeb3, _FakeW3(b""))
    point_ts = datetime(2022, 8, 28, 11, 0, 0, tzinfo=timezone.utc)
    deployment_cache: dict[str, dict[str, int]] = {}

    with patch.object(
        crawler, "_collect_v2_market_at_block", new=AsyncMock()
    ) as collect:
        market_rows, reserve_rows = await crawler._collect_v2_markets_at_block(
            cfg,
            w3,
            point_ts=point_ts,
            block_number=15427392,
            markets=["0x39AA39c021dfbaE8faC545936693aC917d5E7563"],
            metadata_cache={},
            deployment_cache=deployment_cache,
        )

    assert market_rows == []
    assert reserve_rows == []
    assert collect.await_count == 0
    assert len(cast(_FakeW3, w3).eth.calls) == 1
    assert (
        deployment_cache["0x39aa39c021dfbae8fac545936693ac917d5e7563"][
            "missing_through"
        ]
        == 15427392
    )


@pytest.mark.asyncio
async def test_collect_v2_markets_calls_collector_when_deployed() -> None:
    cfg = cast(
        AppConfig,
        SimpleNamespace(crawler=SimpleNamespace(concurrency=2), protocol="v2"),
    )
    w3 = cast(AsyncWeb3, _FakeW3(b"\x01"))
    point_ts = datetime(2022, 8, 28, 11, 0, 0, tzinfo=timezone.utc)

    fake_market_row = crawler.MarketSnapshotRow(
        timestamp=point_ts,
        market=bytes.fromhex("39aa39c021dfbae8fac545936693ac917d5e7563"),
        symbol="cUSDC",
        total_supply=Decimal("0"),
        total_borrow=Decimal("0"),
        collateral_usd=Decimal("0"),
        utilization=Decimal("0"),
        borrow_rate=Decimal("0"),
        supply_rate=Decimal("0"),
        price_usd=Decimal("0"),
        supply_usd=Decimal("0"),
        borrow_usd=Decimal("0"),
    )
    fake_reserve_rows = [
        crawler.ReserveSnapshotRow(
            timestamp=point_ts,
            market=bytes.fromhex("39aa39c021dfbae8fac545936693ac917d5e7563"),
            reserve=bytes.fromhex("a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"),
            symbol="USDC",
            decimals=6,
            total_supply=Decimal("0"),
            total_borrow=Decimal("0"),
            utilization=Decimal("0"),
            borrow_rate=Decimal("0"),
            supply_rate=Decimal("0"),
            price_in_base=Decimal("0"),
            price_usd=Decimal("0"),
            supply_usd=Decimal("0"),
            borrow_usd=Decimal("0"),
        )
    ]

    with patch.object(
        crawler,
        "_collect_v2_market_at_block",
        new=AsyncMock(return_value=(fake_market_row, fake_reserve_rows)),
    ) as collect:
        market_rows, reserve_rows = await crawler._collect_v2_markets_at_block(
            cfg,
            w3,
            point_ts=point_ts,
            block_number=15427392,
            markets=["0x39AA39c021dfbaE8faC545936693aC917d5E7563"],
            metadata_cache={},
            deployment_cache={},
        )

    assert len(market_rows) == 1
    assert len(reserve_rows) == 1
    assert collect.await_count == 1


def test_governance_config_hash_is_stable() -> None:
    payload = {
        "base_token": "0x1",
        "asset_configs": [{"asset": "0x2", "supply_cap": "100"}],
        "target_reserves": "5",
    }
    assert crawler._governance_config_hash(payload) == crawler._governance_config_hash(
        {
            "target_reserves": "5",
            "asset_configs": [{"supply_cap": "100", "asset": "0x2"}],
            "base_token": "0x1",
        }
    )


def test_annualize_factor_from_per_second_rate() -> None:
    assert crawler._annualize_factor(10**18) == crawler.SECONDS_PER_YEAR


@pytest.mark.asyncio
async def test_price_from_feed_direct_returns_zero_when_historical_and_latest_fail() -> (
    None
):
    w3 = cast(
        AsyncWeb3,
        _FakeFeedW3(
            b"\x01",
            historical_exc=RuntimeError("historical revert"),
            latest_exc=RuntimeError("latest revert"),
        ),
    )

    price = await crawler._price_from_feed_direct(
        w3,
        "0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419",
        23161825,
    )

    assert price == Decimal("0")
