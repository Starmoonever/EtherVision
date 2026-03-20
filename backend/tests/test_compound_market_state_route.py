from __future__ import annotations

from datetime import datetime, timezone

from compound_crawler.api.routes import router as compound_router
from compound_crawler.database import get_pool
from fastapi import FastAPI
from starlette.testclient import TestClient


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self, row, reserve_rows):
        self._row = row
        self._reserve_rows = reserve_rows

    async def fetchrow(self, _sql, *_args):
        return self._row

    async def fetch(self, _sql, *_args):
        return self._reserve_rows


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


def _build_client(row=None, reserve_rows=None) -> TestClient:
    app = FastAPI()
    app.include_router(compound_router)

    fake_conn = _FakeConn(row=row, reserve_rows=reserve_rows or [])
    fake_pool = _FakePool(fake_conn)

    async def _override_pool():
        return fake_pool

    app.dependency_overrides[get_pool] = _override_pool
    return TestClient(app)


def test_market_state_ok_without_detail() -> None:
    row = {
        "timestamp": datetime(2026, 3, 19, 12, 0, 0, tzinfo=timezone.utc),
        "market": bytes.fromhex("c3d688b66703497daa19211eedff47f25384cdc3"),
        "symbol": "USDC",
        "total_supply": "100",
        "total_borrow": "20",
        "collateral_usd": "80000",
        "utilization": "0.2",
        "borrow_rate": "0.01",
        "supply_rate": "0.005",
        "price_usd": "1000",
        "supply_usd": "100000",
        "borrow_usd": "20000",
    }
    with _build_client(row=row) as client:
        resp = client.get(
            "/api/compound/market/state",
            params={
                "version": "v3",
                "market": "usdc",
                "date": "2026-03-19T12:00:00Z",
                "detail": "false",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "v3"
    assert data["market"] == "0xc3d688b66703497daa19211eedff47f25384cdc3"
    assert data["symbol"] == "USDC"
    assert data["timestamp"] == "2026-03-19T12:00:00Z"
    assert data["collateral_usd"] == "80000"
    assert data["borrow_apr"] == "315360.00"
    assert data["supply_apr"] == "157680.000"
    assert "borrow_rate" not in data
    assert "supply_rate" not in data
    assert data["price_usd"] == "1000"
    assert data["reserves"] is None


def test_market_state_ok_with_detail() -> None:
    row = {
        "timestamp": datetime(2026, 3, 19, 12, 0, 0, tzinfo=timezone.utc),
        "market": bytes.fromhex("c3d688b66703497daa19211eedff47f25384cdc3"),
        "symbol": "USDC",
        "total_supply": "100",
        "total_borrow": "20",
        "collateral_usd": "80000",
        "utilization": "0.2",
        "borrow_rate": "0.01",
        "supply_rate": "0.005",
        "price_usd": "1000",
        "supply_usd": "100000",
        "borrow_usd": "20000",
    }
    reserve_rows = [
        {
            "reserve": bytes.fromhex("a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"),
            "symbol": "USDC",
            "decimals": 6,
            "total_supply": "80",
            "total_borrow": "20",
            "utilization": "0.25",
            "borrow_rate": "0.02",
            "supply_rate": "0.01",
            "price_in_base": "0.8",
            "price_usd": "1000",
            "supply_usd": "80000",
            "borrow_usd": "20000",
        }
    ]
    with _build_client(row=row, reserve_rows=reserve_rows) as client:
        resp = client.get(
            "/api/compound/market/state",
            params={
                "version": "v3",
                "market": "USDC",
                "date": "2026-03-19T12:00:00Z",
                "detail": "true",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["reserves"], list)
    assert len(data["reserves"]) == 1
    assert data["reserves"][0]["reserve"].startswith("0x")
    assert data["reserves"][0]["borrow_apr"] == "630720.00"
    assert data["reserves"][0]["supply_apr"] == "315360.00"
    assert "borrow_rate" not in data["reserves"][0]
    assert "supply_rate" not in data["reserves"][0]
    assert data["reserves"][0]["price_in_base"] == "0.8"
    assert data["reserves"][0]["price_usd"] == "1000"


def test_market_state_reject_v2_for_now() -> None:
    with _build_client(row=None) as client:
        resp = client.get(
            "/api/compound/market/state",
            params={
                "version": "v2",
                "market": "USDC",
                "date": "2026-03-19T12:00:00Z",
            },
        )
    assert resp.status_code == 400
    assert "仅支持" in resp.json()["detail"]


def test_market_state_reject_non_hour_date() -> None:
    with _build_client(row=None) as client:
        resp = client.get(
            "/api/compound/market/state",
            params={
                "version": "v3",
                "market": "USDC",
                "date": "2026-03-19T12:30:00Z",
            },
        )
    assert resp.status_code == 400
    assert "精确到小时" in resp.json()["detail"]
