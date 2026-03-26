from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
from fastapi import HTTPException

from compound_crawler.api import service
from compound_crawler.config import AppConfig
from compound_crawler.constants import (
    COMPOUND_V2_MARKET_NAMES,
    COMPOUND_V3_MARKET_NAMES,
)
from compound_crawler.db import (
    CompoundEventPositionSnapshotRow,
    UserPositionSnapshotRow,
)
from compound_crawler.user_position_snapshots import (
    CollectedMarketSnapshots,
    collect_market_user_snapshots,
)


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self, rows=None):
        self._rows = rows or []

    async def fetch(self, _sql, *_args):
        return self._rows


class _FakePool:
    def __init__(self, rows=None):
        self._conn = _FakeConn(rows)

    def acquire(self):
        return _AcquireCtx(self._conn)


class _FakeEth:
    async def get_block(self, _block_identifier):
        return {"timestamp": 1_742_521_600, "number": 123}


class _FakeWeb3:
    def __init__(self):
        self.eth = _FakeEth()


class _RecordLike:
    def __init__(self, payload: dict[str, object]):
        self._payload = payload

    def __getitem__(self, key: str) -> object:
        return self._payload[key]


class _FakeCall:
    def __init__(self, result: object = None, error: Exception | None = None):
        self._result = result
        self._error = error

    async def call(self, *, block_identifier: int):
        assert block_identifier > 0
        if self._error is not None:
            raise self._error
        return self._result


class _FakeV2Functions:
    def __init__(
        self, *, balance: int, borrow: int, exchange_rate: int, use_current: bool
    ):
        self._balance = balance
        self._borrow = borrow
        self._exchange_rate = exchange_rate
        self._use_current = use_current

    def balanceOf(self, _user: str) -> _FakeCall:
        return _FakeCall(self._balance)

    def borrowBalanceCurrent(self, _user: str) -> _FakeCall:
        if self._use_current:
            return _FakeCall(self._borrow)
        return _FakeCall(error=RuntimeError("current unavailable"))

    def exchangeRateCurrent(self) -> _FakeCall:
        if self._use_current:
            return _FakeCall(self._exchange_rate)
        return _FakeCall(error=RuntimeError("current unavailable"))

    def borrowBalanceStored(self, _user: str) -> _FakeCall:
        return _FakeCall(self._borrow)

    def exchangeRateStored(self) -> _FakeCall:
        return _FakeCall(self._exchange_rate)


class _FakeV2Contract:
    def __init__(
        self, *, balance: int, borrow: int, exchange_rate: int, use_current: bool
    ):
        self.functions = _FakeV2Functions(
            balance=balance,
            borrow=borrow,
            exchange_rate=exchange_rate,
            use_current=use_current,
        )


class _ReplayFakeFunctions:
    def __init__(self, mapping: dict[str, object]):
        self._mapping = mapping

    def __getattr__(self, name: str):
        def _callable(*_args, **_kwargs):
            value = self._mapping[name]
            return _FakeCall(value)

        return _callable


class _ReplayFakeContract:
    def __init__(self, mapping: dict[str, object]):
        self.functions = _ReplayFakeFunctions(mapping)


class _ReplayFakeEth:
    def __init__(
        self, contracts: dict[str, _ReplayFakeContract], codes: dict[str, bytes]
    ):
        self._contracts = contracts
        self._codes = codes

    def contract(self, *, address, abi):
        del abi
        return self._contracts[str(address).lower()]

    async def get_code(self, address, block_identifier=None):
        del block_identifier
        return self._codes.get(str(address).lower(), b"")


class _ReplayFakeWeb3:
    def __init__(
        self, contracts: dict[str, _ReplayFakeContract], codes: dict[str, bytes]
    ):
        self.eth = _ReplayFakeEth(contracts, codes)


