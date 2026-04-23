from __future__ import annotations

from datetime import datetime, timezone
from typing import Generator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from aave_crawler.api.routes import common_router
from aave_crawler.database import get_pool
from tests.fixtures.aave import MOCK_PRICE_HIST, MOCK_PRICE_ONCHAIN, MOCK_PRICE_PERIOD
from tests.helpers.routes import build_test_app, build_test_client

_COMMON_ROUTES = "crawler_shared.api.routes"


def _build_client(*, with_w3: bool = True) -> TestClient:
    async def _override_pool():
        return object()

    state = {
        "justlend_cfg": object(),
        "tron_rpc": object(),
    }
    if with_w3:
        state["w3"] = object()

    return build_test_client(
        router=common_router,
        dependency_overrides={get_pool: _override_pool},
        state=state,
    )


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with _build_client() as client:
        yield client


@pytest.fixture
def app_no_w3():
    async def _override_pool():
        return object()

    return build_test_app(
        router=common_router,
        dependency_overrides={get_pool: _override_pool},
        state={"w3": None, "justlend_cfg": object(), "tron_rpc": object()},
    )


class TestPrice:
    """GET /api/price — symbol 与 address 二选一，time 默认 now。"""

    def test_defaults_return_onchain_price(self, client: TestClient):
        resp = client.get("/api/price")
        assert resp.status_code == 400

    def test_time_now_explicit(self, client: TestClient):
        with patch(
            f"{_COMMON_ROUTES}.get_price",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_ONCHAIN,
        ) as mock_svc:
            resp = client.get("/api/price", params={"symbol": "eth", "time": "now"})
        assert resp.status_code == 200
        assert resp.json()["source"] == "on-chain"
        _, kwargs = mock_svc.call_args
        assert kwargs["symbol"] == "eth"
        assert kwargs["address"] is None

    @pytest.mark.parametrize("symbol", ["eth", "ETH", "wbtc", "WBTC", "usdc"])
    def test_various_symbols_realtime(self, client: TestClient, symbol: str):
        with patch(
            f"{_COMMON_ROUTES}.get_price",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_ONCHAIN,
        ):
            resp = client.get("/api/price", params={"symbol": symbol})
        assert resp.status_code == 200

    def test_address_realtime_ok(self, client: TestClient):
        with patch(
            f"{_COMMON_ROUTES}.get_price",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_ONCHAIN,
        ) as mock_svc:
            resp = client.get(
                "/api/price",
                params={"address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"},
            )
        assert resp.status_code == 200
        _, kwargs = mock_svc.call_args
        assert kwargs["symbol"] is None
        assert kwargs["address"] == "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"

    def test_tron_symbol_chain_forwarded(self, client: TestClient):
        with patch(
            f"{_COMMON_ROUTES}.get_price",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_ONCHAIN,
        ) as mock_svc:
            resp = client.get("/api/price", params={"symbol": "usdt", "chain": "tron"})
        assert resp.status_code == 200
        _, kwargs = mock_svc.call_args
        assert kwargs["chain"] == "tron"

    def test_symbol_and_address_together_returns_400(self, client: TestClient):
        resp = client.get(
            "/api/price",
            params={
                "symbol": "eth",
                "address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            },
        )
        assert resp.status_code == 400

    def test_unknown_symbol_returns_404(self, client: TestClient):
        with patch(
            f"{_COMMON_ROUTES}.get_price",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="未找到资产"),
        ):
            resp = client.get("/api/price", params={"symbol": "FAKETOKEN"})
        assert resp.status_code == 404

    def test_no_w3_returns_503(self, app_no_w3):
        with TestClient(app_no_w3) as c:
            resp = c.get("/api/price", params={"symbol": "eth"})
        assert resp.status_code == 503

    def test_historical_price_ok(self, client: TestClient):
        with patch(
            f"{_COMMON_ROUTES}.get_price",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_HIST,
        ) as mock_svc:
            resp = client.get(
                "/api/price", params={"symbol": "eth", "time": "2024-06-01"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "defillama"
        _, kwargs = mock_svc.call_args
        assert kwargs.get("timestamp") is not None
        assert isinstance(kwargs["timestamp"], int)

    @pytest.mark.parametrize(
        "time_str",
        [
            "2024-06-01",
            "2024-06-01T12:00:00Z",
            "2024-06-01T12:00:00",
            "2024-06-01 12:00:00",
        ],
    )
    def test_historical_time_formats_accepted(self, client: TestClient, time_str: str):
        with patch(
            f"{_COMMON_ROUTES}.get_price",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_HIST,
        ):
            resp = client.get("/api/price", params={"symbol": "eth", "time": time_str})
        assert resp.status_code == 200

    def test_historical_correct_timestamp_passed(self, client: TestClient):
        expected_ts = int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp())
        with patch(
            f"{_COMMON_ROUTES}.get_price",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_HIST,
        ) as mock_svc:
            client.get("/api/price", params={"symbol": "eth", "time": "2024-06-01"})
        _, kwargs = mock_svc.call_args
        assert kwargs["timestamp"] == expected_ts

    @pytest.mark.parametrize(
        "bad_time",
        [
            "yesterday",
            "2024-13-01",
            "2024.06.01",
            "06/01/2024",
        ],
    )
    def test_invalid_time_format_returns_400(self, client: TestClient, bad_time: str):
        resp = client.get("/api/price", params={"time": bad_time})
        assert resp.status_code == 400

    def test_defillama_failure_returns_502(self, client: TestClient):
        with patch(
            f"{_COMMON_ROUTES}.get_price",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=502, detail="DeFiLlama 不可用"),
        ):
            resp = client.get(
                "/api/price", params={"symbol": "eth", "time": "2024-06-01"}
            )
        assert resp.status_code == 502

    def test_historical_no_w3_returns_503(self, app_no_w3):
        with TestClient(app_no_w3) as c:
            resp = c.get("/api/price", params={"symbol": "eth", "time": "2024-06-01"})
        assert resp.status_code == 503


