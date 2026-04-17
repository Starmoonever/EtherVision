from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from justlend_crawler.api.routes import router as justlend_router
from justlend_crawler.database import get_pool
from starlette.testclient import TestClient


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(justlend_router)
    app.state.cfg = object()
    app.state.tron_rpc = object()

    async def _override_pool():
        return object()

    app.dependency_overrides[get_pool] = _override_pool
    return TestClient(app)


def test_justlend_position_route_ok() -> None:
    payload = {
        "protocol": "trx",
        "chain": "tron",
        "address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
        "snapshot_at": "2026-04-03T00:00:00Z",
        "block_timestamp": "2026-04-03T00:00:00Z",
        "total_collateral_usd": "100.00000000",
        "total_debt_usd": "20.00000000",
        "available_borrow_usd": "55.00000000",
        "health_factor": "5.000000000000000000",
        "ltv": "0.750000",
        "liquidation_threshold": "0.750000",
        "data_source": "database",
        "assets": [],
    }

    with patch(
        "justlend_crawler.api.routes.get_user_position",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/justlend/position",
                params={
                    "address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
                    "protocol": "trx",
                },
            )

    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_awaited_once()


def test_justlend_position_replay_route_ok() -> None:
    payload = {
        "address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
        "protocol": "trx",
        "from_time": "2026-04-01T00:00:00Z",
        "to_time": "2026-04-03T00:00:00Z",
        "data_source": "cache",
        "points": [],
        "total_points": 0,
        "total_tx_count": 0,
        "cache_hit_rate": "1.00",
    }

    with patch(
        "justlend_crawler.api.routes.get_position_replay",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/justlend/position/replay",
                params={
                    "address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
                    "protocol": "trx",
                    "start": "2026-04-01",
                    "end": "2026-04-03",
                },
            )

    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_awaited_once()
    await_args = mocked_service.await_args
    assert await_args is not None
    assert await_args.kwargs["tron_rpc"] is not None


def test_justlend_position_replay_route_rejects_invalid_time() -> None:
    with _build_client() as client:
        resp = client.get(
            "/api/justlend/position/replay",
            params={
                "address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
                "protocol": "trx",
                "start": "invalid",
                "end": "2026-04-03",
            },
        )

    assert resp.status_code == 400


def test_justlend_positions_route_ok() -> None:
    payload = {
        "items": [
            {
                "protocol": "trx",
                "chain": "tron",
                "address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
                "snapshot_at": "2026-04-03T00:00:00Z",
                "block_timestamp": "2026-04-03T00:00:00Z",
                "total_supply_usd": "100.00000000",
                "total_borrow_usd": "20.00000000",
                "health_factor": "5.000000000000000000",
                "ltv": "0.750000",
                "liquidation_threshold": "0.750000",
                "matched_asset_value_usd": "80.00000000",
                "assets": [],
            }
        ],
        "page": 2,
        "page_size": 20,
        "total": 123,
        "sort_by": "asset_value_usd",
        "order": "desc",
        "side": "supply",
        "asset": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    }

    with patch(
        "justlend_crawler.api.routes.get_positions",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get(
                "/api/justlend/positions",
                params={
                    "page": 2,
                    "page_size": 20,
                    "sort_by": "asset_value_usd",
                    "order": "desc",
                    "side": "supply",
                    "asset": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
                    "detail": "true",
                },
            )

    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_awaited_once()


def test_justlend_tx_ops_route_ok() -> None:
    payload = [
        "deposit",
        "redeem",
        "withdraw",
        "borrow",
        "repay",
        "repay_behalf",
        "liquidation",
    ]

    with patch(
        "justlend_crawler.api.routes.get_supported_tx_operation_types",
        return_value=payload,
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get("/api/justlend/tx/ops")

    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_called_once()