def _snapshot_row_dict() -> dict[str, object]:
    return {
        "timestamp": datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc),
        "block_number": 123,
        "market": bytes.fromhex("a17581a9e3356d9a858b789d68b4d866e593ae94"),
        "symbol": "WETH",
        "user_address": bytes.fromhex("11" * 20),
        "has_open_position": True,
        "is_liquidatable": False,
        "base_token": bytes.fromhex("c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"),
        "base_symbol": "WETH",
        "base_price_usd": Decimal("2000"),
        "eth_price_usd": Decimal("2000"),
        "total_collateral_usd": Decimal("5000"),
        "total_debt_usd": Decimal("2000"),
        "discounted_collateral_usd": Decimal("4200"),
        "liquidation_buffer_usd": Decimal("2200"),
        "health_factor": Decimal("2.1"),
        "eth_sensitive_collateral_usd": Decimal("5000"),
        "eth_sensitive_debt_usd": Decimal("2000"),
        "net_eth_exposure_usd": Decimal("3000"),
        "non_eth_collateral_usd": Decimal("0"),
        "non_eth_debt_usd": Decimal("0"),
        "basis_risk_collateral_usd": Decimal("0"),
        "eth_down_liq_price_usd": Decimal("1200"),
        "eth_up_liq_price_usd": None,
        "eth_liq_mode": "down",
        "dominant_risk": "eth_down",
        "assets_jsonb": json.dumps(
            [
                {
                    "asset": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                    "symbol": "WETH",
                    "side": "base_borrow",
                    "amount": "1",
                    "price_in_base": "1",
                    "price_usd": "2000",
                    "value_usd": "2000",
                    "discounted_value_usd": "0",
                    "borrow_collateral_factor": None,
                    "liquidate_collateral_factor": None,
                    "liquidation_factor": None,
                    "beta_to_eth": "1",
                    "is_eth_correlated": True,
                    "is_basis_risk_asset": False,
                }
            ]
        ),
    }


def _snapshot_dataclass() -> UserPositionSnapshotRow:
    return UserPositionSnapshotRow(
        timestamp=datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc),
        block_number=456,
        market=bytes.fromhex("c3d688b66703497daa19211eedff47f25384cdc3"),
        symbol="USDC",
        user_address=bytes.fromhex("22" * 20),
        has_open_position=True,
        is_liquidatable=True,
        base_token=bytes.fromhex("a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"),
        base_symbol="USDC",
        base_price_usd=Decimal("1"),
        eth_price_usd=Decimal("2000"),
        total_collateral_usd=Decimal("1500"),
        total_debt_usd=Decimal("1000"),
        discounted_collateral_usd=Decimal("1100"),
        liquidation_buffer_usd=Decimal("100"),
        health_factor=Decimal("1.1"),
        eth_sensitive_collateral_usd=Decimal("500"),
        eth_sensitive_debt_usd=Decimal("0"),
        net_eth_exposure_usd=Decimal("500"),
        non_eth_collateral_usd=Decimal("1000"),
        non_eth_debt_usd=Decimal("1000"),
        basis_risk_collateral_usd=Decimal("0"),
        eth_down_liq_price_usd=Decimal("1500"),
        eth_up_liq_price_usd=None,
        eth_liq_mode="down",
        dominant_risk="eth_down",
        assets_jsonb=[
            {
                "asset": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                "symbol": "USDC",
                "side": "base_borrow",
                "amount": "1000",
                "price_in_base": "1",
                "price_usd": "1",
                "value_usd": "1000",
                "discounted_value_usd": "0",
                "borrow_collateral_factor": None,
                "liquidate_collateral_factor": None,
                "liquidation_factor": None,
                "beta_to_eth": "0",
                "is_eth_correlated": False,
                "is_basis_risk_asset": False,
            }
        ],
    )


@pytest.mark.asyncio
async def test_get_positions_reads_historical_snapshot_from_db() -> None:
    pool = _FakePool(rows=[_RecordLike(_snapshot_row_dict())])

    response = await service.get_positions(
        pool=pool,
        version="v3",
        market="weth",
        address="0x1111111111111111111111111111111111111111",
        date="2026-03-21",
    )

    assert response.address == "0x1111111111111111111111111111111111111111"
    assert len(response.positions) == 1
    assert response.positions[0].market == "0xa17581a9e3356d9a858b789d68b4d866e593ae94"
    assert response.positions[0].symbol == "WETH"
    assert response.positions[0].timestamp == "2026-03-21T00:00:00Z"
    assert response.positions[0].liquidation_buffer_usd == "2200"
    assert response.positions[0].assets[0].symbol == "WETH"


