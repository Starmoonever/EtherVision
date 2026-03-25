from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from compound_crawler.api import service


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    async def fetchrow(self, _sql, *_args):
        return self._row

    async def fetch(self, _sql, *_args):
        return self._rows


class _FakePool:
    def __init__(self, row=None, rows=None):
        self._conn = _FakeConn(row=row, rows=rows)

    def acquire(self):
        return _AcquireCtx(self._conn)


def _row() -> dict[str, object]:
    return {
        "market": bytes.fromhex("5d3a536e4d6dbd6114cc1ead35777bab948e3643"),
        "symbol": "cDAI",
        "effective_timestamp": datetime(2026, 3, 24, 0, 0, 0, tzinfo=timezone.utc),
        "block_number": 24723660,
        "config_hash": "abc123",
        "comptroller": bytes.fromhex("3d9819210a31b4961b30ef54be2aed79b9c9cd3b"),
        "interest_rate_model": bytes.fromhex(
            "0000000000000000000000000000000000000001"
        ),
        "underlying": bytes.fromhex("6b175474e89094c44da98b954eedeac495271d0f"),
        "underlying_symbol": "DAI",
        "ctoken_decimals": 8,
        "underlying_decimals": 18,
        "collateral_factor": Decimal("0.75"),
        "reserve_factor": Decimal("0.1"),
        "liquidation_threshold": None,
        "borrow_cap": Decimal("1000000"),
        "supply_cap": Decimal("2000000"),
        "is_listed": True,
        "is_comped": True,
        "is_deprecated": False,
        "raw_config_jsonb": {
            "protocol_config_hash": "p123",
            "mint_paused": False,
            "borrow_paused": True,
        },
    }


@pytest.mark.asyncio
async def test_get_v2_market_config_ok() -> None:
    response = await service.get_v2_market_config(
        pool=_FakePool(row=_row()),
        version="v2",
        market="cDAI",
    )
    assert response.version == "v2"
    assert response.market == "0x5d3a536e4d6dbd6114cc1ead35777bab948e3643"
    assert response.protocol_config_hash == "p123"
    assert response.borrow_paused is True


@pytest.mark.asyncio
async def test_get_v2_market_config_rejects_v3() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await service.get_v2_market_config(
            pool=_FakePool(row=_row()),
            version="v3",
            market="cDAI",
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_v2_market_config_period_ok() -> None:
    row1 = _row()
    row2 = {
        **_row(),
        "config_hash": "def456",
        "effective_timestamp": datetime(2026, 3, 25, 0, 0, 0, tzinfo=timezone.utc),
    }
    response = await service.get_v2_market_config_period(
        pool=_FakePool(rows=[row1, row2]),
        version="v2",
        market="cDAI",
        start="2026-03-24T00:00:00Z",
        end="2026-03-25T00:00:00Z",
    )
    assert [item.config_hash for item in response.points] == ["abc123", "def456"]
