from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from compound_crawler.api import service


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self, row=None, asset_rows=None):
        self._row = row
        self._asset_rows = asset_rows or []

    async def fetchrow(self, _sql, *_args):
        return self._row

    async def fetch(self, _sql, *_args):
        return self._asset_rows


class _FakePool:
    def __init__(self, row=None, asset_rows=None):
        self._conn = _FakeConn(row=row, asset_rows=asset_rows)

    def acquire(self):
        return _AcquireCtx(self._conn)


def _governance_row() -> dict[str, object]:
    return {
        "market": bytes.fromhex("a17581a9e3356d9a858b789d68b4d866e593ae94"),
        "symbol": "WETH",
        "effective_timestamp": datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc),
        "block_number": 123,
        "config_hash": "abc123",
        "governor": bytes.fromhex("11" * 20),
        "pause_guardian": bytes.fromhex("22" * 20),
        "base_token": bytes.fromhex("c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"),
        "base_token_symbol": "WETH",
        "base_token_price_feed": bytes.fromhex("33" * 20),
        "extension_delegate": bytes.fromhex("44" * 20),
        "base_scale": 10**18,
        "base_decimals": 18,
        "supply_kink": Decimal("0.8"),
        "borrow_kink": Decimal("0.9"),
        "supply_per_year_interest_rate_slope_low": Decimal("0.10"),
        "supply_per_year_interest_rate_slope_high": Decimal("0.20"),
        "supply_per_year_interest_rate_base": Decimal("0.01"),
        "borrow_per_year_interest_rate_slope_low": Decimal("0.15"),
        "borrow_per_year_interest_rate_slope_high": Decimal("0.30"),
        "borrow_per_year_interest_rate_base": Decimal("0.02"),
        "store_front_price_factor": Decimal("0.95"),
        "tracking_index_scale": Decimal("1"),
        "base_tracking_supply_speed": Decimal("0.5"),
        "base_tracking_borrow_speed": Decimal("0.6"),
        "base_min_for_rewards": Decimal("100"),
        "base_borrow_min": Decimal("1"),
        "target_reserves": Decimal("1000"),
        "raw_config_jsonb": {
            "source": "comet",
            "supply_per_second_interest_rate_slope_low": "0.000000003",
            "supply_per_second_interest_rate_slope_high": "0.000000006",
            "supply_per_second_interest_rate_base": "0.000000001",
            "borrow_per_second_interest_rate_slope_low": "0.000000004",
            "borrow_per_second_interest_rate_slope_high": "0.000000007",
            "borrow_per_second_interest_rate_base": "0.000000002",
        },
    }


def _asset_row() -> dict[str, object]:
    return {
        "config_hash": "abc123",
        "asset": bytes.fromhex("c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"),
        "symbol": "WETH",
        "price_feed": bytes.fromhex("55" * 20),
        "decimals": 18,
        "borrow_collateral_factor": Decimal("0.85"),
        "liquidate_collateral_factor": Decimal("0.90"),
        "liquidation_factor": Decimal("0.95"),
        "supply_cap": Decimal("50000"),
    }


@pytest.mark.asyncio
async def test_get_market_governance_reads_latest_snapshot() -> None:
    response = await service.get_market_governance(
        pool=_FakePool(row=_governance_row(), asset_rows=[_asset_row()]),
        version="v3",
        market="weth",
        date=None,
    )

    assert response.market == "0xa17581a9e3356d9a858b789d68b4d866e593ae94"
    assert response.symbol == "WETH"
    assert response.source == "comet"
    assert response.base_symbol == "WETH"
    assert response.supply_per_second_interest_rate_slope_low == "0.000000003"
    assert response.supply_per_year_interest_rate_slope_low == "0.10"
    assert response.assets is None


@pytest.mark.asyncio
async def test_get_market_governance_detail_expands_assets() -> None:
    response = await service.get_market_governance(
        pool=_FakePool(row=_governance_row(), asset_rows=[_asset_row()]),
        version="v3",
        market="weth",
        date=None,
        detail=True,
    )

    assert response.assets is not None
    assert len(response.assets) == 1
    assert response.assets[0].asset == "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"


@pytest.mark.asyncio
async def test_get_market_governance_rejects_v2() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await service.get_market_governance(
            pool=_FakePool(),
            version="v2",
            market="weth",
            date=None,
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_market_governance_raises_404_when_missing() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await service.get_market_governance(
            pool=_FakePool(row=None),
            version="v3",
            market="weth",
            date="2026-03-21T00:00:00Z",
        )

    assert exc_info.value.status_code == 404


class _PeriodConn:
    def __init__(self, rows, asset_rows):
        self._rows = rows
        self._asset_rows = asset_rows

    async def fetch(self, sql, *_args):
        if "FROM loan.compound_v3_market_config_versions" in sql:
            return self._rows
        return self._asset_rows


class _PeriodPool:
    def __init__(self, rows, asset_rows):
        self._conn = _PeriodConn(rows, asset_rows)

    def acquire(self):
        return _AcquireCtx(self._conn)


@pytest.mark.asyncio
async def test_get_market_governance_period_returns_changed_points() -> None:
    row1 = _governance_row()
    row2 = {**_governance_row(), "config_hash": "def456", "block_number": 456}
    row2["effective_timestamp"] = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
    asset_row_1 = _asset_row()
    asset_row_2 = {**_asset_row(), "config_hash": "def456"}

    response = await service.get_market_governance_period(
        pool=_PeriodPool(rows=[row1, row2], asset_rows=[asset_row_1, asset_row_2]),
        version="v3",
        market="weth",
        start="2026-03-21T00:00:00Z",
        end="2026-03-22T00:00:00Z",
    )

    assert len(response.points) == 2
    assert response.points[0].config_hash == "abc123"
    assert response.points[1].config_hash == "def456"
    assert response.points[0].assets is None


@pytest.mark.asyncio
async def test_get_market_governance_period_latest_only_per_day_keeps_last() -> None:
    row1 = _governance_row()
    row2 = {**_governance_row(), "config_hash": "mid111", "block_number": 234}
    row2["effective_timestamp"] = datetime(2026, 3, 21, 12, 0, 0, tzinfo=timezone.utc)
    row3 = {**_governance_row(), "config_hash": "def456", "block_number": 456}
    row3["effective_timestamp"] = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
    asset_row_1 = _asset_row()
    asset_row_2 = {**_asset_row(), "config_hash": "mid111"}
    asset_row_3 = {**_asset_row(), "config_hash": "def456"}

    response = await service.get_market_governance_period(
        pool=_PeriodPool(
            rows=[row1, row2, row3],
            asset_rows=[asset_row_1, asset_row_2, asset_row_3],
        ),
        version="v3",
        market="weth",
        start="2026-03-21T00:00:00Z",
        end="2026-03-22T00:00:00Z",
        latest_only_per_day=True,
        detail=True,
    )

    assert [point.config_hash for point in response.points] == ["mid111", "def456"]
    assert response.points[0].assets is not None