@pytest.mark.asyncio
async def test_get_positions_v2_reads_historical_snapshot_from_db_only() -> None:
    pool = _FakePool(rows=[_RecordLike(_snapshot_row_dict())])
    with patch.object(
        service,
        "collect_market_user_snapshots",
        new=AsyncMock(),
    ) as mocked_collect:
        response = await service.get_positions(
            pool=pool,
            version="v2",
            market="ceth",
            address="0x1111111111111111111111111111111111111111",
            date="2026-03-21",
        )

    assert response.version == "v2"
    assert len(response.positions) == 1
    mocked_collect.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_positions_collects_and_persists_when_history_missing() -> None:
    collected = CollectedMarketSnapshots(
        timestamp=datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc),
        block_number=456,
        market="0xc3d688b66703497daa19211eedff47f25384cdc3",
        symbol="USDC",
        snapshots=[_snapshot_dataclass()],
    )

    with (
        patch.object(service, "load_config", return_value=SimpleNamespace()),
        patch.object(
            service,
            "collect_market_user_snapshots",
            new=AsyncMock(return_value=collected),
        ) as mocked_collect,
    ):
        response = await service.get_positions(
            pool=_FakePool(rows=[]),
            version="v3",
            market="usdc",
            address="0x2222222222222222222222222222222222222222",
            date="2026-03-21T00:00:00Z",
        )

    assert response.address == "0x2222222222222222222222222222222222222222"
    assert response.positions[0].market == "0xc3d688b66703497daa19211eedff47f25384cdc3"
    assert response.positions[0].symbol == "USDC"
    mocked_collect.assert_awaited_once()
    await_args = mocked_collect.await_args
    assert await_args is not None
    assert await_args.kwargs["persist"] is True
    assert await_args.kwargs["market"] == "0xc3d688b66703497daa19211eedff47f25384cdc3"


@pytest.mark.asyncio
async def test_get_positions_passes_single_user_address_to_collector() -> None:
    collected = CollectedMarketSnapshots(
        timestamp=datetime(2026, 3, 21, 9, 30, 0, tzinfo=timezone.utc),
        block_number=789,
        market="0x3afdc9bca9213a35503b077a6072f3d0d5ab0840",
        symbol="USDT",
        snapshots=[],
    )

    with (
        patch.object(service, "load_config", return_value=SimpleNamespace()),
        patch.object(
            service,
            "collect_market_user_snapshots",
            new=AsyncMock(return_value=collected),
        ) as mocked_collect,
    ):
        await service.get_positions(
            pool=_FakePool(),
            version="v3",
            market="usdt",
            address="0x1111111111111111111111111111111111111111",
            date=None,
        )

    await_args = mocked_collect.await_args
    assert await_args is not None
    assert await_args.kwargs["user_addresses"] == [bytes.fromhex("11" * 20)]


@pytest.mark.asyncio
async def test_get_positions_without_date_fetches_realtime() -> None:
    collected = CollectedMarketSnapshots(
        timestamp=datetime(2026, 3, 21, 9, 30, 0, tzinfo=timezone.utc),
        block_number=789,
        market="0x3afdc9bca9213a35503b077a6072f3d0d5ab0840",
        symbol="USDT",
        snapshots=[],
    )

    with (
        patch.object(service, "load_config", return_value=SimpleNamespace()),
        patch.object(
            service,
            "collect_market_user_snapshots",
            new=AsyncMock(return_value=collected),
        ) as mocked_collect,
    ):
        response = await service.get_positions(
            pool=_FakePool(),
            version="v3",
            market="usdt",
            address="0x1111111111111111111111111111111111111111",
            date=None,
        )

    assert response.address == "0x1111111111111111111111111111111111111111"
    assert response.positions == []
    await_args = mocked_collect.await_args
    assert await_args is not None
    assert await_args.kwargs["persist"] is False


