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


def _payload() -> dict[str, object]:
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


def test_compound_protocol_config_route_ok() -> None:
    with patch(
        "compound_crawler.api.routes.get_v2_protocol_config",
        new=AsyncMock(return_value=_payload()),
    ):
        with _build_client() as client:
            resp = client.get("/api/compound/protocol/config", params={"version": "v2"})
    assert resp.status_code == 200
    assert resp.json()["config_hash"] == "p123"


def test_compound_protocol_config_route_ok_with_version_path() -> None:
    with patch(
        "compound_crawler.api.routes.get_v2_protocol_config",
        new=AsyncMock(return_value=_payload()),
    ):
        with _build_client() as client:
            resp = client.get("/api/compound/v2/protocol/config")
    assert resp.status_code == 200
    assert resp.json()["version"] == "v2"


def test_compound_protocol_config_period_route_ok() -> None:
    payload = {"points": [_payload()]}
    with patch(
        "compound_crawler.api.routes.get_v2_protocol_config_period",
        new=AsyncMock(return_value=payload),
    ):
        with _build_client() as client:
            resp = client.get(
                "/api/compound/protocol/config/period",
                params={
                    "version": "v2",
                    "start": "2026-03-24T00:00:00Z",
                    "end": "2026-03-25T00:00:00Z",
                },
            )
    assert resp.status_code == 200
    assert len(resp.json()["points"]) == 1
