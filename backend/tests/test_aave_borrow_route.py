from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from tests.fixtures.aave import (
    ADDR,
    MOCK_BORROW_POSITIONS_LIST,
    MOCK_BORROW_USER_POSITION,
    MOCK_SHORT_LIQ_PERIOD,
    MOCK_SHORT_SIM_EMPTY,
    MOCK_SHORT_SIM_RESPONSE,
)

_ROUTES = "aave_crawler.api.routes"


class TestBorrowPositions:
    """GET /api/aave/borrow/positions — 借贷端仓位列表（借入 WETH / 做空 ETH）。"""

    def test_default_ok(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_sorted_borrow_positions",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_POSITIONS_LIST,
        ):
            resp = client.get("/api/aave/borrow/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        item = data[0]
        assert "address" in item
        assert "weth_debt_amount" in item
        assert "weth_debt_usd" in item
        assert "total_collateral_usd" in item
        assert "total_debt_usd" in item
        assert "health_factor" in item
        assert "liq_price_rise" in item

    def test_empty_result(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_sorted_borrow_positions",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/aave/borrow/positions")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.skip(reason="路由已迁移至 DbSession，不再依赖 pool")
    def test_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/aave/borrow/positions")
        assert resp.status_code == 503

    @pytest.mark.parametrize(
        "orderby",
        ["liq_price_rise", "weth_debt_usd", "total_debt_usd", "health_factor"],
    )
    def test_valid_orderby_values(self, client: TestClient, orderby: str):
        with patch(
            f"{_ROUTES}.get_sorted_borrow_positions",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_POSITIONS_LIST,
        ):
            resp = client.get("/api/aave/borrow/positions", params={"orderby": orderby})
        assert resp.status_code == 200

    def test_invalid_orderby_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/borrow/positions", params={"orderby": "nonexistent_col"}
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("order", ["asc", "desc"])
    def test_valid_order_values(self, client: TestClient, order: str):
        with patch(
            f"{_ROUTES}.get_sorted_borrow_positions",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_POSITIONS_LIST,
        ):
            resp = client.get("/api/aave/borrow/positions", params={"order": order})
        assert resp.status_code == 200

    def test_invalid_order_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/borrow/positions", params={"order": "random"})
        assert resp.status_code == 422

    @pytest.mark.parametrize("limit", [1, 50, 200])
    def test_valid_limit_values(self, client: TestClient, limit: int):
        with patch(
            f"{_ROUTES}.get_sorted_borrow_positions",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_POSITIONS_LIST,
        ):
            resp = client.get("/api/aave/borrow/positions", params={"limit": limit})
        assert resp.status_code == 200

    def test_limit_too_large_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/borrow/positions", params={"limit": 201})
        assert resp.status_code == 422

    def test_limit_zero_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/borrow/positions", params={"limit": 0})
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "version,expected_protocol",
        [("v3", "v3_borrow"), ("v2", "v2_borrow")],
    )
    def test_version_maps_to_borrow_protocol(
        self, client: TestClient, version: str, expected_protocol: str
    ):
        with patch(
            f"{_ROUTES}.get_sorted_borrow_positions",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_POSITIONS_LIST,
        ) as mock_svc:
            client.get("/api/aave/borrow/positions", params={"version": version})
        _, kwargs = mock_svc.call_args
        assert kwargs["protocol"] == expected_protocol

    def test_service_receives_correct_params(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_sorted_borrow_positions",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_POSITIONS_LIST,
        ) as mock_svc:
            client.get(
                "/api/aave/borrow/positions",
                params={"orderby": "weth_debt_usd", "order": "desc", "limit": 50},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["orderby"] == "weth_debt_usd"
        assert kwargs["order"] == "desc"
        assert kwargs["limit"] == 50


class TestBorrowLiquidate:
    """GET /api/aave/borrow/liquidate — 模拟 ETH 上涨时的做空清算情况。"""

    def test_missing_eth_price_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/borrow/liquidate")
        assert resp.status_code == 422

    def test_eth_price_zero_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/borrow/liquidate", params={"eth_price": 0})
        assert resp.status_code == 422

    def test_eth_price_negative_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/borrow/liquidate", params={"eth_price": -100})
        assert resp.status_code == 422

    def test_ok_with_results(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_RESPONSE,
        ):
            resp = client.get("/api/aave/borrow/liquidate", params={"eth_price": 2700})
        assert resp.status_code == 200
        data = resp.json()
        assert "simulated_eth_price" in data
        assert "positions" in data
        assert "positions_cnt" in data
        assert "total_weth_debt_amount" in data
        assert "total_weth_debt_usd" in data
        assert "total_liquidation_usd" in data
        assert isinstance(data["positions"], list)
        item = data["positions"][0]
        assert "address" in item
        assert "liq_price_rise" in item
        assert "weth_debt_amount" in item
        assert "weth_debt_usd" in item
        assert "total_collateral_usd" in item

    def test_ok_empty_results(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_EMPTY,
        ):
            resp = client.get("/api/aave/borrow/liquidate", params={"eth_price": 1000})
        assert resp.status_code == 200
        data = resp.json()
        assert data["positions_cnt"] == "0"
        assert data["positions"] == []

    def test_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/aave/borrow/liquidate", params={"eth_price": 2700})
        assert resp.status_code == 503

    def test_service_receives_decimal_eth_price(self, client: TestClient):
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_RESPONSE,
        ) as mock_svc:
            client.get("/api/aave/borrow/liquidate", params={"eth_price": 2700.5})
        args, _ = mock_svc.call_args
        assert args[1] == Decimal("2700.5")

    @pytest.mark.parametrize(
        "orderby", ["liq_price_rise", "weth_debt_usd", "total_debt_usd"]
    )
    def test_valid_orderby_values(self, client: TestClient, orderby: str):
        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_RESPONSE,
        ):
            resp = client.get(
                "/api/aave/borrow/liquidate",
                params={"eth_price": 2700, "orderby": orderby},
            )
        assert resp.status_code == 200

    def test_invalid_orderby_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/borrow/liquidate",
            params={"eth_price": 2700, "orderby": "bad_col"},
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("limit", [1, 100, 1000])
    def test_valid_limit_values(self, client: TestClient, limit: int):
        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_RESPONSE,
        ):
            resp = client.get(
                "/api/aave/borrow/liquidate", params={"eth_price": 2700, "limit": limit}
            )
        assert resp.status_code == 200

    def test_limit_too_large_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/borrow/liquidate", params={"eth_price": 2700, "limit": 1001}
        )
        assert resp.status_code == 422

    def test_cap_passed_to_service(self, client: TestClient):
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_RESPONSE,
        ) as mock_svc:
            client.get(
                "/api/aave/borrow/liquidate", params={"eth_price": 2700, "cap": 3000}
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["cap"] == Decimal("3000")

    def test_no_cap_passes_none_to_service(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_RESPONSE,
        ) as mock_svc:
            client.get("/api/aave/borrow/liquidate", params={"eth_price": 2700})
        _, kwargs = mock_svc.call_args
        assert kwargs["cap"] is None

    def test_cap_zero_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/borrow/liquidate", params={"eth_price": 2700, "cap": 0}
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "version,expected_protocol",
        [("v3", "v3_borrow"), ("v2", "v2_borrow")],
    )
    def test_version_maps_to_borrow_protocol(
        self, client: TestClient, version: str, expected_protocol: str
    ):
        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_RESPONSE,
        ) as mock_svc:
            client.get(
                "/api/aave/borrow/liquidate",
                params={"eth_price": 2700, "version": version},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["protocol"] == expected_protocol

    def test_default_eth_ratio_is_0_45(self, client: TestClient):
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_RESPONSE,
        ) as mock_svc:
            client.get("/api/aave/borrow/liquidate", params={"eth_price": 2700})
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal("0.45")

    def test_custom_eth_ratio_passed_to_service(self, client: TestClient):
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_RESPONSE,
        ) as mock_svc:
            client.get(
                "/api/aave/borrow/liquidate",
                params={"eth_price": 2700, "eth_ratio": 0.8},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal("0.8")

    def test_eth_ratio_zero_passes_to_service(self, client: TestClient):
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_RESPONSE,
        ) as mock_svc:
            client.get(
                "/api/aave/borrow/liquidate", params={"eth_price": 2700, "eth_ratio": 0}
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal("0")

    def test_eth_ratio_greater_than_1_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/borrow/liquidate", params={"eth_price": 2700, "eth_ratio": 1.1}
        )
        assert resp.status_code == 422

    def test_eth_ratio_negative_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/borrow/liquidate", params={"eth_price": 2700, "eth_ratio": -0.1}
        )
        assert resp.status_code == 422


