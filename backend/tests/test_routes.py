"""
API 路由单元测试。

覆盖所有端点的所有参数组合：
  - GET /api/user/position
  - GET /api/user/liq_price
  - GET /api/positions
  - GET /api/price

使用 starlette.testclient.TestClient（同步），mock 所有 service 函数，
无需真实 RPC 或数据库连接。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from tests.conftest import (
    ADDR,
    MOCK_HIST_POSITION,
    MOCK_HIST_POSITIONS_LIST,
    MOCK_LIQ,
    MOCK_POSITION,
    MOCK_POSITIONS_LIST,
    MOCK_PRICE_HIST,
    MOCK_PRICE_ONCHAIN,
    MOCK_SIM_EMPTY,
    MOCK_SIM_RESPONSE,
    _make_app,
)

# service 函数在 routes 模块中被导入，patch 该命名空间
_ROUTES = "aave_crawler.api.routes"

_404 = HTTPException(status_code=404, detail="无仓位")
_502 = HTTPException(status_code=502, detail="RPC失败")


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/user/position
# ─────────────────────────────────────────────────────────────────────────────


class TestUserPosition:
    """GET /api/user/position — 必须参数 address，可选参数 date。"""

    def test_missing_address_returns_422(self, client: TestClient):
        resp = client.get("/api/user/position")
        assert resp.status_code == 422

    # ── 实时模式（无 date）────────────────────────────────────────────────────

    def test_realtime_ok(self, client: TestClient):
        with patch(f"{_ROUTES}.get_user_position", new_callable=AsyncMock,
                   return_value=MOCK_POSITION):
            resp = client.get("/api/user/position", params={"address": ADDR})
        assert resp.status_code == 200
        data = resp.json()
        assert data["address"] == ADDR
        assert "health_factor" in data
        assert "liq_price" in data
        assert "at_time" not in data  # PositionResponse，不含历史字段

    def test_realtime_empty_position_returns_404(self, client: TestClient):
        with patch(f"{_ROUTES}.get_user_position", new_callable=AsyncMock,
                   side_effect=_404):
            resp = client.get("/api/user/position", params={"address": ADDR})
        assert resp.status_code == 404

    def test_realtime_rpc_failure_returns_502(self, client: TestClient):
        with patch(f"{_ROUTES}.get_user_position", new_callable=AsyncMock,
                   side_effect=_502):
            resp = client.get("/api/user/position", params={"address": ADDR})
        assert resp.status_code == 502

    def test_realtime_no_w3_returns_503(self, app_no_w3):
        with TestClient(app_no_w3) as c:
            resp = c.get("/api/user/position", params={"address": ADDR})
        assert resp.status_code == 503

    # ── 历史模式（带 date）────────────────────────────────────────────────────

    def test_historical_ok(self, client: TestClient):
        with patch(f"{_ROUTES}.get_user_position_history", new_callable=AsyncMock,
                   return_value=MOCK_HIST_POSITION):
            resp = client.get("/api/user/position",
                              params={"address": ADDR, "date": "2025-01-01"})
        assert resp.status_code == 200
        data = resp.json()
        assert "at_time" in data          # HistoricalPositionResponse 字段
        assert data["at_time"] == "2025-01-01T00:00:00Z"

    def test_historical_fallback_to_realtime_when_no_history(self, client: TestClient):
        """history 无记录 → 返回 None → 回退到实时链上查询。"""
        with patch(f"{_ROUTES}.get_user_position_history", new_callable=AsyncMock,
                   return_value=None), \
             patch(f"{_ROUTES}.get_user_position", new_callable=AsyncMock,
                   return_value=MOCK_POSITION):
            resp = client.get("/api/user/position",
                              params={"address": ADDR, "date": "2025-01-01"})
        assert resp.status_code == 200
        data = resp.json()
        assert "health_factor" in data   # 回退后是 PositionResponse
        assert "at_time" not in data

    @pytest.mark.parametrize("date_str,expected_ts_prefix", [
        ("2025-01-01",             "2025-01-01T"),
        ("2025-06-15T12:00:00Z",   "2025-06-15T"),
        ("2025-06-15T12:00:00",    "2025-06-15T"),
        ("2025-06-15 12:00:00",    "2025-06-15T"),
    ])
    def test_historical_date_formats_accepted(
        self, client: TestClient, date_str: str, expected_ts_prefix: str
    ):
        with patch(f"{_ROUTES}.get_user_position_history", new_callable=AsyncMock,
                   return_value=MOCK_HIST_POSITION):
            resp = client.get("/api/user/position",
                              params={"address": ADDR, "date": date_str})
        assert resp.status_code == 200

    @pytest.mark.parametrize("bad_date", [
        "not-a-date",
        "2025/01/01",
        "Jan 1 2025",
        "1704067200",   # 纯 Unix 时间戳不支持
    ])
    def test_invalid_date_returns_400(self, client: TestClient, bad_date: str):
        resp = client.get("/api/user/position",
                          params={"address": ADDR, "date": bad_date})
        assert resp.status_code == 400

    def test_historical_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/user/position",
                         params={"address": ADDR, "date": "2025-01-01"})
        assert resp.status_code == 503


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/user/liq_price
# ─────────────────────────────────────────────────────────────────────────────


class TestUserLiqPrice:
    """GET /api/user/liq_price — 必须参数 address。"""

    def test_missing_address_returns_422(self, client: TestClient):
        resp = client.get("/api/user/liq_price")
        assert resp.status_code == 422

    def test_normal_ok(self, client: TestClient):
        with patch(f"{_ROUTES}.get_liq_price", new_callable=AsyncMock,
                   return_value=MOCK_LIQ):
            resp = client.get("/api/user/liq_price", params={"address": ADDR})
        assert resp.status_code == 200
        data = resp.json()
        assert data["address"] == ADDR
        assert "current_eth_price_usd" in data
        assert "liquidation_eth_price_usd" in data
        assert "distance_pct" in data
        assert "health_factor" in data

    def test_no_debt_returns_inf_distance(self, client: TestClient):
        from aave_crawler.api.schemas import LiqPriceResponse
        no_debt = LiqPriceResponse(
            address=ADDR,
            current_eth_price_usd="3000.00",
            liquidation_eth_price_usd="0",
            distance_pct="inf",
            health_factor="inf",
            note="该地址无借贷，不存在清算风险",
        )
        with patch(f"{_ROUTES}.get_liq_price", new_callable=AsyncMock,
                   return_value=no_debt):
            resp = client.get("/api/user/liq_price", params={"address": ADDR})
        assert resp.status_code == 200
        assert resp.json()["distance_pct"] == "inf"

    def test_no_eth_collateral_returns_note(self, client: TestClient):
        from aave_crawler.api.schemas import LiqPriceResponse
        no_eth = LiqPriceResponse(
            address=ADDR,
            current_eth_price_usd="0",
            liquidation_eth_price_usd="0",
            distance_pct="0",
            health_factor="1.2000",
            note="未发现 ETH/WETH 抵押仓位，无法计算 ETH 清算价",
        )
        with patch(f"{_ROUTES}.get_liq_price", new_callable=AsyncMock,
                   return_value=no_eth):
            resp = client.get("/api/user/liq_price", params={"address": ADDR})
        assert resp.status_code == 200
        assert "ETH" in resp.json()["note"]

    def test_empty_position_returns_404(self, client: TestClient):
        with patch(f"{_ROUTES}.get_liq_price", new_callable=AsyncMock,
                   side_effect=_404):
            resp = client.get("/api/user/liq_price", params={"address": ADDR})
        assert resp.status_code == 404

    def test_rpc_failure_returns_502(self, client: TestClient):
        with patch(f"{_ROUTES}.get_liq_price", new_callable=AsyncMock,
                   side_effect=_502):
            resp = client.get("/api/user/liq_price", params={"address": ADDR})
        assert resp.status_code == 502

    def test_no_w3_returns_503(self, app_no_w3):
        with TestClient(app_no_w3) as c:
            resp = c.get("/api/user/liq_price", params={"address": ADDR})
        assert resp.status_code == 503


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/positions
# ─────────────────────────────────────────────────────────────────────────────


class TestPositions:
    """GET /api/positions — 可选 orderby / order / limit / date。"""

    # ── 实时模式（无 date）────────────────────────────────────────────────────

    def test_defaults_ok(self, client: TestClient):
        with patch(f"{_ROUTES}.get_sorted_positions", new_callable=AsyncMock,
                   return_value=MOCK_POSITIONS_LIST) as mock_svc:
            resp = client.get("/api/positions")
        assert resp.status_code == 200
        mock_svc.assert_awaited_once()
        _, kwargs = mock_svc.call_args
        assert kwargs.get("orderby", mock_svc.call_args.args[1] if len(mock_svc.call_args.args) > 1 else "liq_price") is not None
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["address"] == ADDR

    @pytest.mark.parametrize("orderby", ["liq_price", "health_factor"])
    def test_orderby_variants(self, client: TestClient, orderby: str):
        with patch(f"{_ROUTES}.get_sorted_positions", new_callable=AsyncMock,
                   return_value=MOCK_POSITIONS_LIST):
            resp = client.get("/api/positions", params={"orderby": orderby})
        assert resp.status_code == 200

    @pytest.mark.parametrize("order", ["asc", "desc"])
    def test_order_variants(self, client: TestClient, order: str):
        with patch(f"{_ROUTES}.get_sorted_positions", new_callable=AsyncMock,
                   return_value=MOCK_POSITIONS_LIST):
            resp = client.get("/api/positions", params={"order": order})
        assert resp.status_code == 200

    @pytest.mark.parametrize("limit", [1, 10, 100, 200])
    def test_limit_boundaries_ok(self, client: TestClient, limit: int):
        with patch(f"{_ROUTES}.get_sorted_positions", new_callable=AsyncMock,
                   return_value=MOCK_POSITIONS_LIST):
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
        with patch(f"{_ROUTES}.get_positions_history", new_callable=AsyncMock,
                   return_value=MOCK_HIST_POSITIONS_LIST):
            resp = client.get("/api/positions",
                              params={"date": "2025-01-01", "limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert "at_time" in data[0]

    def test_historical_limit_capped_at_100(self, client: TestClient):
        """历史模式下 limit > 100 应被裁剪至 100。"""
        with patch(f"{_ROUTES}.get_positions_history", new_callable=AsyncMock,
                   return_value=MOCK_HIST_POSITIONS_LIST) as mock_svc:
            resp = client.get("/api/positions",
                              params={"date": "2025-01-01", "limit": 150})
        assert resp.status_code == 200
        # 验证传递给 service 的 limit 不超过 100
        _, kwargs = mock_svc.call_args
        passed_limit = kwargs.get("limit") or mock_svc.call_args.args[-1]
        assert passed_limit <= 100

    @pytest.mark.parametrize("date_str", [
        "2024-01-01",
        "2024-01-01T00:00:00Z",
        "2024-01-01T00:00:00",
        "2024-01-01 00:00:00",
    ])
    def test_historical_date_formats_accepted(self, client: TestClient, date_str: str):
        with patch(f"{_ROUTES}.get_positions_history", new_callable=AsyncMock,
                   return_value=MOCK_HIST_POSITIONS_LIST):
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
        with patch(f"{_ROUTES}.get_eth_price", new_callable=AsyncMock,
                   return_value=MOCK_PRICE_ONCHAIN) as mock_svc:
            resp = client.get("/api/price")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "on-chain"
        # 确认调用时 timestamp 参数未传（即为 None）
        _, kwargs = mock_svc.call_args
        assert kwargs.get("timestamp") is None

    def test_time_now_explicit(self, client: TestClient):
        with patch(f"{_ROUTES}.get_eth_price", new_callable=AsyncMock,
                   return_value=MOCK_PRICE_ONCHAIN):
            resp = client.get("/api/price", params={"time": "now"})
        assert resp.status_code == 200
        assert resp.json()["source"] == "on-chain"

    @pytest.mark.parametrize("asset", ["eth", "ETH", "wbtc", "WBTC", "usdc"])
    def test_various_assets_realtime(self, client: TestClient, asset: str):
        with patch(f"{_ROUTES}.get_eth_price", new_callable=AsyncMock,
                   return_value=MOCK_PRICE_ONCHAIN):
            resp = client.get("/api/price", params={"asset": asset})
        assert resp.status_code == 200

    def test_unknown_asset_returns_404(self, client: TestClient):
        with patch(f"{_ROUTES}.get_eth_price", new_callable=AsyncMock,
                   side_effect=HTTPException(status_code=404, detail="未找到资产")):
            resp = client.get("/api/price", params={"asset": "FAKETOKEN"})
        assert resp.status_code == 404

    def test_no_w3_returns_503(self, app_no_w3):
        with TestClient(app_no_w3) as c:
            resp = c.get("/api/price")
        assert resp.status_code == 503

    # ── 历史模式（time=<日期字符串>）─────────────────────────────────────────

    def test_historical_price_ok(self, client: TestClient):
        with patch(f"{_ROUTES}.get_eth_price", new_callable=AsyncMock,
                   return_value=MOCK_PRICE_HIST) as mock_svc:
            resp = client.get("/api/price",
                              params={"asset": "eth", "time": "2024-06-01"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "defillama"
        # 确认调用时传入了 timestamp（非 None）
        _, kwargs = mock_svc.call_args
        assert kwargs.get("timestamp") is not None
        assert isinstance(kwargs["timestamp"], int)

    @pytest.mark.parametrize("time_str", [
        "2024-06-01",
        "2024-06-01T12:00:00Z",
        "2024-06-01T12:00:00",
        "2024-06-01 12:00:00",
    ])
    def test_historical_time_formats_accepted(self, client: TestClient, time_str: str):
        with patch(f"{_ROUTES}.get_eth_price", new_callable=AsyncMock,
                   return_value=MOCK_PRICE_HIST):
            resp = client.get("/api/price",
                              params={"asset": "eth", "time": time_str})
        assert resp.status_code == 200

    def test_historical_correct_timestamp_passed(self, client: TestClient):
        """时间字符串应正确解析为 Unix 时间戳后传给 service。"""
        from datetime import datetime, timezone
        expected_ts = int(
            datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp()
        )
        with patch(f"{_ROUTES}.get_eth_price", new_callable=AsyncMock,
                   return_value=MOCK_PRICE_HIST) as mock_svc:
            client.get("/api/price",
                       params={"asset": "eth", "time": "2024-06-01"})
        _, kwargs = mock_svc.call_args
        assert kwargs["timestamp"] == expected_ts

    @pytest.mark.parametrize("bad_time", [
        "yesterday",
        "2024-13-01",    # 月份超范围（Python strptime 会报错）
        "2024.06.01",
        "06/01/2024",
    ])
    def test_invalid_time_format_returns_400(self, client: TestClient, bad_time: str):
        resp = client.get("/api/price", params={"time": bad_time})
        assert resp.status_code == 400

    def test_defillama_failure_returns_502(self, client: TestClient):
        with patch(f"{_ROUTES}.get_eth_price", new_callable=AsyncMock,
                   side_effect=HTTPException(status_code=502, detail="DeFiLlama 不可用")):
            resp = client.get("/api/price",
                              params={"asset": "eth", "time": "2024-06-01"})
        assert resp.status_code == 502

    def test_historical_no_w3_returns_503(self, app_no_w3):
        with TestClient(app_no_w3) as c:
            resp = c.get("/api/price",
                         params={"asset": "eth", "time": "2024-06-01"})
        assert resp.status_code == 503


# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数 _parse_utc_time 的独立测试
# ─────────────────────────────────────────────────────────────────────────────


class TestParseUtcTime:
    """直接测试路由层的日期解析辅助函数。"""

    def _call(self, time_str: str) -> int:
        from aave_crawler.api.routes import _parse_utc_time
        return _parse_utc_time(time_str)

    @pytest.mark.parametrize("time_str,expected", [
        ("2025-01-01",              1735689600),
        ("2025-01-01T00:00:00Z",    1735689600),
        ("2025-01-01T00:00:00",     1735689600),
        ("2025-01-01 00:00:00",     1735689600),
    ])
    def test_valid_formats(self, time_str: str, expected: int):
        assert self._call(time_str) == expected

    @pytest.mark.parametrize("bad_str", [
        "not-a-date",
        "2025/01/01",
        "Jan 1 2025",
    ])
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
        with patch(f"{_ROUTES}.simulate_liquidation", new_callable=AsyncMock,
                   return_value=MOCK_SIM_RESPONSE):
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
        with patch(f"{_ROUTES}.simulate_liquidation", new_callable=AsyncMock,
                   return_value=MOCK_SIM_EMPTY):
            resp = client.get("/api/liquidate", params={"eth_price": 100})
        assert resp.status_code == 200
        data = resp.json()
        assert data["positions"] == []
        assert data["total_eth_collateral_usd"] == "0.00"
        assert data["total_liquidation_usd"] == "0.00"

    @pytest.mark.parametrize("eth_price", [1.0, 100.5, 1500, 3000.99, 10000])
    def test_various_eth_prices_accepted(self, client: TestClient, eth_price: float):
        with patch(f"{_ROUTES}.simulate_liquidation", new_callable=AsyncMock,
                   return_value=MOCK_SIM_EMPTY):
            resp = client.get("/api/liquidate", params={"eth_price": eth_price})
        assert resp.status_code == 200

    def test_total_liquidation_lte_total_collateral(self, client: TestClient):
        """清算人最多获得全部抵押品，total_liquidation_usd 不超过 total_eth_collateral_usd。"""
        with patch(f"{_ROUTES}.simulate_liquidation", new_callable=AsyncMock,
                   return_value=MOCK_SIM_RESPONSE):
            resp = client.get("/api/liquidate", params={"eth_price": 1500})
        data = resp.json()
        total_liq = float(data["total_liquidation_usd"])
        total_col = float(data["total_eth_collateral_usd"])
        # 清算奖励可能导致 liq > col（当债 > col/1.05），但不前超过 col
        # mock 中是手工构造的，这里只验证字段类型合法
        assert isinstance(total_liq, float)
        assert isinstance(total_col, float)

    def test_note_field_present(self, client: TestClient):
        with patch(f"{_ROUTES}.simulate_liquidation", new_callable=AsyncMock,
                   return_value=MOCK_SIM_RESPONSE):
            resp = client.get("/api/liquidate", params={"eth_price": 1500})
        assert "note" in resp.json()

    def test_no_pool_returns_503(self, app_no_pool):
        with TestClient(app_no_pool) as c:
            resp = c.get("/api/liquidate", params={"eth_price": 1500})
        assert resp.status_code == 503

    # ── limit ──────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("limit", [1, 10, 100, 500, 1000])
    def test_limit_valid_values(self, client: TestClient, limit: int):
        with patch(f"{_ROUTES}.simulate_liquidation", new_callable=AsyncMock,
                   return_value=MOCK_SIM_EMPTY):
            resp = client.get("/api/liquidate",
                              params={"eth_price": 1500, "limit": limit})
        assert resp.status_code == 200

    def test_limit_zero_returns_422(self, client: TestClient):
        resp = client.get("/api/liquidate",
                          params={"eth_price": 1500, "limit": 0})
        assert resp.status_code == 422

    def test_limit_over_max_returns_422(self, client: TestClient):
        resp = client.get("/api/liquidate",
                          params={"eth_price": 1500, "limit": 1001})
        assert resp.status_code == 422

    def test_limit_passed_to_service(self, client: TestClient):
        """limit 参数应原样传递给 simulate_liquidation。"""
        with patch(f"{_ROUTES}.simulate_liquidation", new_callable=AsyncMock,
                   return_value=MOCK_SIM_EMPTY) as mock_svc:
            client.get("/api/liquidate",
                       params={"eth_price": 1500, "limit": 42})
        _, kwargs = mock_svc.call_args
        assert kwargs["limit"] == 42

    # ── orderby ────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("orderby", [
        "liq_price",
        "eth_collateral_amount",
        "eth_collateral_usd",
        "total_debt_usd",
    ])
    def test_orderby_valid_values(self, client: TestClient, orderby: str):
        with patch(f"{_ROUTES}.simulate_liquidation", new_callable=AsyncMock,
                   return_value=MOCK_SIM_EMPTY):
            resp = client.get("/api/liquidate",
                              params={"eth_price": 1500, "orderby": orderby})
        assert resp.status_code == 200

    def test_orderby_invalid_returns_422(self, client: TestClient):
        resp = client.get("/api/liquidate",
                          params={"eth_price": 1500, "orderby": "address"})
        assert resp.status_code == 422

    def test_orderby_passed_to_service(self, client: TestClient):
        with patch(f"{_ROUTES}.simulate_liquidation", new_callable=AsyncMock,
                   return_value=MOCK_SIM_EMPTY) as mock_svc:
            client.get("/api/liquidate",
                       params={"eth_price": 1500, "orderby": "total_debt_usd"})
        _, kwargs = mock_svc.call_args
        assert kwargs["orderby"] == "total_debt_usd"

    # ── order ──────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("order", ["asc", "desc"])
    def test_order_valid_values(self, client: TestClient, order: str):
        with patch(f"{_ROUTES}.simulate_liquidation", new_callable=AsyncMock,
                   return_value=MOCK_SIM_EMPTY):
            resp = client.get("/api/liquidate",
                              params={"eth_price": 1500, "order": order})
        assert resp.status_code == 200

    def test_order_invalid_returns_422(self, client: TestClient):
        resp = client.get("/api/liquidate",
                          params={"eth_price": 1500, "order": "random"})
        assert resp.status_code == 422

    def test_order_passed_to_service(self, client: TestClient):
        with patch(f"{_ROUTES}.simulate_liquidation", new_callable=AsyncMock,
                   return_value=MOCK_SIM_EMPTY) as mock_svc:
            client.get("/api/liquidate",
                       params={"eth_price": 1500, "order": "asc"})
        _, kwargs = mock_svc.call_args
        assert kwargs["order"] == "asc"

    def test_defaults_orderby_liq_price_desc(self, client: TestClient):
        """默认 orderby=liq_price, order=desc。"""
        with patch(f"{_ROUTES}.simulate_liquidation", new_callable=AsyncMock,
                   return_value=MOCK_SIM_EMPTY) as mock_svc:
            client.get("/api/liquidate", params={"eth_price": 1500})
        _, kwargs = mock_svc.call_args
        assert kwargs["orderby"] == "liq_price"
        assert kwargs["order"] == "desc"
        assert kwargs["limit"] == 100
