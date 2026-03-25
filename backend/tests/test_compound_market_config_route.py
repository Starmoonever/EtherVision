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


def test_compound_market_config_route_ok() -> None:
    payload = {
        "version": "v2",
        "market": "0x5d3a536e4d6dbd6114cc1ead35777bab948e3643",
        "symbol": "cDAI",
        "effective_timestamp": "2026-03-24T00:00:00Z",
        "block_number": 24723660,
        "config_hash": "abc123",
        "comptroller": "0x3d9819210a31b4961b30ef54be2aed79b9c9cd3b",
        "interest_rate_model": "0x0000000000000000000000000000000000000001",
        "underlying": "0x6b175474e89094c44da98b954eedeac495271d0f",
        "underlying_symbol": "DAI",
        "ctoken_decimals": 8,
        "underlying_decimals": 18,
        "collateral_factor": "0.75",
        "reserve_factor": "0.1",
        "liquidation_threshold": None,
        "borrow_cap": "1000000",
        "supply_cap": "2000000",
        "is_listed": True,
        "is_comped": True,
        "is_deprecated": False,
        "protocol_config_hash": "p123",
        "mint_paused": False,
        "borrow_paused": True,
    }
    with patch(
        "compound_crawler.api.routes.get_v2_market_config",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/compound/market/config",
                params={"version": "v2", "market": "cDAI"},
            )
    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_awaited_once()


def test_compound_market_config_route_ok_with_version_path() -> None:
    payload = {
        "version": "v2",
        "market": "0x5d3a536e4d6dbd6114cc1ead35777bab948e3643",
        "symbol": "cDAI",
        "effective_timestamp": "2026-03-24T00:00:00Z",
        "block_number": 24723660,
        "config_hash": "abc123",
        "comptroller": None,
        "interest_rate_model": None,
        "underlying": None,
        "underlying_symbol": None,
        "ctoken_decimals": 8,
        "underlying_decimals": 18,
        "collateral_factor": None,
        "reserve_factor": None,
        "liquidation_threshold": None,
        "borrow_cap": None,
        "supply_cap": None,
        "is_listed": True,
        "is_comped": False,
        "is_deprecated": False,
        "protocol_config_hash": None,
        "mint_paused": None,
        "borrow_paused": None,
    }
    with patch(
        "compound_crawler.api.routes.get_v2_market_config",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/compound/v2/market/config",
                params={"market": "cDAI"},
            )
    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_awaited_once()


def test_compound_market_config_period_route_ok() -> None:
    payload = {
        "points": [
            {
                "version": "v2",
                "market": "0x5d3a536e4d6dbd6114cc1ead35777bab948e3643",
                "symbol": "cDAI",
                "effective_timestamp": "2026-03-24T00:00:00Z",
                "block_number": 24723660,
                "config_hash": "abc123",
                "comptroller": "0x3d9819210a31b4961b30ef54be2aed79b9c9cd3b",
                "interest_rate_model": "0x0000000000000000000000000000000000000001",
                "underlying": "0x6b175474e89094c44da98b954eedeac495271d0f",
                "underlying_symbol": "DAI",
                "ctoken_decimals": 8,
                "underlying_decimals": 18,
                "collateral_factor": "0.75",
                "reserve_factor": "0.1",
                "liquidation_threshold": None,
                "borrow_cap": "1000000",
                "supply_cap": "2000000",
                "is_listed": True,
                "is_comped": True,
                "is_deprecated": False,
                "protocol_config_hash": "p123",
                "mint_paused": False,
                "borrow_paused": True,
            }
        ]
    }
    with patch(
        "compound_crawler.api.routes.get_v2_market_config_period",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/compound/market/config/period",
                params={
                    "version": "v2",
                    "market": "cDAI",
                    "start": "2026-03-24T00:00:00Z",
                    "end": "2026-03-25T00:00:00Z",
                },
            )
    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_awaited_once()
