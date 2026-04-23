from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from tests.fixtures.aave import (
    ADDR,
    MOCK_HIST_POSITION,
    MOCK_HIST_POSITIONS_LIST,
    MOCK_POSITION,
    MOCK_POSITIONS_LIST,
)

_ROUTES = "aave_crawler.api.routes"
_404 = HTTPException(status_code=404, detail="无仓位")
_502 = HTTPException(status_code=502, detail="RPC失败")


class TestUserPosition:
    """GET /api/aave/position — 必须参数 address，可选参数 date。"""

    def test_missing_address_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/position")
        assert resp.status_code == 422

    def test_realtime_ok(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_position",
            new_callable=AsyncMock,
            return_value=MOCK_POSITION,
        ):
            resp = client.get("/api/aave/position", params={"address": ADDR})
        assert resp.status_code == 200
        data = resp.json()
        assert data["address"] == ADDR
        assert "health_factor" in data
        assert "liq_price" in data
        assert "total_collateral_usd" in data
        assert "available_borrows_usd" in data
        assert "at_time" not in data

    def test_realtime_empty_position_returns_404(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_position", new_callable=AsyncMock, side_effect=_404
        ):
            resp = client.get("/api/aave/position", params={"address": ADDR})
        assert resp.status_code == 404

    def test_realtime_rpc_failure_returns_502(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_position", new_callable=AsyncMock, side_effect=_502
        ):
            resp = client.get("/api/aave/position", params={"address": ADDR})
        assert resp.status_code == 502

    def test_realtime_no_w3_returns_503(self, app_no_w3):
        with TestClient(app_no_w3) as c:
            resp = c.get("/api/aave/position", params={"address": ADDR})
        assert resp.status_code == 503

    def test_historical_ok(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_position_history",
            new_callable=AsyncMock,
            return_value=MOCK_HIST_POSITION,
        ):
            resp = client.get(
                "/api/aave/position", params={"address": ADDR, "date": "2025-01-01"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "at_time" in data
        assert data["at_time"] == "2025-01-01T00:00:00Z"

    def test_historical_fallback_to_realtime_when_no_history(self, client: TestClient):
        with (
            patch(
                f"{_ROUTES}.get_user_position_history",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{_ROUTES}.get_user_position",
                new_callable=AsyncMock,
                return_value=MOCK_POSITION,
            ),
        ):
            resp = client.get(
                "/api/aave/position", params={"address": ADDR, "date": "2025-01-01"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "health_factor" in data
        assert "at_time" not in data

    @pytest.mark.parametrize(
        "date_str,expected_ts_prefix",
        [
            ("2025-01-01", "2025-01-01T"),
            ("2025-06-15T12:00:00Z", "2025-06-15T"),
            ("2025-06-15T12:00:00", "2025-06-15T"),
            ("2025-06-15 12:00:00", "2025-06-15T"),
        ],
    )
    def test_historical_date_formats_accepted(
        self, client: TestClient, date_str: str, expected_ts_prefix: str
    ):
        with patch(
            f"{_ROUTES}.get_user_position_history",
            new_callable=AsyncMock,
            return_value=MOCK_HIST_POSITION,
        ):
            resp = client.get(
                "/api/aave/position", params={"address": ADDR, "date": date_str}
            )
        assert resp.status_code == 200

    @pytest.mark.parametrize(
        "bad_date",
        [
            "not-a-date",
            "2025/01/01",
            "Jan 1 2025",
            "1704067200",
        ],
    )
    def test_invalid_date_returns_400(self, client: TestClient, bad_date: str):
        resp = client.get(
            "/api/aave/position", params={"address": ADDR, "date": bad_date}
        )
        assert resp.status_code == 400

    def test_historical_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get(
                "/api/aave/position", params={"address": ADDR, "date": "2025-01-01"}
            )
        assert resp.status_code == 503


class TestPositions:
    """GET /api/aave/positions — 可选 orderby / order / limit / date。"""

    def test_defaults_ok(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_sorted_positions",
            new_callable=AsyncMock,
            return_value=MOCK_POSITIONS_LIST,
        ) as mock_svc:
            resp = client.get("/api/aave/positions")
        assert resp.status_code == 200
        mock_svc.assert_awaited_once()
        _, kwargs = mock_svc.call_args
        assert (
            kwargs.get(
                "orderby",
                (
                    mock_svc.call_args.args[1]
                    if len(mock_svc.call_args.args) > 1
                    else "liq_price"
                ),
            )
            is not None
        )
        data = resp.json()
        assert isinstance(data, list)
        item = data[0]
        assert item["address"] == ADDR
        assert "liq_price" in item
        assert "total_collateral_usd" in item
        assert "available_borrows_usd" in item
        assert "total_debt_usd" in item
        assert "health_factor" in item

    @pytest.mark.parametrize("orderby", ["liq_price", "health_factor"])
    def test_orderby_variants(self, client: TestClient, orderby: str):
        with patch(
            f"{_ROUTES}.get_sorted_positions",
            new_callable=AsyncMock,
            return_value=MOCK_POSITIONS_LIST,
        ):
            resp = client.get("/api/aave/positions", params={"orderby": orderby})
        assert resp.status_code == 200

    @pytest.mark.parametrize("order", ["asc", "desc"])
    def test_order_variants(self, client: TestClient, order: str):
        with patch(
            f"{_ROUTES}.get_sorted_positions",
            new_callable=AsyncMock,
            return_value=MOCK_POSITIONS_LIST,
        ):
            resp = client.get("/api/aave/positions", params={"order": order})
        assert resp.status_code == 200

    @pytest.mark.parametrize("limit", [1, 10, 100, 200])
    def test_limit_boundaries_ok(self, client: TestClient, limit: int):
        with patch(
            f"{_ROUTES}.get_sorted_positions",
            new_callable=AsyncMock,
            return_value=MOCK_POSITIONS_LIST,
        ):
            resp = client.get("/api/aave/positions", params={"limit": limit})
        assert resp.status_code == 200

    def test_invalid_orderby_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/positions", params={"orderby": "invalid_field"})
        assert resp.status_code == 422

    def test_invalid_order_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/positions", params={"order": "random"})
        assert resp.status_code == 422

    def test_limit_zero_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/positions", params={"limit": 0})
        assert resp.status_code == 422

    def test_limit_over_max_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/positions", params={"limit": 201})
        assert resp.status_code == 422

    def test_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/aave/positions")
        assert resp.status_code == 503

    def test_historical_ok(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_positions_history",
            new_callable=AsyncMock,
            return_value=MOCK_HIST_POSITIONS_LIST,
        ):
            resp = client.get(
                "/api/aave/positions", params={"date": "2025-01-01", "limit": 10}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert "at_time" in data[0]

    def test_historical_limit_capped_at_100(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_positions_history",
            new_callable=AsyncMock,
            return_value=MOCK_HIST_POSITIONS_LIST,
        ) as mock_svc:
            resp = client.get(
                "/api/aave/positions", params={"date": "2025-01-01", "limit": 150}
            )
        assert resp.status_code == 200
        _, kwargs = mock_svc.call_args
        passed_limit = kwargs.get("limit") or mock_svc.call_args.args[-1]
        assert passed_limit <= 100

    @pytest.mark.parametrize(
        "date_str",
        [
            "2024-01-01",
            "2024-01-01T00:00:00Z",
            "2024-01-01T00:00:00",
            "2024-01-01 00:00:00",
        ],
    )
    def test_historical_date_formats_accepted(self, client: TestClient, date_str: str):
        with patch(
            f"{_ROUTES}.get_positions_history",
            new_callable=AsyncMock,
            return_value=MOCK_HIST_POSITIONS_LIST,
        ):
            resp = client.get("/api/aave/positions", params={"date": date_str})
        assert resp.status_code == 200

    def test_historical_invalid_date_returns_400(self, client: TestClient):
        resp = client.get("/api/aave/positions", params={"date": "march-2025"})
        assert resp.status_code == 400

    def test_historical_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/aave/positions", params={"date": "2025-01-01"})
        assert resp.status_code == 503


class TestParseUtcTime:
    """直接测试路由层的日期解析辅助函数。"""

    def _call(self, time_str: str) -> int:
        from aave_crawler.api.routes import _parse_utc_time

        return _parse_utc_time(time_str)

    @pytest.mark.parametrize(
        "time_str,expected",
        [
            ("2025-01-01", 1735689600),
            ("2025-01-01T00:00:00Z", 1735689600),
            ("2025-01-01T00:00:00", 1735689600),
            ("2025-01-01 00:00:00", 1735689600),
        ],
    )
    def test_valid_formats(self, time_str: str, expected: int):
        assert self._call(time_str) == expected

    @pytest.mark.parametrize(
        "bad_str",
        [
            "not-a-date",
            "2025/01/01",
            "Jan 1 2025",
        ],
    )
    def test_invalid_raises_400(self, bad_str: str):
        with pytest.raises(HTTPException) as exc_info:
            self._call(bad_str)
        assert exc_info.value.status_code == 400
