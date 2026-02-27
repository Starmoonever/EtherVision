"""pytest 公共 fixtures"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from aave_crawler.api.routes import router
from aave_crawler.api.schemas import (
    HistoricalPositionResponse,
    HistoricalReserveDetail,
    LiqPriceResponse,
    PositionResponse,
    PriceResponse,
)

# ── 测试用地址 ────────────────────────────────────────────────────────────────

ADDR = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
WETH_ADDR = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"

# ── Mock 返回值 ──────────────────────────────────────────────────────────────

MOCK_POSITION = PositionResponse(
    address=ADDR,
    eth_collateral_amount="1.500000",
    eth_collateral_usd="4500.00",
    total_debt_usd="2000.00",
    health_factor="1.6875",
    ltv="0.6500",
    liq_threshold="0.8000",
    liq_price="1666.67",
)

MOCK_LIQ = LiqPriceResponse(
    address=ADDR,
    current_eth_price_usd="3000.00",
    liquidation_eth_price_usd="1666.67",
    distance_pct="44.44",
    health_factor="1.6875",
    note="",
)

MOCK_PRICE_ONCHAIN = PriceResponse(
    asset="ETH",
    price_usd="3000.00",
    token_address=WETH_ADDR,
    timestamp="2025-01-01T00:00:00Z",
    source="on-chain",
)

MOCK_PRICE_HIST = PriceResponse(
    asset="ETH",
    price_usd="2800.00",
    token_address=WETH_ADDR,
    timestamp="2024-06-01T00:00:00Z",
    source="defillama",
)

MOCK_HIST_POSITION = HistoricalPositionResponse(
    address=ADDR,
    at_time="2025-01-01T00:00:00Z",
    eth_collateral_amount="1.500000",
    eth_price_usd="3200.00",
    eth_collateral_usd="4800.00",
    total_debt_approx_usd="2000.00",
    liq_price="1666.67",
    reserves=[
        HistoricalReserveDetail(
            symbol="WETH",
            token_address=WETH_ADDR,
            supply_amount="1.500000",
            debt_amount="0.000000",
        )
    ],
    note="",
)

MOCK_POSITIONS_LIST = [MOCK_POSITION]
MOCK_HIST_POSITIONS_LIST = [MOCK_HIST_POSITION]


# ── fixtures ──────────────────────────────────────────────────────────────────


def _make_app(w3=..., pool=...) -> FastAPI:
    """创建含路由的测试 FastAPI 实例；使用 ... 表示使用默认 MagicMock。"""
    _app = FastAPI()
    _app.include_router(router)
    _app.state.w3 = MagicMock() if w3 is ... else w3
    _app.state.pool = MagicMock() if pool is ... else pool
    return _app


@pytest.fixture
def app() -> FastAPI:
    """默认测试 app：w3 和 pool 均为 MagicMock（非 None，通过守卫检查）。"""
    return _make_app()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def app_no_w3() -> FastAPI:
    """w3=None 的 app，用于测试 503 场景。"""
    return _make_app(w3=None)


@pytest.fixture
def app_no_pool() -> FastAPI:
    """pool=None 的 app，用于测试 503 场景。"""
    return _make_app(pool=None)
