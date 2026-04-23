from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from tests.fixtures.aave import ADDR, MOCK_REPLAY_RESPONSE, MOCK_TX_HISTORY_RESPONSE

_ROUTES = "aave_crawler.api.routes"


class TestPositionReplay:
    """GET /api/aave/position/replay — 必须参数 address / start / end。"""

    _URL = "/api/aave/position/replay"
    _BASE = {"address": ADDR, "start": "2025-01-01", "end": "2026-01-01"}

    def test_missing_address_returns_422(self, client: TestClient):
        resp = client.get(
            self._URL, params={"start": "2025-01-01", "end": "2026-01-01"}
        )
        assert resp.status_code == 422

    def test_missing_start_returns_422(self, client: TestClient):
        resp = client.get(self._URL, params={"address": ADDR, "end": "2026-01-01"})
        assert resp.status_code == 422

    def test_missing_end_returns_422(self, client: TestClient):
        resp = client.get(self._URL, params={"address": ADDR, "start": "2025-01-01"})
        assert resp.status_code == 422

    def test_invalid_start_returns_400(self, client: TestClient):
        resp = client.get(self._URL, params={**self._BASE, "start": "not-a-date"})
        assert resp.status_code == 400

    def test_invalid_end_returns_400(self, client: TestClient):
        resp = client.get(self._URL, params={**self._BASE, "end": "2025/12/31"})
        assert resp.status_code == 400

    def test_start_after_end_returns_400(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_position_replay",
            new_callable=AsyncMock,
            return_value=MOCK_REPLAY_RESPONSE,
        ):
            resp = client.get(
                self._URL,
                params={"address": ADDR, "start": "2026-01-01", "end": "2025-01-01"},
            )
        assert resp.status_code == 400

    def test_ok_returns_200_with_fields(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_position_replay",
            new_callable=AsyncMock,
            return_value=MOCK_REPLAY_RESPONSE,
        ):
            resp = client.get(self._URL, params=self._BASE)
        assert resp.status_code == 200
        data = resp.json()
        for field in (
            "address",
            "protocol",
            "from_time",
            "to_time",
            "data_source",
            "points",
            "total_points",
            "cache_hit_rate",
        ):
            assert field in data, f"缺少字段: {field}"

    def test_points_is_list(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_position_replay",
            new_callable=AsyncMock,
            return_value=MOCK_REPLAY_RESPONSE,
        ):
            resp = client.get(self._URL, params=self._BASE)
        assert isinstance(resp.json()["points"], list)
        assert resp.json()["total_points"] == 1

    def test_point_fields(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_position_replay",
            new_callable=AsyncMock,
            return_value=MOCK_REPLAY_RESPONSE,
        ):
            resp = client.get(self._URL, params=self._BASE)
        point = resp.json()["points"][0]
        for field in (
            "tx_hash",
            "block_number",
            "timestamp",
            "eth_price_usd",
            "total_collateral_usd",
            "total_debt_usd",
            "health_factor",
            "liq_price",
            "liq_price_rise",
            "eth_collateral_amount",
            "eth_collateral_usd",
            "weth_debt_amount",
            "weth_debt_usd",
        ):
            assert field in point, f"point 缺少字段: {field}"

    def test_no_pool_returns_503(self, app_no_pool: FastAPI):
        with TestClient(app_no_pool) as c:
            resp = c.get(self._URL, params=self._BASE)
        assert resp.status_code == 503

    def test_no_w3_returns_503(self, app_no_w3: FastAPI):
        with TestClient(app_no_w3) as c:
            resp = c.get(self._URL, params=self._BASE)
        assert resp.status_code == 503

    @pytest.mark.parametrize(
        "date_str",
        [
            "2025-01-01",
            "2025-01-01T00:00:00Z",
            "2025-01-01T00:00:00",
            "2025-01-01 00:00:00",
        ],
    )
    def test_various_date_formats_accepted(self, client: TestClient, date_str: str):
        with patch(
            f"{_ROUTES}.get_user_position_replay",
            new_callable=AsyncMock,
            return_value=MOCK_REPLAY_RESPONSE,
        ):
            resp = client.get(
                self._URL,
                params={"address": ADDR, "start": date_str, "end": "2026-01-01"},
            )
        assert resp.status_code == 200

    @pytest.mark.parametrize("version,expected", [("v3", "v3"), ("v2", "v2")])
    def test_version_passed_to_service(
        self, client: TestClient, version: str, expected: str
    ):
        with patch(
            f"{_ROUTES}.get_user_position_replay",
            new_callable=AsyncMock,
            return_value=MOCK_REPLAY_RESPONSE,
        ) as mock_svc:
            client.get(self._URL, params={**self._BASE, "version": version})
        _, kwargs = mock_svc.call_args
        assert kwargs["protocol"] == expected

    def test_invalid_version_returns_422(self, client: TestClient):
        resp = client.get(self._URL, params={**self._BASE, "version": "v4"})
        assert resp.status_code == 422

    def test_use_cache_false_passed_to_service(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_position_replay",
            new_callable=AsyncMock,
            return_value=MOCK_REPLAY_RESPONSE,
        ) as mock_svc:
            client.get(self._URL, params={**self._BASE, "use_cache": "false"})
        _, kwargs = mock_svc.call_args
        assert kwargs["use_cache"] is False

    def test_detail_true_passed_to_service(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_position_replay",
            new_callable=AsyncMock,
            return_value=MOCK_REPLAY_RESPONSE,
        ) as mock_svc:
            client.get(self._URL, params={**self._BASE, "detail": "true"})
        _, kwargs = mock_svc.call_args
        assert kwargs["detail"] is True


