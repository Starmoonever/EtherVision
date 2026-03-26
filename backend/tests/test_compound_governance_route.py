from __future__ import annotations

from types import SimpleNamespace
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


def _v3_payload() -> dict[str, object]:
    return {
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


def test_compound_market_config_route_v3_uses_governance() -> None:
    payload = _v3_payload()
    with patch(
        "compound_crawler.api.routes.get_market_governance",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/compound/market/config",
                params={"version": "v3", "market": "weth", "detail": "false"},
            )

    assert resp.status_code == 200
    assert resp.json() == {
        "version": "v3",
        "market_config": payload,
        "protocol_config": None,
    }
    mocked_service.assert_awaited_once()


def test_compound_market_config_period_route_v3_uses_governance() -> None:
    payload = {"points": [_v3_payload()]}
    with patch(
        "compound_crawler.api.routes.get_market_governance_period",
        new=AsyncMock(return_value=SimpleNamespace(points=payload["points"])),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/compound/market/config/period",
                params={
                    "version": "v3",
                    "market": "weth",
                    "start": "2026-03-21T00:00:00Z",
                    "end": "2026-03-22T00:00:00Z",
                },
            )

    assert resp.status_code == 200
    assert resp.json() == {
        "points": [
            {
                "version": "v3",
                "market_config": _v3_payload(),
                "protocol_config": None,
            }
        ]
    }
    mocked_service.assert_awaited_once()
