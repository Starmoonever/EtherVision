from __future__ import annotations

from aave_crawler.api.routes import router as aave_router
from fastapi import FastAPI
from starlette.testclient import TestClient


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(aave_router)
    return TestClient(app)


def test_aave_path_version_compat_redirects_to_query_version() -> None:
    with _build_client() as client:
        resp = client.get(
            "/api/aave/v2/positions",
            params={"limit": 5, "order": "asc"},
            follow_redirects=False,
        )

    assert resp.status_code == 307
    location = resp.headers.get("location", "")
    assert location.startswith("/api/aave/positions?")
    assert "version=v2" in location
    assert "limit=5" in location
    assert "order=asc" in location
