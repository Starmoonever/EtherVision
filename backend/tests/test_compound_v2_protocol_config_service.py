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
        "effective_timestamp": datetime(2026, 3, 24, 0, 0, 0, tzinfo=timezone.utc),
        "block_number": 24723660,
        "config_hash": "p123",
        "comptroller": bytes.fromhex("3d9819210a31b4961b30ef54be2aed79b9c9cd3b"),
        "price_oracle": bytes.fromhex("922018674c12a7f0d394ebeef9b58f186cde13c1"),
        "close_factor": Decimal("0.5"),
        "liquidation_incentive": Decimal("1.08"),
        "pause_guardian": bytes.fromhex("1111111111111111111111111111111111111111"),
        "transfer_paused": False,
        "seize_paused": False,
        "mint_paused": False,
        "borrow_paused": True,
    }


@pytest.mark.asyncio
async def test_get_v2_protocol_config_ok() -> None:
    response = await service.get_v2_protocol_config(
        pool=_FakePool(row=_row()),
        version="v2",
    )
    assert response.version == "v2"
    assert response.config_hash == "p123"
    assert response.borrow_paused is True


@pytest.mark.asyncio
async def test_get_v2_protocol_config_rejects_v3() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await service.get_v2_protocol_config(
            pool=_FakePool(row=_row()),
            version="v3",
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_v2_protocol_config_period_ok() -> None:
    row1 = _row()
    row2 = {
        **_row(),
        "config_hash": "p456",
        "effective_timestamp": datetime(2026, 3, 25, 0, 0, 0, tzinfo=timezone.utc),
    }
    response = await service.get_v2_protocol_config_period(
        pool=_FakePool(rows=[row1, row2]),
        version="v2",
        start="2026-03-24T00:00:00Z",
        end="2026-03-25T00:00:00Z",
    )
    assert [item.config_hash for item in response.points] == ["p123", "p456"]
