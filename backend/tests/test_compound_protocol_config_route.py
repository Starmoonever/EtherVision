from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from compound_crawler.api.routes import router as compound_router
from compound_crawler.api.schemas import V2MarketConfigResponse
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


def _market_payload() -> V2MarketConfigResponse:
    return V2MarketConfigResponse(
        version="v2",
        market="0x5d3a536e4d6dbd6114cc1ead35777bab948e3643",
        symbol="cDAI",
        effective_timestamp="2026-03-24T00:00:00Z",
        block_number=24723660,
        config_hash="abc123",
        comptroller=None,
        interest_rate_model=None,
        underlying=None,
        underlying_symbol=None,
        ctoken_decimals=8,
        underlying_decimals=18,
        collateral_factor=None,
        reserve_factor=None,
        liquidation_threshold=None,
        borrow_cap=None,
        supply_cap=None,
        is_listed=True,
        is_comped=False,
        is_deprecated=False,
        protocol_config_hash=None,
        mint_paused=None,
        borrow_paused=None,
    )


def _protocol_payload() -> dict[str, object]:
    return {
        "version": "v2",
        "effective_timestamp": "2026-03-24T00:00:00Z",
        "block_number": 24723660,
        "config_hash": "p123",
        "comptroller": "0x3d9819210a31b4961b30ef54be2aed79b9c9cd3b",
        "price_oracle": "0x922018674c12a7f0d394ebeef9b58f186cde13c1",
        "close_factor": "0.5",
        "liquidation_incentive": "1.08",
        "pause_guardian": "0x1111111111111111111111111111111111111111",
        "transfer_paused": False,
        "seize_paused": False,
        "mint_paused": False,
        "borrow_paused": True,
    }


def test_compound_market_config_route_v2_detail_returns_protocol_config() -> None:
    with (
        patch(
            "compound_crawler.api.routes.get_v2_market_config",
            new=AsyncMock(return_value=_market_payload().model_dump()),
        ) as mocked_market,
        patch(
            "compound_crawler.api.routes.get_v2_protocol_config",
            new=AsyncMock(return_value=_protocol_payload()),
        ) as mocked_protocol,
    ):
        with _build_client() as client:
            resp = client.get(
                "/api/compound/market/config",
                params={
                    "version": "v2",
                    "market": "cDAI",
                    "date": "2026-03-24T00:00:00Z",
                    "detail": "true",
                },
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "v2"
    assert body["market_config"]["config_hash"] == "abc123"
    assert body["protocol_config"]["config_hash"] == "p123"
    mocked_market.assert_awaited_once()
    mocked_protocol.assert_awaited_once()


def test_compound_market_config_period_route_v2_detail_returns_protocol_config() -> (
    None
):
    with (
        patch(
            "compound_crawler.api.routes.get_v2_market_config_period",
            new=AsyncMock(return_value=SimpleNamespace(points=[_market_payload()])),
        ) as mocked_market_period,
        patch(
            "compound_crawler.api.routes.get_v2_protocol_config",
            new=AsyncMock(return_value=_protocol_payload()),
        ) as mocked_protocol,
    ):
        with _build_client() as client:
            resp = client.get(
                "/api/compound/market/config/period",
                params={
                    "version": "v2",
                    "market": "cDAI",
                    "start": "2026-03-24T00:00:00Z",
                    "end": "2026-03-25T00:00:00Z",
                    "detail": "true",
                },
            )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["points"]) == 1
    assert body["points"][0]["version"] == "v2"
    assert body["points"][0]["market_config"]["config_hash"] == "abc123"
    assert body["points"][0]["protocol_config"]["config_hash"] == "p123"
    mocked_market_period.assert_awaited_once()
    mocked_protocol.assert_awaited_once()
