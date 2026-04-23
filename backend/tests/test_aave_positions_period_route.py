from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from tests.fixtures.aave import MOCK_POSITIONS_PERIOD

_ROUTES = "aave_crawler.api.routes"


class TestPositionsPeriod:
    """GET /api/aave/positions/period — 日级 ETH 抵押仓位统计时序。"""

    _URL = "/api/aave/positions/period"
    _BASE = {"start": "2025-01-01", "end": "2025-01-03"}

    def test_ok_returns_list(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_positions_period",
            new_callable=AsyncMock,
            return_value=MOCK_POSITIONS_PERIOD,
        ):
            resp = client.get(self._URL, params=self._BASE)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 3
        item = data[0]
        assert "snapshot_date" in item
        assert "liquidation_cnt" in item
        assert "total_eth_collateral_amount" in item
        assert "total_eth_collateral_usd" in item
        assert "total_weth_debt_amount" in item
        assert "total_weth_debt_usd" in item
        assert "eth_price" in item
        assert "sim_eth_price" in item

    def test_service_receives_correct_params(self, client: TestClient):
        from datetime import datetime, timezone

        expected_start = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
        expected_end = int(datetime(2025, 1, 3, tzinfo=timezone.utc).timestamp())
        with patch(
            f"{_ROUTES}.get_positions_period",
            new_callable=AsyncMock,
            return_value=MOCK_POSITIONS_PERIOD,
        ) as mock_svc:
            client.get(
                self._URL,
                params={
                    "start": "2025-01-01",
                    "end": "2025-01-03",
                    "interval": 7,
                    "sim_eth_price_distance": -10.0,
                    "version": "v2",
                },
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["start_ts"] == expected_start
        assert kwargs["end_ts"] == expected_end
        assert kwargs["interval_days"] == 7
        assert kwargs["sim_eth_price_distance"] == -10.0
        assert kwargs["protocol"] == "v2"

    def test_default_params(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_positions_period",
            new_callable=AsyncMock,
            return_value=MOCK_POSITIONS_PERIOD,
        ) as mock_svc:
            client.get(self._URL, params=self._BASE)
        _, kwargs = mock_svc.call_args
        assert kwargs["interval_days"] == 1
        assert kwargs["sim_eth_price_distance"] == 0.0
        assert kwargs["protocol"] == "v3"

    def test_missing_start_returns_422(self, client: TestClient):
        resp = client.get(self._URL, params={"end": "2025-01-03"})
        assert resp.status_code == 422

    def test_missing_end_returns_422(self, client: TestClient):
        resp = client.get(self._URL, params={"start": "2025-01-01"})
        assert resp.status_code == 422

    def test_interval_zero_returns_422(self, client: TestClient):
        resp = client.get(self._URL, params={**self._BASE, "interval": 0})
        assert resp.status_code == 422

    def test_interval_negative_returns_422(self, client: TestClient):
        resp = client.get(self._URL, params={**self._BASE, "interval": -1})
        assert resp.status_code == 422

    def test_start_after_end_returns_400(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_positions_period",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get(
                self._URL, params={"start": "2025-01-10", "end": "2025-01-01"}
            )
        assert resp.status_code == 400

    def test_invalid_version_returns_422(self, client: TestClient):
        resp = client.get(self._URL, params={**self._BASE, "version": "v4"})
        assert resp.status_code == 422

    def test_empty_result_returns_empty_list(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_positions_period",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get(self._URL, params=self._BASE)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get(self._URL, params=self._BASE)
        assert resp.status_code == 503

    @pytest.mark.parametrize("version", ["v2", "v3"])
    def test_both_versions_accepted(self, client: TestClient, version: str):
        with patch(
            f"{_ROUTES}.get_positions_period",
            new_callable=AsyncMock,
            return_value=MOCK_POSITIONS_PERIOD,
        ):
            resp = client.get(self._URL, params={**self._BASE, "version": version})
        assert resp.status_code == 200

    @pytest.mark.parametrize("interval", [1, 7, 30])
    def test_various_intervals_accepted(self, client: TestClient, interval: int):
        with patch(
            f"{_ROUTES}.get_positions_period",
            new_callable=AsyncMock,
            return_value=MOCK_POSITIONS_PERIOD,
        ):
            resp = client.get(self._URL, params={**self._BASE, "interval": interval})
        assert resp.status_code == 200

    @pytest.mark.parametrize("distance", [-50.0, -10.0, 0.0, 10.0, 50.0])
    def test_various_sim_distances_accepted(self, client: TestClient, distance: float):
        with patch(
            f"{_ROUTES}.get_positions_period",
            new_callable=AsyncMock,
            return_value=MOCK_POSITIONS_PERIOD,
        ):
            resp = client.get(
                self._URL,
                params={**self._BASE, "sim_eth_price_distance": distance},
            )
        assert resp.status_code == 200
