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


def test_compound_position_route_ok() -> None:
    payload = {
        "version": "v3",
        "address": "0x1111111111111111111111111111111111111111",
        "positions": [],
    }

    with patch(
        "compound_crawler.api.routes.get_positions",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/compound/position",
                params={
                    "version": "v3",
                    "market": "weth",
                    "address": "0x1111111111111111111111111111111111111111",
                    "date": "2026-03-21T00:00:00Z",
                },
            )

    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_awaited_once()
    await_args = mocked_service.await_args
    assert await_args is not None
    assert await_args.kwargs["market"] == "weth"
    assert await_args.kwargs["address"] == "0x1111111111111111111111111111111111111111"


def test_compound_position_route_v2_ok() -> None:
    payload = {
        "version": "v2",
        "address": "0x1111111111111111111111111111111111111111",
        "positions": [],
    }

    with patch(
        "compound_crawler.api.routes.get_positions",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/compound/position",
                params={
                    "version": "v2",
                    "market": "ceth",
                    "address": "0x1111111111111111111111111111111111111111",
                    "date": "2026-03-21",
                },
            )

    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_awaited_once()
    await_args = mocked_service.await_args
    assert await_args is not None
    assert await_args.kwargs["version"] == "v2"


def test_compound_position_route_path_version_removed() -> None:
    with _build_client() as client:
        resp = client.get(
            "/api/compound/v2/position",
            params={
                "market": "all",
                "address": "0x1111111111111111111111111111111111111111",
            },
        )
    assert resp.status_code == 404


def test_compound_position_route_requires_market() -> None:
    with _build_client() as client:
        resp = client.get(
            "/api/compound/position",
            params={
                "version": "v3",
                "address": "0x1111111111111111111111111111111111111111",
            },
        )

    assert resp.status_code == 422


def test_compound_position_route_requires_address() -> None:
    with _build_client() as client:
        resp = client.get(
            "/api/compound/position", params={"version": "v3", "market": "all"}
        )

    assert resp.status_code == 422


def test_compound_position_replay_route_ok() -> None:
    payload = {
        "address": "0x1111111111111111111111111111111111111111",
        "version": "v3",
        "from_time": "2026-03-01T00:00:00Z",
        "to_time": "2026-03-10T00:00:00Z",
        "data_source": "cache",
        "points": [],
        "total_points": 0,
        "total_tx_count": 0,
        "cache_hit_rate": "1.00",
    }
    with patch(
        "compound_crawler.api.routes.get_position_replay",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/compound/position/replay",
                params={
                    "address": "0x1111111111111111111111111111111111111111",
                    "start": "2026-03-01",
                    "end": "2026-03-10",
                    "version": "v3",
                },
            )
    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_awaited_once()


def test_compound_position_replay_route_rejects_invalid_time() -> None:
    with _build_client() as client:
        resp = client.get(
            "/api/compound/position/replay",
            params={
                "address": "0x1111111111111111111111111111111111111111",
                "start": "invalid",
                "end": "2026-03-10",
                "version": "v3",
            },
        )
    assert resp.status_code == 400


def test_compound_liquidate_route_ok() -> None:
    payload = {
        "version": "v3",
        "simulated_eth_price": "1500",
        "positions": [],
        "positions_cnt": "0",
        "total_eth_sensitive_collateral_usd": "0",
        "total_liquidation_usd": "0",
        "note": "",
    }
    with patch(
        "compound_crawler.api.routes.simulate_liquidation",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/compound/liquidate",
                params={
                    "version": "v3",
                    "eth_price": 1500,
                    "market": "all",
                },
            )
    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_awaited_once()


def test_compound_liquidate_period_route_ok() -> None:
    payload = [
        {
            "simulated_eth_price": "1400",
            "positions_cnt": "2",
            "total_eth_sensitive_collateral_usd": "3500",
            "total_liquidation_usd": "1800",
        },
        {
            "simulated_eth_price": "1500",
            "positions_cnt": "1",
            "total_eth_sensitive_collateral_usd": "1200",
            "total_liquidation_usd": "900",
        },
    ]
    with patch(
        "compound_crawler.api.routes.simulate_liquidation_period",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/compound/liquidate/period",
                params={
                    "version": "v3",
                    "start": 1400,
                    "end": 1500,
                    "interval": 100,
                    "market": "all",
                },
            )

    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_awaited_once()