class TestBorrowLiquidatePeriod:
    """GET /api/aave/borrow/liquidate/period — ETH 上涨区间内的做空清算分布。"""

    _BASE_PARAMS = {"start": 2000, "end": 3000, "interval": 500}

    def test_ok(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_short_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_LIQ_PERIOD,
        ):
            resp = client.get(
                "/api/aave/borrow/liquidate/period", params=self._BASE_PARAMS
            )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 3
        item = data[0]
        assert "simulated_eth_price" in item
        assert "positions_cnt" in item
        assert "total_weth_debt_amount" in item
        assert "total_weth_debt_usd" in item
        assert "total_liquidation_usd" in item

    def test_empty_result_returns_empty_list(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_short_liquidation_period",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get(
                "/api/aave/borrow/liquidate/period", params=self._BASE_PARAMS
            )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/aave/borrow/liquidate/period", params=self._BASE_PARAMS)
        assert resp.status_code == 503

    def test_missing_start_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/borrow/liquidate/period", params={"end": 3000, "interval": 500}
        )
        assert resp.status_code == 422

    def test_missing_end_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/borrow/liquidate/period", params={"start": 2000, "interval": 500}
        )
        assert resp.status_code == 422

    def test_missing_interval_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/borrow/liquidate/period", params={"start": 2000, "end": 3000}
        )
        assert resp.status_code == 422

    def test_start_zero_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/borrow/liquidate/period",
            params={"start": 0, "end": 3000, "interval": 500},
        )
        assert resp.status_code == 422

    def test_interval_zero_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/borrow/liquidate/period",
            params={"start": 2000, "end": 3000, "interval": 0},
        )
        assert resp.status_code == 422

    def test_start_greater_than_end_returns_400(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_short_liquidation_period",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=400, detail="start 必须 <= end"),
        ):
            resp = client.get(
                "/api/aave/borrow/liquidate/period",
                params={"start": 4000, "end": 2000, "interval": 500},
            )
        assert resp.status_code == 400

    def test_service_receives_correct_decimal_params(self, client: TestClient):
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_short_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_LIQ_PERIOD,
        ) as mock_svc:
            client.get("/api/aave/borrow/liquidate/period", params=self._BASE_PARAMS)
        _, kwargs = mock_svc.call_args
        assert kwargs["start_price"] == Decimal("2000")
        assert kwargs["end_price"] == Decimal("3000")
        assert kwargs["interval"] == Decimal("500")

    @pytest.mark.parametrize(
        "version,expected_protocol",
        [("v3", "v3_borrow"), ("v2", "v2_borrow")],
    )
    def test_version_maps_to_borrow_protocol(
        self, client: TestClient, version: str, expected_protocol: str
    ):
        with patch(
            f"{_ROUTES}.simulate_short_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_LIQ_PERIOD,
        ) as mock_svc:
            client.get(
                "/api/aave/borrow/liquidate/period",
                params={**self._BASE_PARAMS, "version": version},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["protocol"] == expected_protocol

    def test_invalid_version_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/borrow/liquidate/period",
            params={**self._BASE_PARAMS, "version": "v4"},
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("interval", [100, 500, 1000])
    def test_various_intervals(self, client: TestClient, interval: int):
        with patch(
            f"{_ROUTES}.simulate_short_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_LIQ_PERIOD,
        ):
            resp = client.get(
                "/api/aave/borrow/liquidate/period",
                params={"start": 2000, "end": 3000, "interval": interval},
            )
        assert resp.status_code == 200

    def test_default_eth_ratio_is_0_45(self, client: TestClient):
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_short_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_LIQ_PERIOD,
        ) as mock_svc:
            client.get("/api/aave/borrow/liquidate/period", params=self._BASE_PARAMS)
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal("0.45")

    def test_custom_eth_ratio_passed_to_service(self, client: TestClient):
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_short_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_LIQ_PERIOD,
        ) as mock_svc:
            client.get(
                "/api/aave/borrow/liquidate/period",
                params={**self._BASE_PARAMS, "eth_ratio": 0.7},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal("0.7")

    def test_eth_ratio_zero_passes_to_service(self, client: TestClient):
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_short_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_LIQ_PERIOD,
        ) as mock_svc:
            client.get(
                "/api/aave/borrow/liquidate/period",
                params={**self._BASE_PARAMS, "eth_ratio": 0},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal("0")

    def test_eth_ratio_greater_than_1_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/borrow/liquidate/period",
            params={**self._BASE_PARAMS, "eth_ratio": 1.5},
        )
        assert resp.status_code == 422

    def test_eth_ratio_negative_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/borrow/liquidate/period",
            params={**self._BASE_PARAMS, "eth_ratio": -0.1},
        )
        assert resp.status_code == 422


