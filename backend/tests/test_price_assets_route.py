from __future__ import annotations

from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from aave_crawler.api.routes import common_router
from aave_crawler.database import get_pool
from tests.helpers.routes import build_test_client


def _build_client() -> TestClient:
    async def _override_pool():
        return object()

    return build_test_client(
        router=common_router,
        dependency_overrides={get_pool: _override_pool},
        state={"w3": object(), "justlend_cfg": object()},
    )


def test_price_assets_route_ok() -> None:
    payload = {
        "assets": [
            {
                "asset": "WETH",
                "token_address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
                "chain": "ethereum",
            },
            {
                "asset": "USDT",
                "token_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
                "chain": "tron",
            },
        ]
    }

    with patch(
        "crawler_shared.api.routes.get_supported_price_assets",
        new=AsyncMock(return_value=payload),
    ) as mocked_service:
        with _build_client() as client:
            resp = client.get("/api/price/assets")

    assert resp.status_code == 200
    assert resp.json() == payload
    mocked_service.assert_awaited_once()
