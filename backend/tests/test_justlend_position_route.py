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