@pytest.mark.asyncio
async def test_get_positions_v2_without_date_reads_latest_snapshot_only() -> None:
    pool = _FakePool(rows=[_RecordLike(_snapshot_row_dict())])
    with patch.object(
        service,
        "collect_market_user_snapshots",
        new=AsyncMock(),
    ) as mocked_collect:
        response = await service.get_positions(
            pool=pool,
            version="v2",
            market="all",
            address="0x1111111111111111111111111111111111111111",
            date=None,
        )

    assert response.version == "v2"
    assert len(response.positions) == 1
    mocked_collect.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_positions_market_all_collects_all_markets() -> None:
    usdc = CollectedMarketSnapshots(
        timestamp=datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc),
        block_number=100,
        market="0xc3d688b66703497daa19211eedff47f25384cdc3",
        symbol="USDC",
        snapshots=[_snapshot_dataclass()],
    )
    weth_payload = _snapshot_dataclass()
    weth_payload.market = bytes.fromhex("a17581a9e3356d9a858b789d68b4d866e593ae94")
    weth_payload.symbol = "WETH"
    weth = CollectedMarketSnapshots(
        timestamp=datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc),
        block_number=101,
        market="0xa17581a9e3356d9a858b789d68b4d866e593ae94",
        symbol="WETH",
        snapshots=[weth_payload],
    )
    usdt = CollectedMarketSnapshots(
        timestamp=datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc),
        block_number=102,
        market="0x3afdc9bca9213a35503b077a6072f3d0d5ab0840",
        symbol="USDT",
        snapshots=[],
    )

    def _collect_for_market(*_args, **kwargs):
        market = kwargs["market"]
        if market == "0xc3d688b66703497daa19211eedff47f25384cdc3":
            return usdc
        if market == "0x3afdc9bca9213a35503b077a6072f3d0d5ab0840":
            return usdt
        if market == "0xa17581a9e3356d9a858b789d68b4d866e593ae94":
            return weth
        return CollectedMarketSnapshots(
            timestamp=datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc),
            block_number=0,
            market=market,
            symbol="UNKNOWN",
            snapshots=[],
        )

    with (
        patch.object(service, "load_config", return_value=SimpleNamespace()),
        patch.object(
            service,
            "collect_market_user_snapshots",
            new=AsyncMock(side_effect=_collect_for_market),
        ) as mocked_collect,
    ):
        response = await service.get_positions(
            pool=_FakePool(),
            version="v3",
            market="all",
            address="0x1111111111111111111111111111111111111111",
            date=None,
        )

    assert response.address == "0x1111111111111111111111111111111111111111"
    assert [item.market for item in response.positions] == [
        "0xa17581a9e3356d9a858b789d68b4d866e593ae94",
        "0xc3d688b66703497daa19211eedff47f25384cdc3",
    ]
    assert mocked_collect.await_count == len(service.COMPOUND_V3_MARKET_NAMES)


@pytest.mark.asyncio
async def test_get_positions_realtime_empty_result() -> None:
    collected = CollectedMarketSnapshots(
        timestamp=datetime(2026, 3, 21, 9, 30, 0, tzinfo=timezone.utc),
        block_number=789,
        market="0x3afdc9bca9213a35503b077a6072f3d0d5ab0840",
        symbol="USDT",
        snapshots=[],
    )

    with (
        patch.object(service, "load_config", return_value=SimpleNamespace()),
        patch.object(
            service,
            "collect_market_user_snapshots",
            new=AsyncMock(return_value=collected),
        ) as mocked_collect,
    ):
        response = await service.get_positions(
            pool=_FakePool(),
            version="v3",
            market="usdt",
            address="0x1111111111111111111111111111111111111111",
            date=None,
        )

    assert response.address == "0x1111111111111111111111111111111111111111"
    assert response.positions == []
    await_args = mocked_collect.await_args
    assert await_args is not None
    assert await_args.kwargs["persist"] is False


