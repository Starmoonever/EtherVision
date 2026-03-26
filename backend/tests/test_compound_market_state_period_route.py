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
    def __init__(self, rows, reserve_rows):
        self._rows = rows
        self._reserve_rows = reserve_rows

    async def fetchrow(self, _sql, *_args):
        return None

    async def fetch(self, sql, *args):
        if (
            "FROM loan.compound_v3_market_snapshots" in sql
            or "FROM loan.compound_v2_market_snapshots" in sql
        ):
            return self._rows
        if (
            "FROM loan.compound_v3_market_snapshot_reserves" in sql
            or "FROM loan.compound_v2_market_snapshot_reserves" in sql
        ):
            return self._reserve_rows
        return []


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


def _build_client(rows=None, reserve_rows=None) -> TestClient:
    app = FastAPI()
    app.include_router(compound_router)
    fake_conn = _FakeConn(rows=rows or [], reserve_rows=reserve_rows or [])
    fake_pool = _FakePool(fake_conn)

    async def _override_pool():
        return fake_pool

    app.dependency_overrides[get_pool] = _override_pool
    return TestClient(app)


def test_market_state_period_ok_without_detail() -> None:
    ts1 = datetime(2026, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 3, 11, 0, 0, 0, tzinfo=timezone.utc)
    rows = [
        {
            "timestamp": ts1,
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
        },
        {
            "timestamp": ts2,
            "market": bytes.fromhex("c3d688b66703497daa19211eedff47f25384cdc3"),
            "symbol": "USDC",
            "total_supply": "110",
            "total_borrow": "22",
            "collateral_usd": "85000",
            "utilization": "0.2",
            "borrow_rate": "0.01",
            "supply_rate": "0.005",
            "price_usd": "1000",
            "supply_usd": "110000",
            "borrow_usd": "22000",
        },
    ]
    with _build_client(rows=rows) as client:
        resp = client.get(
            "/api/compound/market/state/period",
            params={
                "version": "v3",
                "market": "usdc",
                "start": "2026-03-10T00:00:00Z",
                "end": "2026-03-11T00:00:00Z",
                "interval": 24,
                "detail": "false",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["points"], list)
    assert len(data["points"]) == 2
    assert data["points"][0]["market"] == "0xc3d688b66703497daa19211eedff47f25384cdc3"
    assert data["points"][0]["symbol"] == "USDC"
    assert data["points"][0]["collateral_usd"] == "80000"
    assert data["points"][0]["borrow_apr"] == "315360.00"
    assert data["points"][0]["supply_apr"] == "157680.000"
    assert "borrow_rate" not in data["points"][0]
    assert "supply_rate" not in data["points"][0]
    assert data["points"][0]["price_usd"] == "1000"
    assert data["points"][1]["total_supply"] == "110"
    assert data["points"][0]["reserves"] is None


def test_market_state_period_ok_with_detail() -> None:
    ts1 = datetime(2026, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
    rows = [
        {
            "timestamp": ts1,
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
    ]
    reserve_rows = [
        {
            "timestamp": ts1,
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
    with _build_client(rows=rows, reserve_rows=reserve_rows) as client:
        resp = client.get(
            "/api/compound/market/state/period",
            params={
                "version": "v3",
                "market": "USDC",
                "start": "2026-03-10T00:00:00Z",
                "end": "2026-03-10T00:00:00Z",
                "interval": 24,
                "detail": "true",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["points"]) == 1
    assert isinstance(data["points"][0]["reserves"], list)
    assert data["points"][0]["borrow_apr"] == "315360.00"
    assert data["points"][0]["supply_apr"] == "157680.000"
    assert data["points"][0]["reserves"][0]["borrow_apr"] == "630720.00"
    assert data["points"][0]["reserves"][0]["supply_apr"] == "315360.00"
    assert "borrow_rate" not in data["points"][0]["reserves"][0]
    assert "supply_rate" not in data["points"][0]["reserves"][0]
    assert data["points"][0]["reserves"][0]["price_in_base"] == "0.8"
    assert data["points"][0]["reserves"][0]["price_usd"] == "1000"


def test_market_state_period_invalid_interval() -> None:
    with _build_client() as client:
        resp = client.get(
            "/api/compound/market/state/period",
            params={
                "version": "v3",
                "market": "USDC",
                "start": "2026-03-10T00:00:00Z",
                "end": "2026-03-10T00:00:00Z",
                "interval": 0,
            },
        )
    assert resp.status_code == 400
    assert "interval" in resp.json()["detail"]


def test_market_state_period_invalid_time_order() -> None:
    with _build_client() as client:
        resp = client.get(
            "/api/compound/market/state/period",
            params={
                "version": "v3",
                "market": "USDC",
                "start": "2026-03-11T00:00:00Z",
                "end": "2026-03-10T00:00:00Z",
            },
        )
    assert resp.status_code == 400
    assert "start" in resp.json()["detail"]


def test_market_state_period_supports_v2() -> None:
    ts1 = datetime(2026, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
    rows = [
        {
            "timestamp": ts1,
            "market": bytes.fromhex("5d3a536e4d6dbd6114cc1ead35777bab948e3643"),
            "symbol": "cDAI",
            "total_supply": "100",
            "total_borrow": "20",
            "collateral_usd": "0",
            "utilization": "0.2",
            "borrow_rate": "0.01",
            "supply_rate": "0.005",
            "price_usd": "1",
            "supply_usd": "100",
            "borrow_usd": "20",
        }
    ]
    with _build_client(rows=rows) as client:
        resp = client.get(
            "/api/compound/market/state/period",
            params={
                "version": "v2",
                "market": "0x5d3a536e4d6dbd6114cc1ead35777bab948e3643",
                "start": "2026-03-10T00:00:00Z",
                "end": "2026-03-10T00:00:00Z",
                "interval": 24,
                "detail": "false",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["points"]) == 1
    assert data["points"][0]["version"] == "v2"


def test_market_state_period_path_version_removed() -> None:
    ts1 = datetime(2026, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
    rows = [
        {
            "timestamp": ts1,
            "market": bytes.fromhex("5d3a536e4d6dbd6114cc1ead35777bab948e3643"),
            "symbol": "cDAI",
            "total_supply": "100",
            "total_borrow": "20",
            "collateral_usd": "0",
            "utilization": "0.2",
            "borrow_rate": "0.01",
            "supply_rate": "0.005",
            "price_usd": "1",
            "supply_usd": "100",
            "borrow_usd": "20",
        }
    ]
    with _build_client(rows=rows) as client:
        resp = client.get(
            "/api/compound/v2/market/state/period",
            params={
                "market": "0x5d3a536e4d6dbd6114cc1ead35777bab948e3643",
                "start": "2026-03-10T00:00:00Z",
                "end": "2026-03-10T00:00:00Z",
                "interval": 24,
                "detail": "false",
            },
        )
    assert resp.status_code == 404