class TestPricePeriod:
    """GET /api/price/period — 按间隔查询资产历史价格序列。"""

    _BASE_PARAMS = {
        "symbol": "eth",
        "start": "2024-06-01",
        "end": "2024-06-03",
        "interval": 60,
    }

    def test_ok_returns_price_period(self, client: TestClient):
        with patch(
            f"{_COMMON_ROUTES}.get_price_period_service",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_PERIOD,
        ):
            resp = client.get("/api/price/period", params=self._BASE_PARAMS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset"] == "ETH"
        assert data["source"] == "defillama"
        assert isinstance(data["prices"], list)
        assert len(data["prices"]) == 3
        assert "price_usd" in data["prices"][0]
        assert "timestamp" in data["prices"][0]

    def test_service_receives_correct_params(self, client: TestClient):
        expected_start = int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp())
        expected_end = int(datetime(2024, 6, 3, tzinfo=timezone.utc).timestamp())
        with patch(
            f"{_COMMON_ROUTES}.get_price_period_service",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_PERIOD,
        ) as mock_svc:
            client.get("/api/price/period", params=self._BASE_PARAMS)
        _, kwargs = mock_svc.call_args
        assert kwargs["symbol"] == "eth"
        assert kwargs["address"] is None
        assert kwargs["start"] == expected_start
        assert kwargs["end"] == expected_end
        assert kwargs["interval"] == 60

    def test_default_interval_is_60(self, client: TestClient):
        with patch(
            f"{_COMMON_ROUTES}.get_price_period_service",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_PERIOD,
        ) as mock_svc:
            client.get(
                "/api/price/period",
                params={"symbol": "eth", "start": "2024-06-01", "end": "2024-06-03"},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["interval"] == 60

    @pytest.mark.parametrize("interval", [15, 30, 60, 1440])
    def test_various_intervals_accepted(self, client: TestClient, interval: int):
        with patch(
            f"{_COMMON_ROUTES}.get_price_period_service",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_PERIOD,
        ):
            resp = client.get(
                "/api/price/period",
                params={
                    "symbol": "eth",
                    "start": "2024-06-01",
                    "end": "2024-06-30",
                    "interval": interval,
                },
            )
        assert resp.status_code == 200

    @pytest.mark.parametrize("interval", [0, 1, 14])
    def test_interval_under_15_returns_422(self, client: TestClient, interval: int):
        resp = client.get(
            "/api/price/period",
            params={
                "symbol": "eth",
                "start": "2024-06-01",
                "end": "2024-06-30",
                "interval": interval,
            },
        )
        assert resp.status_code == 422

    def test_missing_start_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/price/period", params={"symbol": "eth", "end": "2024-06-30"}
        )
        assert resp.status_code == 422

    def test_missing_end_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/price/period", params={"symbol": "eth", "start": "2024-06-01"}
        )
        assert resp.status_code == 422

    def test_invalid_start_time_returns_400(self, client: TestClient):
        with patch(
            f"{_COMMON_ROUTES}.get_price_period_service",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_PERIOD,
        ):
            resp = client.get(
                "/api/price/period",
                params={"symbol": "eth", "start": "not-a-date", "end": "2024-06-30"},
            )
        assert resp.status_code == 400

    def test_invalid_end_time_returns_400(self, client: TestClient):
        with patch(
            f"{_COMMON_ROUTES}.get_price_period_service",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_PERIOD,
        ):
            resp = client.get(
                "/api/price/period",
                params={"symbol": "eth", "start": "2024-06-01", "end": "invalid"},
            )
        assert resp.status_code == 400

    def test_no_w3_returns_503(self, app_no_w3):
        with TestClient(app_no_w3) as c:
            resp = c.get("/api/price/period", params=self._BASE_PARAMS)
        assert resp.status_code == 503

    def test_unknown_symbol_returns_404(self, client: TestClient):
        with patch(
            f"{_COMMON_ROUTES}.get_price_period_service",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="未找到资产"),
        ):
            resp = client.get(
                "/api/price/period",
                params={
                    "symbol": "FAKETOKEN",
                    "start": "2024-06-01",
                    "end": "2024-06-30",
                },
            )
        assert resp.status_code == 404

    def test_address_ok(self, client: TestClient):
        with patch(
            f"{_COMMON_ROUTES}.get_price_period_service",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_PERIOD,
        ) as mock_svc:
            resp = client.get(
                "/api/price/period",
                params={
                    "address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
                    "start": "2024-06-01",
                    "end": "2024-06-30",
                },
            )
        assert resp.status_code == 200
        _, kwargs = mock_svc.call_args
        assert kwargs["symbol"] is None
        assert kwargs["address"] == "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"

    def test_symbol_and_address_together_returns_400(self, client: TestClient):
        resp = client.get(
            "/api/price/period",
            params={
                "symbol": "eth",
                "address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
                "start": "2024-06-01",
                "end": "2024-06-30",
            },
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        "time_str",
        [
            "2024-06-01",
            "2024-06-01T12:00:00Z",
            "2024-06-01T12:00:00",
            "2024-06-01 12:00:00",
        ],
    )
    def test_various_time_formats_accepted(self, client: TestClient, time_str: str):
        with patch(
            f"{_COMMON_ROUTES}.get_price_period_service",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_PERIOD,
        ):
            resp = client.get(
                "/api/price/period",
                params={
                    "symbol": "eth",
                    "start": time_str,
                    "end": time_str,
                    "interval": 60,
                },
            )
        assert resp.status_code == 200