@pytest.mark.asyncio
async def test_get_positions_rejects_invalid_address() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await service.get_positions(
            pool=_FakePool(),
            version="v3",
            market="weth",
            address="not-an-address",
            date="2026-03-21T00:00:00Z",
        )

    assert exc_info.value.status_code == 400
    assert "address" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_positions_ignores_time_part_in_date() -> None:
    pool = _FakePool(rows=[_RecordLike(_snapshot_row_dict())])

    response = await service.get_positions(
        pool=pool,
        version="v3",
        market="weth",
        address="0x1111111111111111111111111111111111111111",
        date="2026-03-21T12:34:56Z",
    )

    assert response.positions[0].timestamp == "2026-03-21T00:00:00Z"


@pytest.mark.asyncio
async def test_collect_market_user_snapshots_with_explicit_user_does_not_require_csv() -> (
    None
):
    collected = CollectedMarketSnapshots(
        timestamp=datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc),
        block_number=123,
        market="0xa17581a9e3356d9a858b789d68b4d866e593ae94",
        symbol="WETH",
        snapshots=[],
    )

    with (
        patch(
            "compound_crawler.user_position_snapshots._build_web3",
            new=AsyncMock(return_value=_FakeWeb3()),
        ),
        patch(
            "compound_crawler.user_position_snapshots._collect_market_snapshot_rows",
            new=AsyncMock(
                return_value=(
                    SimpleNamespace(
                        market_address=collected.market, market_symbol="WETH"
                    ),
                    [],
                    [],
                    0,
                )
            ),
        ),
    ):
        result = await collect_market_user_snapshots(
            cfg=cast(
                AppConfig,
                SimpleNamespace(
                    market_state=SimpleNamespace(use_timescaledb=False),
                    crawler=SimpleNamespace(batch_size=100),
                ),
            ),
            pool=cast(asyncpg.Pool, _FakePool()),
            market="weth",
            point_ts=None,
            persist=False,
            derived_users_dir=None,
            user_addresses=[bytes.fromhex("11" * 20)],
        )

    assert result.market == "0xa17581a9e3356d9a858b789d68b4d866e593ae94"


def test_market_to_address_accepts_mixed_case_known_addresses() -> None:
    for address in COMPOUND_V3_MARKET_NAMES:
        mixed = "0x" + address[2:].upper()
        assert service._market_to_address(mixed) == address.lower()
    for address in COMPOUND_V2_MARKET_NAMES:
        mixed = "0x" + address[2:].upper()
        assert service._market_to_address("v2", mixed) == address.lower()


def test_format_compound_brief_keeps_v2_brief_plain() -> None:
    assert (
        service._format_compound_brief("v2", "借入", "cDAI", amount=Decimal("100"))
        == "借入 100.000000 cDAI"
    )


def test_format_compound_brief_appends_v3_market_suffix() -> None:
    assert (
        service._format_compound_brief("v3", "提取", "USDC", amount=Decimal("15.5"))
        == "提取 15.500000 USDC @USDC"
    )


