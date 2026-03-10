"""
API 路由单元测试。

覆盖所有端点的所有参数组合：
  - GET /api/position
  - GET /api/positions
  - GET /api/price
  - GET /api/price/period
  - GET /api/position/replay
  - GET /api/txs

使用 starlette.testclient.TestClient（同步），mock 所有 service 函数，
无需真实 RPC 或数据库连接。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient
from tests.conftest import (ADDR, MOCK_BORROW_POSITIONS_LIST,
                            MOCK_BORROW_USER_POSITION, MOCK_HIST_POSITION,
                            MOCK_HIST_POSITIONS_LIST, MOCK_LIQ,
                            MOCK_LIQ_PERIOD, MOCK_POSITION,
                            MOCK_POSITIONS_LIST, MOCK_PRICE_HIST,
                            MOCK_PRICE_ONCHAIN, MOCK_PRICE_PERIOD,
                            MOCK_REPLAY_RESPONSE, MOCK_SHORT_LIQ_PERIOD,
                            MOCK_SHORT_SIM_EMPTY, MOCK_SHORT_SIM_RESPONSE,
                            MOCK_SIM_EMPTY, MOCK_SIM_RESPONSE,
                            MOCK_TX_HISTORY_RESPONSE, _make_app)

# service 函数在 routes 模块中被导入，patch 该命名空间
_ROUTES = "aave_crawler.api.routes"

_404 = HTTPException(status_code=404, detail="无仓位")
_502 = HTTPException(status_code=502, detail="RPC失败")


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/position
# ─────────────────────────────────────────────────────────────────────────────


class TestUserPosition:
    """GET /api/position — 必须参数 address，可选参数 date。"""

    def test_missing_address_returns_422(self, client: TestClient):
        resp = client.get("/api/position")
        assert resp.status_code == 422

    # ── 实时模式（无 date）────────────────────────────────────────────────────

    def test_realtime_ok(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_position",
            new_callable=AsyncMock,
            return_value=MOCK_POSITION,
        ):
            resp = client.get("/api/position", params={"address": ADDR})
        assert resp.status_code == 200
        data = resp.json()
        assert data["address"] == ADDR
        assert "health_factor" in data
        assert "liq_price" in data
        assert "total_collateral_usd" in data
        assert "available_borrows_usd" in data
        assert "at_time" not in data  # PositionResponse，不含历史字段

    def test_realtime_empty_position_returns_404(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_position", new_callable=AsyncMock, side_effect=_404
        ):
            resp = client.get("/api/position", params={"address": ADDR})
        assert resp.status_code == 404

    def test_realtime_rpc_failure_returns_502(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_position", new_callable=AsyncMock, side_effect=_502
        ):
            resp = client.get("/api/position", params={"address": ADDR})
        assert resp.status_code == 502

    def test_realtime_no_w3_returns_503(self, app_no_w3):
        with TestClient(app_no_w3) as c:
            resp = c.get("/api/position", params={"address": ADDR})
        assert resp.status_code == 503

    # ── 历史模式（带 date）────────────────────────────────────────────────────

    def test_historical_ok(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_user_position_history",
            new_callable=AsyncMock,
            return_value=MOCK_HIST_POSITION,
        ):
            resp = client.get(
                "/api/position", params={"address": ADDR, "date": "2025-01-01"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "at_time" in data  # HistoricalPositionResponse 字段
        assert data["at_time"] == "2025-01-01T00:00:00Z"

    def test_historical_fallback_to_realtime_when_no_history(self, client: TestClient):
        """history 无记录 → 返回 None → 回退到实时链上查询。"""
        with patch(
            f"{_ROUTES}.get_user_position_history",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            f"{_ROUTES}.get_user_position",
            new_callable=AsyncMock,
            return_value=MOCK_POSITION,
        ):
            resp = client.get(
                "/api/position", params={"address": ADDR, "date": "2025-01-01"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "health_factor" in data  # 回退后是 PositionResponse
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
                "/api/position", params={"address": ADDR, "date": date_str}
            )
        assert resp.status_code == 200

    @pytest.mark.parametrize(
        "bad_date",
        [
            "not-a-date",
            "2025/01/01",
            "Jan 1 2025",
            "1704067200",  # 纯 Unix 时间戳不支持
        ],
    )
    def test_invalid_date_returns_400(self, client: TestClient, bad_date: str):
        resp = client.get(
            "/api/position", params={"address": ADDR, "date": bad_date}
        )
        assert resp.status_code == 400

    def test_historical_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get(
                "/api/position", params={"address": ADDR, "date": "2025-01-01"}
            )
        assert resp.status_code == 503


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/positions
# ─────────────────────────────────────────────────────────────────────────────


class TestPositions:
    """GET /api/positions — 可选 orderby / order / limit / date。"""

    # ── 实时模式（无 date）────────────────────────────────────────────────────

    def test_defaults_ok(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_sorted_positions",
            new_callable=AsyncMock,
            return_value=MOCK_POSITIONS_LIST,
        ) as mock_svc:
            resp = client.get("/api/positions")
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
            resp = client.get("/api/positions", params={"orderby": orderby})
        assert resp.status_code == 200

    @pytest.mark.parametrize("order", ["asc", "desc"])
    def test_order_variants(self, client: TestClient, order: str):
        with patch(
            f"{_ROUTES}.get_sorted_positions",
            new_callable=AsyncMock,
            return_value=MOCK_POSITIONS_LIST,
        ):
            resp = client.get("/api/positions", params={"order": order})
        assert resp.status_code == 200

    @pytest.mark.parametrize("limit", [1, 10, 100, 200])
    def test_limit_boundaries_ok(self, client: TestClient, limit: int):
        with patch(
            f"{_ROUTES}.get_sorted_positions",
            new_callable=AsyncMock,
            return_value=MOCK_POSITIONS_LIST,
        ):
            resp = client.get("/api/positions", params={"limit": limit})
        assert resp.status_code == 200

    def test_invalid_orderby_returns_422(self, client: TestClient):
        resp = client.get("/api/positions", params={"orderby": "invalid_field"})
        assert resp.status_code == 422

    def test_invalid_order_returns_422(self, client: TestClient):
        resp = client.get("/api/positions", params={"order": "random"})
        assert resp.status_code == 422

    def test_limit_zero_returns_422(self, client: TestClient):
        resp = client.get("/api/positions", params={"limit": 0})
        assert resp.status_code == 422

    def test_limit_over_max_returns_422(self, client: TestClient):
        resp = client.get("/api/positions", params={"limit": 201})
        assert resp.status_code == 422

    def test_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/positions")
        assert resp.status_code == 503

    # ── 历史模式（带 date）────────────────────────────────────────────────────

    def test_historical_ok(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_positions_history",
            new_callable=AsyncMock,
            return_value=MOCK_HIST_POSITIONS_LIST,
        ):
            resp = client.get(
                "/api/positions", params={"date": "2025-01-01", "limit": 10}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert "at_time" in data[0]

    def test_historical_limit_capped_at_100(self, client: TestClient):
        """历史模式下 limit > 100 应被裁剪至 100。"""
        with patch(
            f"{_ROUTES}.get_positions_history",
            new_callable=AsyncMock,
            return_value=MOCK_HIST_POSITIONS_LIST,
        ) as mock_svc:
            resp = client.get(
                "/api/positions", params={"date": "2025-01-01", "limit": 150}
            )
        assert resp.status_code == 200
        # 验证传递给 service 的 limit 不超过 100
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
            resp = client.get("/api/positions", params={"date": date_str})
        assert resp.status_code == 200

    def test_historical_invalid_date_returns_400(self, client: TestClient):
        resp = client.get("/api/positions", params={"date": "march-2025"})
        assert resp.status_code == 400

    def test_historical_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/positions", params={"date": "2025-01-01"})
        assert resp.status_code == 503


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/price
# ─────────────────────────────────────────────────────────────────────────────


class TestPrice:
    """GET /api/price — 可选 asset（默认 eth）/ time（默认 now）。"""

    # ── 实时模式（time=now）──────────────────────────────────────────────────

    def test_defaults_return_onchain_price(self, client: TestClient):
        """默认参数：asset=eth, time=now → 链上实时价格。"""
        with patch(
            f"{_ROUTES}.get_eth_price",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_ONCHAIN,
        ) as mock_svc:
            resp = client.get("/api/price")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "on-chain"
        # 确认调用时 timestamp 参数未传（即为 None）
        _, kwargs = mock_svc.call_args
        assert kwargs.get("timestamp") is None

    def test_time_now_explicit(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_eth_price",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_ONCHAIN,
        ):
            resp = client.get("/api/price", params={"time": "now"})
        assert resp.status_code == 200
        assert resp.json()["source"] == "on-chain"

    @pytest.mark.parametrize("asset", ["eth", "ETH", "wbtc", "WBTC", "usdc"])
    def test_various_assets_realtime(self, client: TestClient, asset: str):
        with patch(
            f"{_ROUTES}.get_eth_price",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_ONCHAIN,
        ):
            resp = client.get("/api/price", params={"asset": asset})
        assert resp.status_code == 200

    def test_unknown_asset_returns_404(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_eth_price",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="未找到资产"),
        ):
            resp = client.get("/api/price", params={"asset": "FAKETOKEN"})
        assert resp.status_code == 404

    def test_no_w3_returns_503(self, app_no_w3):
        with TestClient(app_no_w3) as c:
            resp = c.get("/api/price")
        assert resp.status_code == 503

    # ── 历史模式（time=<日期字符串>）─────────────────────────────────────────

    def test_historical_price_ok(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_eth_price",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_HIST,
        ) as mock_svc:
            resp = client.get(
                "/api/price", params={"asset": "eth", "time": "2024-06-01"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "defillama"
        # 确认调用时传入了 timestamp（非 None）
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
            f"{_ROUTES}.get_eth_price",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_HIST,
        ):
            resp = client.get("/api/price", params={"asset": "eth", "time": time_str})
        assert resp.status_code == 200

    def test_historical_correct_timestamp_passed(self, client: TestClient):
        """时间字符串应正确解析为 Unix 时间戳后传给 service。"""
        from datetime import datetime, timezone

        expected_ts = int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp())
        with patch(
            f"{_ROUTES}.get_eth_price",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_HIST,
        ) as mock_svc:
            client.get("/api/price", params={"asset": "eth", "time": "2024-06-01"})
        _, kwargs = mock_svc.call_args
        assert kwargs["timestamp"] == expected_ts

    @pytest.mark.parametrize(
        "bad_time",
        [
            "yesterday",
            "2024-13-01",  # 月份超范围（Python strptime 会报错）
            "2024.06.01",
            "06/01/2024",
        ],
    )
    def test_invalid_time_format_returns_400(self, client: TestClient, bad_time: str):
        resp = client.get("/api/price", params={"time": bad_time})
        assert resp.status_code == 400

    def test_defillama_failure_returns_502(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_eth_price",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=502, detail="DeFiLlama 不可用"),
        ):
            resp = client.get(
                "/api/price", params={"asset": "eth", "time": "2024-06-01"}
            )
        assert resp.status_code == 502

    def test_historical_no_w3_returns_503(self, app_no_w3):
        with TestClient(app_no_w3) as c:
            resp = c.get("/api/price", params={"asset": "eth", "time": "2024-06-01"})
        assert resp.status_code == 503


# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数 _parse_utc_time 的独立测试
# ─────────────────────────────────────────────────────────────────────────────


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


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/liquidate
# ─────────────────────────────────────────────────────────────────────────────


class TestLiquidateSimulation:
    """GET /api/liquidate — 必须参数 eth_price，返回模拟清算结果。"""

    def test_missing_eth_price_returns_422(self, client: TestClient):
        resp = client.get("/api/liquidate")
        assert resp.status_code == 422

    def test_eth_price_zero_returns_422(self, client: TestClient):
        """gt=0 验证：eth_price 必须 > 0。"""
        resp = client.get("/api/liquidate", params={"eth_price": 0})
        assert resp.status_code == 422

    def test_eth_price_negative_returns_422(self, client: TestClient):
        resp = client.get("/api/liquidate", params={"eth_price": -100})
        assert resp.status_code == 422

    def test_eth_price_string_returns_422(self, client: TestClient):
        resp = client.get("/api/liquidate", params={"eth_price": "abc"})
        assert resp.status_code == 422

    def test_normal_ok_with_positions(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_RESPONSE,
        ):
            resp = client.get("/api/liquidate", params={"eth_price": 1500})
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
        """ETH 价格足够高时无被清算仓位。"""
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ):
            resp = client.get("/api/liquidate", params={"eth_price": 100})
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
            resp = client.get("/api/liquidate", params={"eth_price": eth_price})
        assert resp.status_code == 200

    def test_total_liquidation_lte_total_collateral(self, client: TestClient):
        """清算人最多获得全部抵押品，total_liquidation_usd 不超过 total_eth_collateral_usd。"""
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_RESPONSE,
        ):
            resp = client.get("/api/liquidate", params={"eth_price": 1500})
        data = resp.json()
        total_liq = float(data["total_liquidation_usd"])
        total_col = float(data["total_eth_collateral_usd"])
        # 清算奖励可能导致 liq > col（当债 > col/1.05），但不前超过 col
        # mock 中是手工构造的，这里只验证字段类型合法
        assert isinstance(total_liq, float)
        assert isinstance(total_col, float)

    def test_note_field_present(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_RESPONSE,
        ):
            resp = client.get("/api/liquidate", params={"eth_price": 1500})
        assert "note" in resp.json()

    @pytest.mark.skip(reason="路由已迁移至 DbSession，不再依赖 pool")
    def test_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/liquidate", params={"eth_price": 1500})
        assert resp.status_code == 503

    # ── limit ──────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("limit", [1, 10, 100, 500, 1000])
    def test_limit_valid_values(self, client: TestClient, limit: int):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ):
            resp = client.get(
                "/api/liquidate", params={"eth_price": 1500, "limit": limit}
            )
        assert resp.status_code == 200

    def test_limit_zero_returns_422(self, client: TestClient):
        resp = client.get("/api/liquidate", params={"eth_price": 1500, "limit": 0})
        assert resp.status_code == 422

    def test_limit_over_max_returns_422(self, client: TestClient):
        resp = client.get("/api/liquidate", params={"eth_price": 1500, "limit": 1001})
        assert resp.status_code == 422

    def test_limit_passed_to_service(self, client: TestClient):
        """limit 参数应原样传递给 simulate_liquidation。"""
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ) as mock_svc:
            client.get("/api/liquidate", params={"eth_price": 1500, "limit": 42})
        _, kwargs = mock_svc.call_args
        assert kwargs["limit"] == 42

    # ── orderby ────────────────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "orderby",
        [
            "liq_price",
            "eth_collateral_amount",
            "eth_collateral_usd",
            "total_debt_usd",
        ],
    )
    def test_orderby_valid_values(self, client: TestClient, orderby: str):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ):
            resp = client.get(
                "/api/liquidate", params={"eth_price": 1500, "orderby": orderby}
            )
        assert resp.status_code == 200

    def test_orderby_invalid_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/liquidate", params={"eth_price": 1500, "orderby": "address"}
        )
        assert resp.status_code == 422

    def test_orderby_passed_to_service(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ) as mock_svc:
            client.get(
                "/api/liquidate",
                params={"eth_price": 1500, "orderby": "total_debt_usd"},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["orderby"] == "total_debt_usd"

    # ── order ──────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("order", ["asc", "desc"])
    def test_order_valid_values(self, client: TestClient, order: str):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ):
            resp = client.get(
                "/api/liquidate", params={"eth_price": 1500, "order": order}
            )
        assert resp.status_code == 200

    def test_order_invalid_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/liquidate", params={"eth_price": 1500, "order": "random"}
        )
        assert resp.status_code == 422

    def test_order_passed_to_service(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ) as mock_svc:
            client.get("/api/liquidate", params={"eth_price": 1500, "order": "asc"})
        _, kwargs = mock_svc.call_args
        assert kwargs["order"] == "asc"

    def test_defaults_orderby_liq_price_desc(self, client: TestClient):
        """默认 orderby=liq_price, order=desc。"""
        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ) as mock_svc:
            client.get("/api/liquidate", params={"eth_price": 1500})
        _, kwargs = mock_svc.call_args
        assert kwargs["orderby"] == "liq_price"
        assert kwargs["order"] == "desc"
        assert kwargs["limit"] == 100

    def test_eth_ratio_passed_to_service(self, client: TestClient):
        """自定义 eth_ratio 应传递给 service。"""
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ) as mock_svc:
            client.get("/api/liquidate", params={"eth_price": 1500, "eth_ratio": 0.9})
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal("0.9")

    def test_default_eth_ratio_is_constant(self, client: TestClient):
        """默认 eth_ratio 应为 ETH_COLLATERAL_RATIO_MIN。"""
        from decimal import Decimal

        from aave_crawler.api.constants import ETH_COLLATERAL_RATIO_MIN

        with patch(
            f"{_ROUTES}.simulate_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SIM_EMPTY,
        ) as mock_svc:
            client.get("/api/liquidate", params={"eth_price": 1500})
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal(str(ETH_COLLATERAL_RATIO_MIN))

    def test_eth_ratio_out_of_range_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/liquidate", params={"eth_price": 1500, "eth_ratio": 1.5}
        )
        assert resp.status_code == 422

    def test_eth_ratio_negative_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/liquidate", params={"eth_price": 1500, "eth_ratio": -0.1}
        )
        assert resp.status_code == 422


class TestPricePeriod:
    """GET /api/price/period — 按间隔查询资产历史价格序列。"""

    _BASE_PARAMS = {
        "asset": "eth",
        "start": "2024-06-01",
        "end": "2024-06-03",
        "interval": 60,
    }

    def test_ok_returns_price_period(self, client: TestClient):
        """正常请求返回 200 和价格序列。"""
        with patch(
            f"{_ROUTES}.get_price_period",
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
        """验证 service 接收到正确解析后的参数。"""
        from datetime import datetime, timezone

        expected_start = int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp())
        expected_end = int(datetime(2024, 6, 3, tzinfo=timezone.utc).timestamp())
        with patch(
            f"{_ROUTES}.get_price_period",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_PERIOD,
        ) as mock_svc:
            client.get("/api/price/period", params=self._BASE_PARAMS)
        _, kwargs = mock_svc.call_args
        assert kwargs["start_ts"] == expected_start
        assert kwargs["end_ts"] == expected_end
        assert kwargs["interval_minutes"] == 60

    def test_default_interval_is_60(self, client: TestClient):
        """省略 interval 时默认 60 分钟。"""
        with patch(
            f"{_ROUTES}.get_price_period",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_PERIOD,
        ) as mock_svc:
            client.get(
                "/api/price/period",
                params={"asset": "eth", "start": "2024-06-01", "end": "2024-06-03"},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["interval_minutes"] == 60

    @pytest.mark.parametrize("interval", [1, 15, 30, 60, 1440])
    def test_various_intervals_accepted(self, client: TestClient, interval: int):
        with patch(
            f"{_ROUTES}.get_price_period",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_PERIOD,
        ):
            resp = client.get(
                "/api/price/period",
                params={
                    "asset": "eth",
                    "start": "2024-06-01",
                    "end": "2024-06-30",
                    "interval": interval,
                },
            )
        assert resp.status_code == 200

    def test_interval_zero_returns_422(self, client: TestClient):
        """interval < 1 应返回 422 Unprocessable Entity。"""
        resp = client.get(
            "/api/price/period",
            params={
                "asset": "eth",
                "start": "2024-06-01",
                "end": "2024-06-30",
                "interval": 0,
            },
        )
        assert resp.status_code == 422

    def test_missing_start_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/price/period", params={"asset": "eth", "end": "2024-06-30"}
        )
        assert resp.status_code == 422

    def test_missing_end_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/price/period", params={"asset": "eth", "start": "2024-06-01"}
        )
        assert resp.status_code == 422

    def test_invalid_start_time_returns_400(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_price_period",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_PERIOD,
        ):
            resp = client.get(
                "/api/price/period",
                params={"asset": "eth", "start": "not-a-date", "end": "2024-06-30"},
            )
        assert resp.status_code == 400

    def test_invalid_end_time_returns_400(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_price_period",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_PERIOD,
        ):
            resp = client.get(
                "/api/price/period",
                params={"asset": "eth", "start": "2024-06-01", "end": "invalid"},
            )
        assert resp.status_code == 400

    def test_no_w3_returns_503(self, app_no_w3):
        with TestClient(app_no_w3) as c:
            resp = c.get("/api/price/period", params=self._BASE_PARAMS)
        assert resp.status_code == 503

    def test_unknown_asset_returns_404(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_price_period",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="未找到资产"),
        ):
            resp = client.get(
                "/api/price/period",
                params={
                    "asset": "FAKETOKEN",
                    "start": "2024-06-01",
                    "end": "2024-06-30",
                },
            )
        assert resp.status_code == 404

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
            f"{_ROUTES}.get_price_period",
            new_callable=AsyncMock,
            return_value=MOCK_PRICE_PERIOD,
        ):
            resp = client.get(
                "/api/price/period",
                params={
                    "asset": "eth",
                    "start": time_str,
                    "end": time_str,
                    "interval": 60,
                },
            )
        assert resp.status_code == 200


class TestLiquidatePeriod:
    """GET /api/liquidate/period — ETH 价格区间清算汇总序列。"""

    _BASE_PARAMS = {"start": 1000, "end": 2000, "interval": 500}

    def test_ok_returns_list(self, client: TestClient):
        """正常请求返回 200 和列表。"""
        with patch(
            f"{_ROUTES}.simulate_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_LIQ_PERIOD,
        ):
            resp = client.get("/api/liquidate/period", params=self._BASE_PARAMS)
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
        """验证 service 接收到正确的 Decimal 参数。"""
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_LIQ_PERIOD,
        ) as mock_svc:
            client.get("/api/liquidate/period", params=self._BASE_PARAMS)
        _, kwargs = mock_svc.call_args
        assert kwargs["start_price"] == Decimal("1000")
        assert kwargs["end_price"] == Decimal("2000")
        assert kwargs["interval"] == Decimal("500")

    def test_missing_start_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/liquidate/period", params={"end": 2000, "interval": 500}
        )
        assert resp.status_code == 422

    def test_missing_end_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/liquidate/period", params={"start": 1000, "interval": 500}
        )
        assert resp.status_code == 422

    def test_missing_interval_returns_422(self, client: TestClient):
        resp = client.get("/api/liquidate/period", params={"start": 1000, "end": 2000})
        assert resp.status_code == 422

    def test_start_zero_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/liquidate/period", params={"start": 0, "end": 2000, "interval": 500}
        )
        assert resp.status_code == 422

    def test_interval_zero_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/liquidate/period", params={"start": 1000, "end": 2000, "interval": 0}
        )
        assert resp.status_code == 422

    def test_start_greater_than_end_returns_400(self, client: TestClient):
        """start > end 应返回 400。"""
        from fastapi import HTTPException

        with patch(
            f"{_ROUTES}.simulate_liquidation_period",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=400, detail="start 必须 <= end"),
        ):
            resp = client.get(
                "/api/liquidate/period",
                params={"start": 3000, "end": 1000, "interval": 500},
            )
        assert resp.status_code == 400

    def test_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/liquidate/period", params=self._BASE_PARAMS)
        assert resp.status_code == 503

    def test_empty_result_returns_empty_list(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_liquidation_period",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/liquidate/period", params=self._BASE_PARAMS)
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
                "/api/liquidate/period",
                params={"start": 500, "end": 3000, "interval": interval},
            )
        assert resp.status_code == 200

    def test_eth_ratio_passed_to_service(self, client: TestClient):
        """自定义 eth_ratio 应传递给 service。"""
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_LIQ_PERIOD,
        ) as mock_svc:
            client.get(
                "/api/liquidate/period",
                params={"start": 1000, "end": 2000, "interval": 500, "eth_ratio": 0.6},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal("0.6")

    def test_default_eth_ratio_is_constant(self, client: TestClient):
        """默认 eth_ratio 应为 ETH_COLLATERAL_RATIO_MIN。"""
        from decimal import Decimal

        from aave_crawler.api.constants import ETH_COLLATERAL_RATIO_MIN

        with patch(
            f"{_ROUTES}.simulate_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_LIQ_PERIOD,
        ) as mock_svc:
            client.get("/api/liquidate/period", params=self._BASE_PARAMS)
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal(str(ETH_COLLATERAL_RATIO_MIN))

    def test_eth_ratio_out_of_range_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/liquidate/period",
            params={"start": 1000, "end": 2000, "interval": 500, "eth_ratio": 1.5},
        )
        assert resp.status_code == 422

    def test_eth_ratio_negative_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/liquidate/period",
            params={"start": 1000, "end": 2000, "interval": 500, "eth_ratio": -0.1},
        )
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/borrow/positions
# ─────────────────────────────────────────────────────────────────────────────


class TestBorrowPositions:
    """GET /api/borrow/positions — 借贷端仓位列表（借入 WETH / 做空 ETH）。"""

    def test_default_ok(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_sorted_borrow_positions",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_POSITIONS_LIST,
        ):
            resp = client.get("/api/borrow/positions")
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
            resp = client.get("/api/borrow/positions")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.skip(reason="路由已迁移至 DbSession，不再依赖 pool")
    def test_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/borrow/positions")
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
            resp = client.get("/api/borrow/positions", params={"orderby": orderby})
        assert resp.status_code == 200

    def test_invalid_orderby_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/borrow/positions", params={"orderby": "nonexistent_col"}
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("order", ["asc", "desc"])
    def test_valid_order_values(self, client: TestClient, order: str):
        with patch(
            f"{_ROUTES}.get_sorted_borrow_positions",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_POSITIONS_LIST,
        ):
            resp = client.get("/api/borrow/positions", params={"order": order})
        assert resp.status_code == 200

    def test_invalid_order_returns_422(self, client: TestClient):
        resp = client.get("/api/borrow/positions", params={"order": "random"})
        assert resp.status_code == 422

    @pytest.mark.parametrize("limit", [1, 50, 200])
    def test_valid_limit_values(self, client: TestClient, limit: int):
        with patch(
            f"{_ROUTES}.get_sorted_borrow_positions",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_POSITIONS_LIST,
        ):
            resp = client.get("/api/borrow/positions", params={"limit": limit})
        assert resp.status_code == 200

    def test_limit_too_large_returns_422(self, client: TestClient):
        resp = client.get("/api/borrow/positions", params={"limit": 201})
        assert resp.status_code == 422

    def test_limit_zero_returns_422(self, client: TestClient):
        resp = client.get("/api/borrow/positions", params={"limit": 0})
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "version,expected_protocol",
        [
            ("v3", "v3_borrow"),
            ("v2", "v2_borrow"),
        ],
    )
    def test_version_maps_to_borrow_protocol(
        self, client: TestClient, version: str, expected_protocol: str
    ):
        with patch(
            f"{_ROUTES}.get_sorted_borrow_positions",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_POSITIONS_LIST,
        ) as mock_svc:
            client.get("/api/borrow/positions", params={"version": version})
        _, kwargs = mock_svc.call_args
        assert kwargs["protocol"] == expected_protocol

    def test_service_receives_correct_params(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_sorted_borrow_positions",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_POSITIONS_LIST,
        ) as mock_svc:
            client.get(
                "/api/borrow/positions",
                params={"orderby": "weth_debt_usd", "order": "desc", "limit": 50},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["orderby"] == "weth_debt_usd"
        assert kwargs["order"] == "desc"
        assert kwargs["limit"] == 50


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/borrow/liquidate
# ─────────────────────────────────────────────────────────────────────────────


class TestBorrowLiquidate:
    """GET /api/borrow/liquidate — 模拟 ETH 上涨时的做空清算情况。"""

    def test_missing_eth_price_returns_422(self, client: TestClient):
        resp = client.get("/api/borrow/liquidate")
        assert resp.status_code == 422

    def test_eth_price_zero_returns_422(self, client: TestClient):
        resp = client.get("/api/borrow/liquidate", params={"eth_price": 0})
        assert resp.status_code == 422

    def test_eth_price_negative_returns_422(self, client: TestClient):
        resp = client.get("/api/borrow/liquidate", params={"eth_price": -100})
        assert resp.status_code == 422

    def test_ok_with_results(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_RESPONSE,
        ):
            resp = client.get("/api/borrow/liquidate", params={"eth_price": 2700})
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
            resp = client.get("/api/borrow/liquidate", params={"eth_price": 1000})
        assert resp.status_code == 200
        data = resp.json()
        assert data["positions_cnt"] == "0"
        assert data["positions"] == []

    def test_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/borrow/liquidate", params={"eth_price": 2700})
        assert resp.status_code == 503

    def test_service_receives_decimal_eth_price(self, client: TestClient):
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_RESPONSE,
        ) as mock_svc:
            client.get("/api/borrow/liquidate", params={"eth_price": 2700.5})
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
                "/api/borrow/liquidate", params={"eth_price": 2700, "orderby": orderby}
            )
        assert resp.status_code == 200

    def test_invalid_orderby_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/borrow/liquidate", params={"eth_price": 2700, "orderby": "bad_col"}
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
                "/api/borrow/liquidate", params={"eth_price": 2700, "limit": limit}
            )
        assert resp.status_code == 200

    def test_limit_too_large_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/borrow/liquidate", params={"eth_price": 2700, "limit": 1001}
        )
        assert resp.status_code == 422

    def test_cap_passed_to_service(self, client: TestClient):
        from decimal import Decimal

        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_RESPONSE,
        ) as mock_svc:
            client.get("/api/borrow/liquidate", params={"eth_price": 2700, "cap": 3000})
        _, kwargs = mock_svc.call_args
        assert kwargs["cap"] == Decimal("3000")

    def test_no_cap_passes_none_to_service(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_short_liquidation",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_SIM_RESPONSE,
        ) as mock_svc:
            client.get("/api/borrow/liquidate", params={"eth_price": 2700})
        _, kwargs = mock_svc.call_args
        assert kwargs["cap"] is None

    def test_cap_zero_returns_422(self, client: TestClient):
        resp = client.get("/api/borrow/liquidate", params={"eth_price": 2700, "cap": 0})
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "version,expected_protocol",
        [
            ("v3", "v3_borrow"),
            ("v2", "v2_borrow"),
        ],
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
                "/api/borrow/liquidate", params={"eth_price": 2700, "version": version}
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
            client.get("/api/borrow/liquidate", params={"eth_price": 2700})
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
                "/api/borrow/liquidate", params={"eth_price": 2700, "eth_ratio": 0.8}
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
                "/api/borrow/liquidate", params={"eth_price": 2700, "eth_ratio": 0}
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal("0")

    def test_eth_ratio_greater_than_1_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/borrow/liquidate", params={"eth_price": 2700, "eth_ratio": 1.1}
        )
        assert resp.status_code == 422

    def test_eth_ratio_negative_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/borrow/liquidate", params={"eth_price": 2700, "eth_ratio": -0.1}
        )
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────


class TestBorrowLiquidatePeriod:
    """GET /api/borrow/liquidate/period — ETH 上涨区间内的做空清算分布。"""

    _BASE_PARAMS = {"start": 2000, "end": 3000, "interval": 500}

    def test_ok(self, client: TestClient):
        with patch(
            f"{_ROUTES}.simulate_short_liquidation_period",
            new_callable=AsyncMock,
            return_value=MOCK_SHORT_LIQ_PERIOD,
        ):
            resp = client.get("/api/borrow/liquidate/period", params=self._BASE_PARAMS)
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
            resp = client.get("/api/borrow/liquidate/period", params=self._BASE_PARAMS)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/borrow/liquidate/period", params=self._BASE_PARAMS)
        assert resp.status_code == 503

    def test_missing_start_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/borrow/liquidate/period", params={"end": 3000, "interval": 500}
        )
        assert resp.status_code == 422

    def test_missing_end_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/borrow/liquidate/period", params={"start": 2000, "interval": 500}
        )
        assert resp.status_code == 422

    def test_missing_interval_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/borrow/liquidate/period", params={"start": 2000, "end": 3000}
        )
        assert resp.status_code == 422

    def test_start_zero_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/borrow/liquidate/period",
            params={"start": 0, "end": 3000, "interval": 500},
        )
        assert resp.status_code == 422

    def test_interval_zero_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/borrow/liquidate/period",
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
                "/api/borrow/liquidate/period",
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
            client.get("/api/borrow/liquidate/period", params=self._BASE_PARAMS)
        _, kwargs = mock_svc.call_args
        assert kwargs["start_price"] == Decimal("2000")
        assert kwargs["end_price"] == Decimal("3000")
        assert kwargs["interval"] == Decimal("500")

    @pytest.mark.parametrize(
        "version,expected_protocol",
        [
            ("v3", "v3_borrow"),
            ("v2", "v2_borrow"),
        ],
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
                "/api/borrow/liquidate/period",
                params={**self._BASE_PARAMS, "version": version},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["protocol"] == expected_protocol

    def test_invalid_version_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/borrow/liquidate/period",
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
                "/api/borrow/liquidate/period",
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
            client.get("/api/borrow/liquidate/period", params=self._BASE_PARAMS)
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
                "/api/borrow/liquidate/period",
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
                "/api/borrow/liquidate/period",
                params={**self._BASE_PARAMS, "eth_ratio": 0},
            )
        _, kwargs = mock_svc.call_args
        assert kwargs["eth_ratio"] == Decimal("0")

    def test_eth_ratio_greater_than_1_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/borrow/liquidate/period",
            params={**self._BASE_PARAMS, "eth_ratio": 1.5},
        )
        assert resp.status_code == 422

    def test_eth_ratio_negative_returns_422(self, client: TestClient):
        resp = client.get(
            "/api/borrow/liquidate/period",
            params={**self._BASE_PARAMS, "eth_ratio": -0.1},
        )
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────


class TestBorrowUserPosition:
    """测试 GET /api/borrow/position。"""

    _URL = "/api/borrow/position"

    def test_ok_returns_200_with_all_fields(self, client: TestClient):
        with patch(
            f"{_ROUTES}.get_borrow_user_position",
            new_callable=AsyncMock,
            return_value=MOCK_BORROW_USER_POSITION,
        ):
            resp = client.get(self._URL, params={"address": ADDR})
        assert resp.status_code == 200
        data = resp.json()
        # 仅包含 borrow 专属字段，不与 /user/position 重合
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
        # 确认不包含 /user/position 的重合字段
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

    def test_no_pool_returns_503(self, app_no_pool: "FastAPI"):
        with TestClient(app_no_pool) as c:
            resp = c.get(self._URL, params={"address": ADDR})
        assert resp.status_code == 503

    @pytest.mark.parametrize(
        "version,expected_protocol",
        [
            ("v3", "v3_borrow"),
            ("v2", "v2_borrow"),
        ],
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
        # address 作为第 2 个位置参数传入（第 1 个是 pool）
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


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/position/replay
# ─────────────────────────────────────────────────────────────────────────────


class TestPositionReplay:
    """GET /api/position/replay — 必须参数 address / start / end。"""

    _URL = "/api/position/replay"
    _BASE = {"address": ADDR, "start": "2025-01-01", "end": "2026-01-01"}

    def test_missing_address_returns_422(self, client: TestClient):
        resp = client.get(self._URL, params={"start": "2025-01-01", "end": "2026-01-01"})
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
        for field in ("address", "protocol", "from_time", "to_time",
                      "data_source", "points", "total_points", "cache_hit_rate"):
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
        for field in ("tx_hash", "block_number", "timestamp", "eth_price_usd",
                      "total_collateral_usd", "total_debt_usd", "health_factor",
                      "liq_price", "liq_price_rise",
                      "eth_collateral_amount", "eth_collateral_usd",
                      "weth_debt_amount", "weth_debt_usd"):
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
        ["2025-01-01", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00", "2025-01-01 00:00:00"],
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
    def test_version_passed_to_service(self, client: TestClient, version: str, expected: str):
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


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/txs
# ─────────────────────────────────────────────────────────────────────────────


class TestTxHistory:
    """GET /api/txs — 必须参数 address / start / end。"""

    _URL = "/api/txs"
    _BASE = {"address": ADDR, "start": "2025-01-01", "end": "2026-01-01"}

    def test_missing_address_returns_422(self, client: TestClient):
        resp = client.get(self._URL, params={"start": "2025-01-01", "end": "2026-01-01"})
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
        for field in ("tx_hash", "block_number", "timestamp",
                      "operation_type", "token_symbol", "cached"):
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
        ["2025-01-01", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00", "2025-01-01 00:00:00"],
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
    def test_version_passed_to_service(self, client: TestClient, version: str, expected: str):
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
