from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, cast

import pytest

from aave_crawler.api.service import simulate_liquidation_waterfall


class _MockPool:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, _sql, _day):
        return self._rows


def _rows_base():
    # 这个样本确保在初始冲击后可触发清算，并且可进入后续轮次。
    return [
        {
            "user_address": "0xabc",
            "total_debt_usd": Decimal("100"),
            "eth_collateral_amount": Decimal("1"),
            "liq_price": Decimal("100"),
            "health_factor": Decimal("1.02"),
            "eth_price_usd": Decimal("100"),
        }
    ]


@pytest.mark.asyncio
async def test_waterfall_no_cascade_when_impact_k_zero():
    pool = _MockPool(_rows_base())

    resp = await simulate_liquidation_waterfall(
        pool=cast(Any, pool),
        protocol="v3",
        snapshot_date=date(2026, 3, 10),
        initial_price_shock_eth=Decimal("0.05"),
        impact_k=Decimal("0"),
        sell_partition_eth=Decimal("0.7"),
    )

    assert resp.initial_decline == "0.05000000"
    assert resp.cascade_decline == "0.00000000"
    assert resp.total_decline == "0.05000000"
    assert int(resp.liquidation_turns_cnt) == 1


@pytest.mark.asyncio
async def test_waterfall_has_cascade_when_impact_k_positive():
    pool = _MockPool(_rows_base())

    resp = await simulate_liquidation_waterfall(
        pool=cast(Any, pool),
        protocol="v3",
        snapshot_date=date(2026, 3, 10),
        initial_price_shock_eth=Decimal("0.05"),
        impact_k=Decimal("0.4"),
        sell_partition_eth=Decimal("1"),
    )

    assert Decimal(resp.cascade_decline) > Decimal("0")
    assert Decimal(resp.total_decline) > Decimal(resp.initial_decline)
    assert int(resp.liquidation_turns_cnt) >= 1
    # turn[0] 应表示 initial shock 后第一轮清算
    assert resp.liquidation_turns[0].eth_price_decline == resp.initial_decline


@pytest.mark.asyncio
async def test_total_liquidation_accounts_equals_sum_of_turns():
    pool = _MockPool(_rows_base())

    resp = await simulate_liquidation_waterfall(
        pool=cast(Any, pool),
        protocol="v3",
        snapshot_date=date(2026, 3, 10),
        initial_price_shock_eth=Decimal("0.05"),
        impact_k=Decimal("0.2"),
        sell_partition_eth=Decimal("1"),
    )

    turns_sum = sum(int(t.liquidation_accounts) for t in resp.liquidation_turns)
    assert int(resp.total_liquidation_accounts) == turns_sum


@pytest.mark.asyncio
async def test_waterfall_unsupported_protocol_raises():
    pool = _MockPool(_rows_base())

    with pytest.raises(ValueError):
        await simulate_liquidation_waterfall(
            pool=cast(Any, pool),
            protocol="v2",
            snapshot_date=date(2026, 3, 10),
            initial_price_shock_eth=Decimal("0.05"),
            impact_k=Decimal("0.4"),
            sell_partition_eth=Decimal("1"),
        )