@pytest.mark.asyncio
async def test_get_position_replay_filters_non_impact_transactions() -> None:
    user_address = "0x1111111111111111111111111111111111111111"
    ts = datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc)
    market_keep = bytes.fromhex("a17581a9e3356d9a858b789d68b4d866e593ae94")
    market_drop = bytes.fromhex("3afdc9bca9213a35503b077a6072f3d0d5ab0840")
    tx_rows = [
        {
            "market": market_keep,
            "tx_hash": "0x" + "aa" * 32,
            "method_id": "f3fef3a3",  # self-impact method
            "block_number": 100,
            "block_timestamp": ts,
        },
        {
            "market": market_drop,
            "tx_hash": "0x" + "bb" * 32,
            "method_id": "c3b35a7e",  # supplyTo, non-self-impact
            "block_number": 101,
            "block_timestamp": ts,
        },
    ]
    cached_rows = [
        _RecordLike(
            {
                "tx_hash": "0x" + "aa" * 32,
                "block_number": 100,
                "block_timestamp": ts,
                "symbol": "WETH",
                "eth_price_usd": Decimal("2000"),
                "total_collateral_usd": Decimal("1000"),
                "total_debt_usd": Decimal("100"),
                "discounted_collateral_usd": Decimal("700"),
                "liquidation_buffer_usd": Decimal("600"),
                "health_factor": Decimal("7"),
                "is_liquidatable": False,
                "eth_down_liq_price_usd": Decimal("1000"),
                "eth_up_liq_price_usd": None,
                "eth_liq_mode": "down",
                "dominant_risk": "eth_down",
                "brief": "存入 1.000000 WETH",
                "assets_jsonb": "[]",
            }
        )
    ]
    with (
        patch.object(
            service,
            "fetch_compound_user_tx_history",
            new=AsyncMock(return_value=tx_rows),
        ),
        patch.object(
            service,
            "_load_compound_replay_briefs",
            new=AsyncMock(return_value={}),
        ),
        patch.object(
            service,
            "get_compound_event_snapshots",
            new=AsyncMock(return_value=cached_rows),
        ),
        patch.object(
            service,
            "_collect_and_cache_replay_misses",
            new=AsyncMock(),
        ) as mocked_collect_miss,
    ):
        response = await service.get_position_replay(
            pool=_FakePool(),
            version="v3",
            address=user_address,
            from_ts=int(ts.timestamp()),
            to_ts=int(ts.timestamp()),
            use_cache=True,
            detail=False,
        )

    assert response.address == user_address
    assert response.total_tx_count == 1
    assert len(response.points) == 1
    assert response.points[0].tx_hash == "0x" + "aa" * 32
    mocked_collect_miss.assert_not_awaited()


@pytest.mark.asyncio
async def test_collect_and_cache_replay_misses_supports_v2_realtime_backfill() -> None:
    user_address = bytes.fromhex("11" * 20)
    market = bytes.fromhex("4ddc2d193948926d02f9b1fe9e1daa0718270ed5")
    ts = datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc)
    misses = [
        {
            "market": market,
            "tx_hash": "0x" + "aa" * 32,
            "method_id": "2608f818",
            "block_number": 123,
            "block_timestamp": ts,
        }
    ]
    v2_snapshot = CompoundEventPositionSnapshotRow(
        user_address=user_address,
        protocol="v2",
        market=market,
        symbol="cETH",
        block_number=123,
        tx_hash="",
        block_timestamp=ts,
        has_open_position=True,
        is_liquidatable=False,
        base_token=bytes.fromhex(
            "c02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"[2:].lower()
        ),
        base_symbol="ETH",
        base_price_usd=Decimal("2000"),
        eth_price_usd=Decimal("2000"),
        total_collateral_usd=Decimal("1000"),
        total_debt_usd=Decimal("100"),
        discounted_collateral_usd=Decimal("600"),
        liquidation_buffer_usd=Decimal("500"),
        health_factor=Decimal("6"),
        eth_sensitive_collateral_usd=Decimal("1000"),
        eth_sensitive_debt_usd=Decimal("100"),
        net_eth_exposure_usd=Decimal("900"),
        non_eth_collateral_usd=Decimal("0"),
        non_eth_debt_usd=Decimal("0"),
        basis_risk_collateral_usd=Decimal("0"),
        eth_down_liq_price_usd=Decimal("1000"),
        eth_up_liq_price_usd=None,
        eth_liq_mode="down",
        dominant_risk="eth_down",
        assets_jsonb=[],
        brief="",
    )

    with (
        patch.object(
            service,
            "_load_compound_replay_briefs",
            new=AsyncMock(return_value={}),
        ),
        patch.object(
            service,
            "_collect_v2_replay_snapshot_row",
            new=AsyncMock(return_value=v2_snapshot),
        ) as mocked_collect_v2,
        patch.object(
            service,
            "upsert_compound_event_snapshots",
            new=AsyncMock(return_value=1),
        ) as mocked_upsert,
    ):
        await service._collect_and_cache_replay_misses(
            pool=_FakePool(),
            version="v2",
            user_address=user_address,
            misses=misses,
            w3=object(),
        )

    mocked_collect_v2.assert_awaited_once()
    mocked_upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_v2_accrued_balances_prefers_current_calls() -> None:
    contract = _FakeV2Contract(
        balance=100,
        borrow=25,
        exchange_rate=2_000_000_000_000_000_000_000_000_000,
        use_current=True,
    )

    (
        balance_raw,
        borrow_raw,
        exchange_rate_raw,
    ) = await service._load_v2_accrued_balances(
        contract,
        user_checksum="0x" + "11" * 20,
        block_number=123,
    )

    assert balance_raw == 100
    assert borrow_raw == 25
    assert exchange_rate_raw == 2_000_000_000_000_000_000_000_000_000