class TestTxHistory:
    """GET /api/aave/txs — 必须参数 address / start / end。"""

    _URL = "/api/aave/txs"
    _BASE = {"address": ADDR, "start": "2025-01-01", "end": "2026-01-01"}

    def test_missing_address_returns_422(self, client: TestClient):
        resp = client.get(
            self._URL, params={"start": "2025-01-01", "end": "2026-01-01"}
        )
        assert resp.status_code == 422

    def test_missing_start_returns_422(self, client: TestClient):
        resp = client.get(self._URL, params={"address": ADDR, "end": "2026-01-01"})
        assert resp.status_code == 422

    def test_missing_end_returns_422(self, client: TestClient):
        resp = client.get(self._URL, params={"address": ADDR, "start": "2025-01-01"})
        assert resp.status_code == 422

    def test_invalid_start_returns_400(self, client: TestClient):
        resp = client.get(self._URL, params={**self._BASE, "start": "not-a-date"})
        assert resp.status_code == 400

    def test_ok_returns_200_with_fields(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_tx_history",
            new_callable=AsyncMock,
            return_value=MOCK_TX_HISTORY_RESPONSE,
        ):
            resp = client.get(self._URL, params=self._BASE)
        assert resp.status_code == 200
        data = resp.json()
        for field in ("address", "protocol", "from_time", "to_time", "txs", "total"):
            assert field in data, f"缺少字段: {field}"

    def test_txs_is_list(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_tx_history",
            new_callable=AsyncMock,
            return_value=MOCK_TX_HISTORY_RESPONSE,
        ):
            resp = client.get(self._URL, params=self._BASE)
        data = resp.json()
        assert isinstance(data["txs"], list)
        assert data["total"] == 2

    def test_tx_fields(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_tx_history",
            new_callable=AsyncMock,
            return_value=MOCK_TX_HISTORY_RESPONSE,
        ):
            resp = client.get(self._URL, params=self._BASE)
        tx = resp.json()["txs"][0]
        for field in (
            "tx_hash",
            "block_number",
            "timestamp",
            "operation_type",
            "token_symbol",
            "cached",
        ):
            assert field in tx, f"tx 缺少字段: {field}"

    def test_cached_flag_type(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_tx_history",
            new_callable=AsyncMock,
            return_value=MOCK_TX_HISTORY_RESPONSE,
        ):
            resp = client.get(self._URL, params=self._BASE)
        txs = resp.json()["txs"]
        assert txs[0]["cached"] is True
        assert txs[1]["cached"] is False

    def test_no_pool_returns_503(self, app_no_pool: FastAPI):
        with TestClient(app_no_pool) as c:
            resp = c.get(self._URL, params=self._BASE)
        assert resp.status_code == 503

    @pytest.mark.parametrize(
        "date_str",
        [
            "2025-01-01",
            "2025-01-01T00:00:00Z",
            "2025-01-01T00:00:00",
            "2025-01-01 00:00:00",
        ],
    )
    def test_various_date_formats_accepted(self, client: TestClient, date_str: str):
        with patch(
            f"{_ROUTES}.get_user_tx_history",
            new_callable=AsyncMock,
            return_value=MOCK_TX_HISTORY_RESPONSE,
        ):
            resp = client.get(
                self._URL,
                params={"address": ADDR, "start": date_str, "end": "2026-01-01"},
            )
        assert resp.status_code == 200

    @pytest.mark.parametrize("version,expected", [("v3", "v3"), ("v2", "v2")])
    def test_version_passed_to_service(
        self, client: TestClient, version: str, expected: str
    ):
        with patch(
            f"{_ROUTES}.get_user_tx_history",
            new_callable=AsyncMock,
            return_value=MOCK_TX_HISTORY_RESPONSE,
        ) as mock_svc:
            client.get(self._URL, params={**self._BASE, "version": version})
        _, kwargs = mock_svc.call_args
        assert kwargs["protocol"] == expected

    def test_invalid_version_returns_422(self, client: TestClient):
        resp = client.get(self._URL, params={**self._BASE, "version": "v4"})
        assert resp.status_code == 422

    def test_address_passed_to_service(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_tx_history",
            new_callable=AsyncMock,
            return_value=MOCK_TX_HISTORY_RESPONSE,
        ) as mock_svc:
            client.get(self._URL, params=self._BASE)
        args, _ = mock_svc.call_args
        assert args[1] == ADDR
