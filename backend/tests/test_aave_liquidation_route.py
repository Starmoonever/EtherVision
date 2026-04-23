from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from tests.fixtures.aave import (
    ADDR,
    MOCK_LIQ_PERIOD,
    MOCK_SIM_EMPTY,
    MOCK_SIM_RESPONSE,
    MOCK_WATERFALL_RESPONSE,
)

_ROUTES = "aave_crawler.api.routes"


class TestLiquidateSimulation:
    """GET /api/aave/liquidate — 必须参数 eth_price，返回模拟清算结果。"""

    def test_missing_eth_price_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/liquidate")
        assert resp.status_code == 422

    def test_eth_price_zero_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/liquidate", params={"eth_price": 0})
        assert resp.status_code == 422

    def test_eth_price_negative_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/liquidate", params={"eth_price": -100})
        assert resp.status_code == 422

    def test_eth_price_string_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/liquidate", params={"eth_price": "abc"})
        assert resp.status_code == 422

    def test_normal_ok_with_positions(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_RESPONSE,
        ):
            resp = client.get("/api/aave/liquidate", params={"eth_price": 1500})
        assert resp.status_code == 200
        data = resp.json()
        assert data["simulated_eth_price"] == "1500.00"
        assert isinstance(data["positions"], list)
        assert len(data["positions"]) == 1
        assert data["positions"][0]["address"] == ADDR
        assert "liq_price" in data["positions"][0]
        assert "eth_collateral_amount" in data["positions"][0]
        assert "eth_collateral_usd" in data["positions"][0]
        assert "total_debt_usd" in data["positions"][0]
        assert "total_eth_collateral_amount" in data
        assert "total_eth_collateral_usd" in data
        assert "total_liquidation_usd" in data

    def test_no_positions_below_price(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ):
            resp = client.get("/api/aave/liquidate", params={"eth_price": 100})
        assert resp.status_code == 200
        data = resp.json()
        assert data["positions"] == []
        assert data["total_eth_collateral_usd"] == "0.00"
        assert data["total_liquidation_usd"] == "0.00"

    @pytest.mark.parametrize("eth_price", [1.0, 100.5, 1500, 3000.99, 10000])
    def test_various_eth_prices_accepted(self, client: TestClient, eth_price: float):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ):
            resp = client.get("/api/aave/liquidate", params={"eth_price": eth_price})
        assert resp.status_code == 200

    def test_total_liquidation_lte_total_collateral(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_RESPONSE,
        ):
            resp = client.get("/api/aave/liquidate", params={"eth_price": 1500})
        data = resp.json()
        total_liq = float(data["total_liquidation_usd"])
        total_col = float(data["total_eth_collateral_usd"])
        assert isinstance(total_liq, float)
        assert isinstance(total_col, float)

    def test_note_field_present(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_RESPONSE,
        ):
            resp = client.get("/api/aave/liquidate", params={"eth_price": 1500})
        assert "note" in resp.json()

    @pytest.mark.skip(reason="路由已迁移至 DbSession，不再依赖 pool")
    def test_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/aave/liquidate", params={"eth_price": 1500})
        assert resp.status_code == 503

    @pytest.mark.parametrize("limit", [1, 10, 100, 500, 1000])
    def test_limit_valid_values(self, client: TestClient, limit: int):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ):
            resp = client.get(
                "/api/aave/liquidate", params={"eth_price": 1500, "limit": limit}
            )
        assert resp.status_code == 200

    def test_limit_zero_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/liquidate", params={"eth_price": 1500, "limit": 0})
        assert resp.status_code == 422

    def test_limit_over_max_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate", params={"eth_price": 1500, "limit": 1001}
        )
        assert resp.status_code == 422

    def test_limit_passed_to_service(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ) as mock_svc:
            client.get("/api/aave/liquidate", params={"eth_price": 1500, "limit": 42})
        _, kwargs = mock_svc.call_args
        assert kwargs["limit"] == 42

    @pytest.mark.parametrize(
        "orderby",
        ["liq_price", "eth_collateral_amount", "eth_collateral_usd", "total_debt_usd"],
    )
    def test_orderby_valid_values(self, client: TestClient, orderby: str):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ):
            resp = client.get(
                "/api/aave/liquidate", params={"eth_price": 1500, "orderby": orderby}
            )
        assert resp.status_code == 200

    def test_orderby_invalid_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate", params={"eth_price": 1500, "orderby": "address"}
        )
        assert resp.status_code == 422

    def test_orderby_passed_to_service(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ) as mock_svc:
            client.get(
                "/api/aave/liquidate",
                params={"eth_price": 1500, "orderby": "total_debt_usd"},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["orderby"] == "total_debt_usd"

    @pytest.mark.parametrize("order", ["asc", "desc"])
    def test_order_valid_values(self, client: TestClient, order: str):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ):
            resp = client.get(
                "/api/aave/liquidate", params={"eth_price": 1500, "order": order}
            )
        assert resp.status_code == 200

    def test_order_invalid_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate", params={"eth_price": 1500, "order": "random"}
        )
        assert resp.status_code == 422

    def test_order_passed_to_service(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ) as mock_svc:
            client.get(
                "/api/aave/liquidate", params={"eth_price": 1500, "order": "asc"}
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["order"] == "asc"

    def test_defaults_orderby_liq_price_desc(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ) as mock_svc:
            client.get("/api/aave/liquidate", params={"eth_price": 1500})
        _, kwargs = mock_svc.call_args
        assert kwargs["orderby"] == "liq_price"
        assert kwargs["order"] == "desc"
        assert kwargs["limit"] == 100

    def test_eth_ratio_passed_to_service(self, client: TestClient):
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ) as mock_svc:
            client.get(
                "/api/aave/liquidate", params={"eth_price": 1500, "eth_ratio": 0.9}
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal("0.9")

    def test_default_eth_ratio_is_constant(self, client: TestClient):
        from decimal import Decimal
        from aave_crawler.api.constants import ETH_COLLATERAL_RATIO_MIN

        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ) as mock_svc:
            client.get("/api/aave/liquidate", params={"eth_price": 1500})
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal(str(ETH_COLLATERAL_RATIO_MIN))

    def test_eth_ratio_out_of_range_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate", params={"eth_price": 1500, "eth_ratio": 1.5}
        )
        assert resp.status_code == 422

    def test_eth_ratio_negative_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate", params={"eth_price": 1500, "eth_ratio": -0.1}
        )
        assert resp.status_code == 422


