from __future__ import annotations

from unittest.mock import AsyncMock, patch

from compound_crawler.api.routes import router as compound_router
from compound_crawler.database import get_pool
from fastapi import FastAPI
from starlette.testclient import TestClient


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(compound_router)

    async def _override_pool():
        return object()

    app.dependency_overrides[get_pool] = _override_pool
    return TestClient(app)


def test_compound_governance_route_ok() -> None:
    payload = {
        "version": "v3",
        "market": "0xa17581a9e3356d9a858b789d68b4d866e593ae94",
        "symbol": "WETH",
        "effective_timestamp": "2026-03-21T00:00:00Z",
        "block_number": 123,
        "config_hash": "abc123",
        "source": "comet",
        "governor": "0x1111111111111111111111111111111111111111",
        "pause_guardian": "0x2222222222222222222222222222222222222222",
        "base_token": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        "base_symbol": "WETH",
        "base_token_price_feed": "0x3333333333333333333333333333333333333333",
        "extension_delegate": "0x4444444444444444444444444444444444444444",
        "base_scale": "1000000000000000000",
        "base_decimals": 18,
        "supply_kink": "0.8",
        "borrow_kink": "0.9",
        "supply_per_second_interest_rate_slope_low": "0.000000003",
        "supply_per_second_interest_rate_slope_high": "0.000000006",
        "supply_per_second_interest_rate_base": "0.000000001",
        "supply_per_year_interest_rate_slope_low": "0.10",
        "supply_per_year_interest_rate_slope_high": "0.20",
        "supply_per_year_interest_rate_base": "0.01",
        "borrow_per_second_interest_rate_slope_low": "0.000000004",
        "borrow_per_second_interest_rate_slope_high": "0.000000007",
        "borrow_per_second_interest_rate_base": "0.000000002",
        "borrow_per_year_interest_rate_slope_low": "0.15",
        "borrow_per_year_interest_rate_slope_high": "0.30",
        "borrow_per_year_interest_rate_base": "0.02",
        "store_front_price_factor": "0.95",
        "tracking_index_scale": "1",
        "base_tracking_supply_speed": "0.5",
        "base_tracking_borrow_speed": "0.6",
        "base_min_for_rewards": "100",
        "base_borrow_min": "1",
        "target_reserves": "1000",
        "assets": None,
    }

    with patch(
        "compound_crawler.api.routes.get_market_governance",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/compound/market/governance",
                params={
                    "version": "v3",
                    "market": "weth",
                    "date": "2026-03-21T00:00:00Z",
                    "detail": "false",
                },
            )

    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_awaited_once()
    await_args = mocked_service.await_args
    assert await_args is not None
    assert await_args.kwargs["market"] == "weth"


def test_compound_governance_route_requires_market() -> None:
    with _build_client() as client:
        resp = client.get("/api/compound/market/governance", params={"version": "v3"})

    assert resp.status_code == 422


def test_compound_governance_period_route_ok() -> None:
    payload = {
        "points": [
            {
                "version": "v3",
                "market": "0xa17581a9e3356d9a858b789d68b4d866e593ae94",
                "symbol": "WETH",
                "effective_timestamp": "2026-03-21T00:00:00Z",
                "block_number": 123,
                "config_hash": "abc123",
                "source": "comet",
                "governor": None,
                "pause_guardian": None,
                "base_token": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                "base_symbol": "WETH",
                "base_token_price_feed": None,
                "extension_delegate": None,
                "base_scale": "1000000000000000000",
                "base_decimals": 18,
                "supply_kink": "0.8",
                "borrow_kink": "0.9",
                "supply_per_second_interest_rate_slope_low": "0.1",
                "supply_per_second_interest_rate_slope_high": "0.2",
                "supply_per_second_interest_rate_base": "0.01",
                "supply_per_year_interest_rate_slope_low": "1",
                "supply_per_year_interest_rate_slope_high": "2",
                "supply_per_year_interest_rate_base": "0.1",
                "borrow_per_second_interest_rate_slope_low": "0.3",
                "borrow_per_second_interest_rate_slope_high": "0.4",
                "borrow_per_second_interest_rate_base": "0.02",
                "borrow_per_year_interest_rate_slope_low": "3",
                "borrow_per_year_interest_rate_slope_high": "4",
                "borrow_per_year_interest_rate_base": "0.2",
                "store_front_price_factor": "0.95",
                "tracking_index_scale": "1",
                "base_tracking_supply_speed": "0.5",
                "base_tracking_borrow_speed": "0.6",
                "base_min_for_rewards": "100",
                "base_borrow_min": "1",
                "target_reserves": "1000",
                "assets": None,
            }
        ]
    }

    with patch(
        "compound_crawler.api.routes.get_market_governance_period",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/compound/market/governance/period",
                params={
                    "version": "v3",
                    "market": "weth",
                    "start": "2026-03-21T00:00:00Z",
                    "end": "2026-03-22T00:00:00Z",
                    "latest_only_per_day": "true",
                    "detail": "false",
                },
            )

    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_awaited_once()
    await_args = mocked_service.await_args
    assert await_args is not None
    assert await_args.kwargs["latest_only_per_day"] is True
    assert await_args.kwargs["detail"] is False
