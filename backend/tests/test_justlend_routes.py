from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from justlend_crawler.database import get_pool
from starlette.testclient import TestClient

from justlend_crawler.api.routes import router as justlend_router


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self, market_rows=None, state_row=None, period_rows=None):
        self._market_rows = market_rows or []
        self._state_row = state_row
        self._period_rows = period_rows or []

    async def fetchrow(self, sql, *_args):
        if "FROM loan.justlend_markets_current" in sql:
            return self._state_row
        if "FROM loan.justlend_market_snapshots" in sql:
            return self._state_row
        return None

    async def fetch(self, sql, *_args):
        if "FROM loan.justlend_markets_current" in sql:
            return self._market_rows
        if "FROM loan.justlend_market_snapshots" in sql:
            return self._period_rows
        return []


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


def _build_client(
    *,
    market_rows=None,
    state_row=None,
    period_rows=None,
) -> TestClient:
    app = FastAPI()
    app.include_router(justlend_router)
    fake_conn = _FakeConn(
        market_rows=market_rows,
        state_row=state_row,
        period_rows=period_rows,
    )
    fake_pool = _FakePool(fake_conn)

    async def _override_pool():
        return fake_pool

    app.dependency_overrides[get_pool] = _override_pool
    return TestClient(app)


def _market_row(ts: datetime) -> dict[str, object]:
    return {
        "market_address": "TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd",
        "chain": "tron",
        "protocol": "justlend",
        "market_type": "jtoken",
        "underlying_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        "comptroller_address": "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf",
        "oracle_address": "THU4n2tqUj4VYvFsxQ3PzotwqjKXqV7Ywz",
        "symbol": "jUSDT",
        "underlying_symbol": "USDT",
        "underlying_decimals": 6,
        "jtoken_decimals": 8,
        "is_listed": True,
        "is_entered_supported": True,
        "collateral_factor": "0.8",
        "reserve_factor": "0.1",
        "borrow_cap": None,
        "supply_cap": None,
        "exchange_rate": "1.023",
        "cash": "1200",
        "total_borrows": "300",
        "total_reserves": "20",
        "total_supply": "1480",
        "utilization": "0.2",
        "borrow_rate": "0.01",
        "supply_rate": "0.004",
        "underlying_price_in_trx": "0.35",
        "price_usd": "1",
        "snapshot_at": ts,
        "block_timestamp": ts,
        "block_number": 12345678,
        "extra_jsonb": {"source": "test"},
        "created_at": ts,
        "updated_at": ts,
    }


def test_status_route_returns_scaffold_metadata() -> None:
    with _build_client() as client:
        response = client.get("/api/justlend/status")

    assert response.status_code == 200
    assert response.json() == {
        "module": "justlend",
        "status": "scaffold",
        "chain": "tron",
        "supported_protocols": ["trx"],
        "message": "JustLend backend scaffold is wired into the unified API. Data collection and query logic are pending.",
    }


def test_markets_route_returns_market_list() -> None:
    ts = datetime(2026, 4, 16, 8, 0, 0, tzinfo=timezone.utc)
    with _build_client(market_rows=[_market_row(ts)]) as client:
        response = client.get("/api/justlend/markets")

    assert response.status_code == 200
    assert response.json() == {
        "chain": "tron",
        "markets": [
            {
                "market": "TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd",
                "symbol": "jUSDT",
                "underlying_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
                "underlying_symbol": "USDT",
                "updated_at": "2026-04-16T08:00:00Z",
            }
        ],
    }


def test_market_state_route_returns_latest_row() -> None:
    ts = datetime(2026, 4, 16, 8, 0, 0, tzinfo=timezone.utc)
    with _build_client(state_row=_market_row(ts)) as client:
        response = client.get(
            "/api/justlend/market/state",
            params={"market": "TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["market"] == "TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd"
    assert payload["symbol"] == "jUSDT"
    assert payload["underlying_symbol"] == "USDT"
    assert payload["price_usd"] == "1.00000000"
    assert payload["timestamp"] == "2026-04-16T08:00:00Z"


def test_market_state_route_parses_stringified_extra_jsonb() -> None:
    ts = datetime(2026, 4, 16, 8, 0, 0, tzinfo=timezone.utc)
    row = _market_row(ts)
    row["extra_jsonb"] = '{"source":"justlend_market_api_rpc","rpc_available":true}'
    with _build_client(state_row=row) as client:
        response = client.get(
            "/api/justlend/market/state",
            params={"market": "TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["extra"] == {
        "source": "justlend_market_api_rpc",
        "rpc_available": True,
    }


def test_market_state_period_route_returns_points() -> None:
    ts1 = datetime(2026, 4, 16, 8, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)
    row1 = _market_row(ts1)
    row2 = _market_row(ts2)
    row2["cash"] = "1500"
    with _build_client(period_rows=[row1, row2]) as client:
        response = client.get(
            "/api/justlend/market/state/period",
            params={
                "market": "TXJgMdjVX5dKiQaUi9QobwNxtSQaFqccvd",
                "start": "2026-04-16T08:00:00Z",
                "end": "2026-04-16T09:00:00Z",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["points"]) == 2
    assert data["points"][0]["cash"] == "1200.000000000000000000"
    assert data["points"][1]["cash"] == "1500.000000000000000000"


def test_position_route_requires_address() -> None:
    with _build_client() as client:
        response = client.get(
            "/api/justlend/position",
            params={"protocol": "trx"},
        )

    assert response.status_code == 422