@pytest.mark.asyncio
async def test_load_v2_accrued_balances_falls_back_to_stored_calls() -> None:
    contract = _FakeV2Contract(
        balance=200,
        borrow=50,
        exchange_rate=3_000_000_000_000_000_000_000_000_000,
        use_current=False,
    )

    (
        balance_raw,
        borrow_raw,
        exchange_rate_raw,
    ) = await service._load_v2_accrued_balances(
        contract,
        user_checksum="0x" + "22" * 20,
        block_number=456,
    )

    assert balance_raw == 200
    assert borrow_raw == 50
    assert exchange_rate_raw == 3_000_000_000_000_000_000_000_000_000


@pytest.mark.asyncio
async def test_collect_v2_replay_snapshot_row_skips_undeployed_event_market() -> None:
    comptroller = "0x1111111111111111111111111111111111111111"
    deployed_market = "0x5d3a536e4d6dbd6114cc1ead35777bab948e3643"
    undeployed_event_market = "0x39aa39c021dfbae8fac545936693ac917d5e7563"
    underlying = "0x2222222222222222222222222222222222222222"
    user_address = bytes.fromhex("33" * 20)
    user_checksum = "0x" + user_address.hex()

    contracts = {
        deployed_market: _ReplayFakeContract({"comptroller": comptroller}),
        comptroller: _ReplayFakeContract(
            {
                "getAssetsIn": [deployed_market],
                "markets": (True, 0, False),
            }
        ),
    }
    codes = {
        deployed_market: b"\x01",
        comptroller: b"\x01",
    }
    w3 = _ReplayFakeWeb3(contracts, codes)

    with (
        patch.object(
            service,
            "_is_contract_deployed_at_block",
            new=AsyncMock(
                side_effect=lambda _w3, address, *_args: (
                    address.lower() == deployed_market
                )
            ),
        ),
        patch.object(
            service,
            "_token_metadata",
            new=AsyncMock(return_value=("DAI", 18)),
        ),
        patch.object(
            service,
            "_v2_underlying_price_usd",
            new=AsyncMock(return_value=Decimal("1")),
        ),
        patch.object(
            service,
            "_load_v2_accrued_balances",
            new=AsyncMock(
                return_value=(
                    10**8,
                    0,
                    2 * 10**28,
                )
            ),
        ),
        patch.object(
            service,
            "_price_from_feed_direct",
            new=AsyncMock(return_value=Decimal("2000")),
        ),
    ):
        contracts[deployed_market] = _ReplayFakeContract(
            {
                "comptroller": comptroller,
                "underlying": underlying,
            }
        )
        row = await service._collect_v2_replay_snapshot_row(
            w3,
            user_address=user_address,
            event_market=bytes.fromhex(undeployed_event_market[2:]),
            block_number=123,
            point_ts=datetime(2026, 3, 26, tzinfo=timezone.utc),
            metadata_cache={},
        )

    assert user_checksum.startswith("0x")
    assert row.market == bytes.fromhex(undeployed_event_market[2:])
    assert row.symbol == COMPOUND_V2_MARKET_NAMES[undeployed_event_market]
    assert row.total_collateral_usd > 0
