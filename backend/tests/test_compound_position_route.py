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
