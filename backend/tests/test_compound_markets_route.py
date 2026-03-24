from __future__ import annotations

from unittest.mock import patch

from compound_crawler.api.routes import router as compound_router
from fastapi import FastAPI
from starlette.testclient import TestClient


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(compound_router)
    return TestClient(app)


def test_compound_markets_route_ok() -> None:
    payload = {
        "version": "v3",
        "markets": [
            {
                "address": "0xc3d688b66703497daa19211eedff47f25384cdc3",
                "symbol": "USDC",
            }
        ],
    }

    with patch(
        "compound_crawler.api.routes.get_markets", return_value=payload
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get("/api/compound/markets", params={"version": "v3"})

    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_called_once_with("v3")


def test_compound_markets_route_rejects_v2() -> None:
    with _build_client() as client:
        resp = client.get("/api/compound/markets", params={"version": "v2"})

    assert resp.status_code == 400
    assert "仅支持" in resp.json()["detail"]