class TestBorrowUserPosition:
    """测试 GET /api/aave/borrow/position。"""

    _URL = "/api/aave/borrow/position"

    def test_ok_returns_200_with_all_fields(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_borrow_user_position",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_USER_POSITION,
        ):
            resp = client.get(self._URL, params={"address": ADDR})
        assert resp.status_code == 200
        data = resp.json()
        for field in (
            "address",
            "scanned_at",
            "weth_debt_amount",
            "weth_debt_usd",
            "health_factor",
            "liq_price_rise",
            "reserves",
        ):
            assert field in data, f"缺少字段: {field}"
        for field in (
            "total_collateral_usd",
            "total_debt_usd",
            "available_borrows_usd",
            "ltv",
            "liq_threshold",
            "liq_price",
        ):
            assert field not in data, f"不应包含重合字段: {field}"

    def test_ok_reserves_is_list(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_borrow_user_position",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_USER_POSITION,
        ):
            resp = client.get(self._URL, params={"address": ADDR})
        data = resp.json()
        assert isinstance(data["reserves"], list)
        assert len(data["reserves"]) == 2

    def test_ok_reserve_fields(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_borrow_user_position",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_USER_POSITION,
        ):
            resp = client.get(self._URL, params={"address": ADDR})
        reserve = resp.json()["reserves"][0]
        for field in (
            "symbol",
            "token_address",
            "price_usd",
            "supply_amount",
            "supply_usd",
            "stable_debt_amount",
            "variable_debt_amount",
            "total_debt_amount",
            "total_debt_usd",
            "use_as_collateral",
        ):
            assert field in reserve, f"reserve 缺少字段: {field}"

    def test_address_not_found_returns_404(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_borrow_user_position",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(self._URL, params={"address": ADDR})
        assert resp.status_code == 404

    def test_404_detail_contains_address(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_borrow_user_position",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(self._URL, params={"address": ADDR})
        assert (
            ADDR.lower() in resp.json()["detail"].lower()
            or ADDR in resp.json()["detail"]
        )

    def test_missing_address_returns_422(self, client: TestClient):
        resp = client.get(self._URL)
        assert resp.status_code == 422

    def test_no_pool_returns_503(self, app_no_pool: FastAPI):
        with TestClient(app_no_pool) as c:
            resp = c.get(self._URL, params={"address": ADDR})
        assert resp.status_code == 503

    @pytest.mark.parametrize(
        "version,expected_protocol",
        [("v3", "v3_borrow"), ("v2", "v2_borrow")],
    )
    def test_version_maps_to_borrow_protocol(
        self, client: TestClient, version: str, expected_protocol: str
    ):
        with patch(
            f"{_ROUTES}.get_borrow_user_position",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_USER_POSITION,
        ) as mock_svc:
            client.get(self._URL, params={"address": ADDR, "version": version})
        _, kwargs = mock_svc.call_args
        assert kwargs["protocol"] == expected_protocol

    def test_invalid_version_returns_422(self, client: TestClient):
        resp = client.get(self._URL, params={"address": ADDR, "version": "v4"})
        assert resp.status_code == 422

    def test_address_passed_to_service(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_borrow_user_position",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_USER_POSITION,
        ) as mock_svc:
            client.get(self._URL, params={"address": ADDR})
        args, _ = mock_svc.call_args
        assert args[1] == ADDR

    def test_values_match_mock(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_borrow_user_position",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_USER_POSITION,
        ):
            resp = client.get(self._URL, params={"address": ADDR})
        data = resp.json()
        assert data["address"] == ADDR
        assert data["weth_debt_amount"] == "10.000000"
        assert data["weth_debt_usd"] == "18740.00"
        assert data["liq_price_rise"] == "2600.00"
        assert data["health_factor"] == "1.1200"
        assert data["scanned_at"] == "2026-02-28T08:00:00Z"
