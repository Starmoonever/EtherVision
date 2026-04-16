from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest

from aave_crawler.api import service


class _HistoryPool:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, _sql, *_args):
        return self._rows


@pytest.mark.asyncio
async def test_get_user_position_history_uses_shared_bucket_prices() -> None:
    pool = _HistoryPool(
        [
            {
                "token_symbol": "WETH",
                "token_addr": "0xC02AaA39B223FE8D0A0E5C4F27eAD9083C756Cc2",
                "supply_amount": Decimal("2"),
                "debt_amount": Decimal("0"),
            },
            {
                "token_symbol": "USDC",
                "token_addr": "0xA0b86991C6218B36C1d19D4a2E9Eb0cE3606eB48",
                "supply_amount": Decimal("0"),
                "debt_amount": Decimal("100"),
            },
        ]
    )
    at_time_ts = int(datetime(2024, 6, 1, 0, 7, 0, tzinfo=timezone.utc).timestamp())

    with patch.object(
        service,
        "get_historical_prices_usd",
        new=AsyncMock(
            return_value=(
                {
                    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": Decimal("2000"),
                },
                int(datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()),
                "defillama",
            )
        ),
    ) as price_helper:
        resp = await service.get_user_position_history(
            cast(asyncpg.Pool, pool),
            address="0x1234",
            at_time_ts=at_time_ts,
        )

    assert resp is not None
    assert resp.eth_price_usd == "2000.00"
    assert resp.eth_collateral_usd == "4000.00"
    assert resp.total_debt_approx_usd == "100.00"
    assert resp.liq_price == "60.61"
    price_helper.assert_awaited_once_with(
        cast(asyncpg.Pool, pool),
        assets=[
            ("0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "WETH"),
        ],
        requested_ts=at_time_ts,
    )


@pytest.mark.asyncio
async def test_get_positions_history_uses_shared_bucket_prices() -> None:
    pool = _HistoryPool(
        [
            {
                "address": "0xabc",
                "eth_amount": Decimal("1.5"),
                "token_symbol": "WETH",
                "token_addr": "0xC02AaA39B223FE8D0A0E5C4F27eAD9083C756Cc2",
                "debt_amount": Decimal("0.5"),
            },
            {
                "address": "0xabc",
                "eth_amount": Decimal("1.5"),
                "token_symbol": "USDC",
                "token_addr": "0xA0b86991C6218B36C1d19D4a2E9Eb0cE3606eB48",
                "debt_amount": Decimal("100"),
            },
        ]
    )
    at_time_ts = int(datetime(2024, 6, 1, 0, 7, 0, tzinfo=timezone.utc).timestamp())

    with patch.object(
        service,
        "get_historical_prices_usd",
        new=AsyncMock(
            return_value=(
                {
                    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": Decimal("1800"),
                },
                int(datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()),
                "defillama",
            )
        ),
    ) as price_helper:
        resp = await service.get_positions_history(
            cast(asyncpg.Pool, pool),
            at_time_ts=at_time_ts,
            limit=10,
        )

    assert len(resp) == 1
    assert resp[0].eth_price_usd == "1800.00"
    assert resp[0].eth_collateral_usd == "2700.00"
    assert resp[0].total_debt_approx_usd == "1000.00"
    assert resp[0].liq_price == "808.08"
    price_helper.assert_awaited_once_with(
        cast(asyncpg.Pool, pool),
        assets=[
            ("0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "WETH"),
        ],
        requested_ts=at_time_ts,
    )