class TestLiquidateWaterfall:
    """GET /api/aave/liquidate/waterfall — 日级仓位瀑布模拟（第二阶段）。"""

    def test_missing_initial_shock_returns_422(self, client: TestClient):
        resp = client.get("/api/aave/liquidate/waterfall")
        assert resp.status_code == 422

    def test_ok_returns_response(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation_waterfall",
            new_callable=AsyncMock,
            return_value=MOCK_WATERFALL_RESPONSE,
        ):
            resp = client.get(
                "/api/aave/liquidate/waterfall",
                params={"initial_price_shock_eth": 0.05},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["initial_decline"] == "0.05000000"
        assert data["cascade_decline"] == "0.00000000"
        assert data["liquidation_turns_cnt"] == "1"
        assert isinstance(data["liquidation_turns"], list)
        assert data["liquidation_turns"][0]["eth_price"] == "2400.0000"

    def test_initial_shock_out_of_range_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate/waterfall",
            params={"initial_price_shock_eth": 1.0},
        )
        assert resp.status_code == 422

    def test_impact_k_negative_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate/waterfall",
            params={"initial_price_shock_eth": 0.05, "impact_k": -0.1},
        )
        assert resp.status_code == 422

    def test_sell_partition_out_of_range_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate/waterfall",
            params={"initial_price_shock_eth": 0.05, "sell_partition_eth": 1.1},
        )
        assert resp.status_code == 422

    def test_date_invalid_returns_400(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate/waterfall",
            params={"initial_price_shock_eth": 0.05, "date": "2026/01/01"},
        )
        assert resp.status_code == 400

    def test_params_passed_to_service(self, client: TestClient):
        from datetime import date
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_liquidation_waterfall",
            new_callable=AsyncMock,
            return_value=MOCK_WATERFALL_RESPONSE,
        ) as mock_svc:
            client.get(
                "/api/aave/liquidate/waterfall",
                params={
                    "version": "v3",
                    "initial_price_shock_eth": 0.08,
                    "date": "2026-03-19",
                    "impact_k": 0.7,
                    "sell_partition_eth": 0.4,
                },
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["protocol"] == "v3"
        assert kwargs["snapshot_date"] == date(2026, 3, 19)
        assert kwargs["initial_price_shock_eth"] == Decimal("0.08")
        assert kwargs["impact_k"] == Decimal("0.7")
        assert kwargs["sell_partition_eth"] == Decimal("0.4")


class TestLiquidatePeriod:
    """GET /api/aave/liquidate/period — ETH 价格区间清算汇总序列。"""

    _BASE_PARAMS = {"start": 1000, "end": 2000, "interval": 500}

    def test_ok_returns_list(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_LIQ_PERIOD,
        ):
            resp = client.get("/api/aave/liquidate/period", params=self._BASE_PARAMS)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 3
        item = data[0]
        assert "simulated_eth_price" in item
        assert "positions_cnt" in item
        assert "total_eth_collateral_amount" in item
        assert "total_eth_collateral_usd" in item
        assert "total_liquidation_usd" in item

    def test_service_receives_correct_params(self, client: TestClient):
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_LIQ_PERIOD,
        ) as mock_svc:
            client.get("/api/aave/liquidate/period", params=self._BASE_PARAMS)
        _, kwargs = mock_svc.call_args
        assert kwargs["start_price"] == Decimal("1000")
        assert kwargs["end_price"] == Decimal("2000")
        assert kwargs["interval"] == Decimal("500")

    def test_missing_start_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate/period", params={"end": 2000, "interval": 500}
        )
        assert resp.status_code == 422

    def test_missing_end_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate/period", params={"start": 1000, "interval": 500}
        )
        assert resp.status_code == 422

    def test_missing_interval_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate/period", params={"start": 1000, "end": 2000}
        )
        assert resp.status_code == 422

    def test_start_zero_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate/period",
            params={"start": 0, "end": 2000, "interval": 500},
        )
        assert resp.status_code == 422

    def test_interval_zero_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate/period",
            params={"start": 1000, "end": 2000, "interval": 0},
        )
        assert resp.status_code == 422

    def test_start_greater_than_end_returns_400(self, client: TestClient):
        from fastapi import HTTPException

        with patch(
            f"{_ROUTES}.simulate_liquidation_period",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=400, detail="start 必须 <= end"),
        ):
            resp = client.get(
                "/api/aave/liquidate/period",
                params={"start": 3000, "end": 1000, "interval": 500},
            )
        assert resp.status_code == 400

    def test_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/aave/liquidate/period", params=self._BASE_PARAMS)
        assert resp.status_code == 503

    def test_empty_result_returns_empty_list(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation_period",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/aave/liquidate/period", params=self._BASE_PARAMS)
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.parametrize("interval", [100, 500, 1000])
    def test_various_intervals(self, client: TestClient, interval: int):
        with patch(
            f"{_ROUTES}.simulate_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_LIQ_PERIOD,
        ):
            resp = client.get(
                "/api/aave/liquidate/period",
                params={"start": 500, "end": 3000, "interval": interval},
            )
        assert resp.status_code == 200

    def test_eth_ratio_passed_to_service(self, client: TestClient):
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_LIQ_PERIOD,
        ) as mock_svc:
            client.get(
                "/api/aave/liquidate/period",
                params={"start": 1000, "end": 2000, "interval": 500, "eth_ratio": 0.6},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal("0.6")

    def test_default_eth_ratio_is_constant(self, client: TestClient):
        from decimal import Decimal
        from aave_crawler.api.constants import ETH_COLLATERAL_RATIO_MIN

        with patch(
            f"{_ROUTES}.simulate_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_LIQ_PERIOD,
        ) as mock_svc:
            client.get("/api/aave/liquidate/period", params=self._BASE_PARAMS)
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal(str(ETH_COLLATERAL_RATIO_MIN))

    def test_eth_ratio_out_of_range_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate/period",
            params={"start": 1000, "end": 2000, "interval": 500, "eth_ratio": 1.5},
        )
        assert resp.status_code == 422

    def test_eth_ratio_negative_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/aave/liquidate/period",
            params={"start": 1000, "end": 2000, "interval": 500, "eth_ratio": -0.1},
        )
        assert resp.status_code == 422
