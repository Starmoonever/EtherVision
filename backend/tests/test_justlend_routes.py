from __future__ import annotations

from fastapi import FastAPI
from justlend_crawler.database import get_pool
from starlette.testclient import TestClient

from justlend_crawler.api.routes import router as justlend_router


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(justlend_router)
    app.state.cfg = object()

    async def _override_pool():
        return object()

    app.dependency_overrides[get_pool] = _override_pool
    return TestClient(app)


def test_status_route_returns_scaffold_metadata() -> None:
    with _build_client() as client:
        response = client.get("/api/justlend/status")

    assert response.status_code == 200
    assert response.json() == {
        "module": "justlend",
        "status": "scaffold",
        "chain": "tron",
        "supported_protocols": ["trx"],
        "message": "JustLend backend scaffold is wired into the unified API. Data collection and query logic are pending.",
    }


def test_markets_route_returns_empty_scaffold_list() -> None:
    with _build_client() as client:
        response = client.get("/api/justlend/markets")

    assert response.status_code == 200
    assert response.json() == {"chain": "tron", "markets": []}


def test_position_route_requires_address() -> None:
    with _build_client() as client:
        response = client.get(
            "/api/justlend/position",
            params={"protocol": "trx"},
        )

    assert response.status_code == 422
