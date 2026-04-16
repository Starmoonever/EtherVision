from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
from web3 import AsyncWeb3

from morpho_crawler.api.service import (
    _build_group_brief,
    get_position_replay,
)
from morpho_crawler.rpc import MorphoReplayEvent, MorphoRealtimePosition, TokenMetadata


def _mock_position(block_number: int = 123) -> MorphoRealtimePosition:
    return MorphoRealtimePosition(
        morpho_address="0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb",
        market_id="0x" + "11" * 32,
        user_address="0xaAaAaAaaAaAaAaaAaAAAAAAAAaaaAaAaAaaAaaAa",
        block_number=block_number,
        block_timestamp=datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
        loan_token=TokenMetadata(
            address="0x1111111111111111111111111111111111111111",
            symbol="USDC",
            decimals=6,
        ),
        collateral_token=TokenMetadata(
            address="0x2222222222222222222222222222222222222222",
            symbol="wstETH",
            decimals=18,
        ),
        oracle="0x3333333333333333333333333333333333333333",
        irm="0x4444444444444444444444444444444444444444",
        lltv=86 * 10**16,
        supply_shares=0,
        borrow_shares=1000,
        collateral_raw=2 * 10**18,
        supply_assets_raw=0,
        borrow_assets_raw=1_250_000,
        collateral_value_in_loan_asset_raw=3_000_000,
        max_borrowable_raw=2_580_000,
        health_factor=Decimal("2.064"),
        is_healthy=True,
        has_position=True,
        price_raw=1_500_000_000_000_000_000_000_000,
    )


@pytest.mark.asyncio
async def test_get_position_replay_prefers_cache_when_rows_exist() -> None:
    cached_row = {
        "tx_hash": "0xabc",
        "block_timestamp": datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
        "block_number": 123,
        "operation_type": "borrow",
        "brief": "借入 1.25 USDC",
        "has_position": True,
        "is_healthy": True,
        "collateral_value_in_loan_asset": Decimal("3"),
        "borrow_assets": Decimal("1.25"),
        "health_factor": Decimal("2.064"),
        "assets_jsonb": [],
    }
    with (
        patch(
            "morpho_crawler.api.service.fetch_position_replay_snapshots",
            new_callable=AsyncMock,
            return_value=[cached_row],
        ),
        patch(
            "morpho_crawler.api.service.fetch_user_market_replay_events",
            new_callable=AsyncMock,
        ) as fetch_events,
    ):
        response = await get_position_replay(
            cast(AsyncWeb3, object()),
            pool=cast(asyncpg.Pool, object()),
            address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            market_id="0x" + "11" * 32,
            protocol="blue",
            from_ts=int(datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc).timestamp()),
            to_ts=int(datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc).timestamp()),
        )

    assert response.data_source == "cache"
    assert response.total_points == 1
    fetch_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_position_replay_builds_rpc_snapshots_and_writes_cache() -> None:
    events = [
        MorphoReplayEvent(
            tx_hash="0xabc",
            log_index=1,
            block_number=123,
            block_timestamp=datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
            operation_type="supply_collateral",
            collateral_assets=2 * 10**18,
        ),
        MorphoReplayEvent(
            tx_hash="0xabc",
            log_index=2,
            block_number=123,
            block_timestamp=datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
            operation_type="borrow",
            assets=1_250_000,
            shares=1000,
        ),
    ]
    with (
        patch(
            "morpho_crawler.api.service.fetch_position_replay_snapshots",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "morpho_crawler.api.service.fetch_user_market_replay_events",
            new_callable=AsyncMock,
            return_value=events,
        ),
        patch(
            "morpho_crawler.api.service.fetch_position_at_block",
            new_callable=AsyncMock,
            return_value=_mock_position(),
        ),
        patch(
            "morpho_crawler.api.service.get_historical_prices_usd",
            new_callable=AsyncMock,
            return_value=(
                {
                    "0x1111111111111111111111111111111111111111": Decimal("1.00"),
                    "0x2222222222222222222222222222222222222222": Decimal("1500.00"),
                },
                1_711_929_600,
                "defillama",
            ),
        ) as get_hist_prices,
        patch(
            "morpho_crawler.api.service.upsert_position_replay_snapshots",
            new_callable=AsyncMock,
        ) as upsert_replay,
        patch(
            "morpho_crawler.api.service.upsert_market",
            new_callable=AsyncMock,
        ),
    ):
        response = await get_position_replay(
            cast(AsyncWeb3, object()),
            pool=cast(asyncpg.Pool, object()),
            address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            market_id="0x" + "11" * 32,
            protocol="blue",
            from_ts=int(datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc).timestamp()),
            to_ts=int(datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc).timestamp()),
            detail=True,
        )

    assert response.data_source == "rpc"
    assert response.total_points == 1
    assert response.points[0].operation_type == "batch"
    assert (
        response.points[0].brief
        == "新增抵押 2 wstETH (价值 3000.00 usd)；借入 1.25 USDC (价值 1.25 usd)"
    )
    assert response.points[0].assets[0].price_usd == "1.00"
    assert response.points[0].assets[1].price_usd == "1500.00"
    get_hist_prices.assert_awaited_once()
    upsert_replay.assert_awaited_once()


def test_build_group_brief_combines_and_deduplicates_event_briefs() -> None:
    operation_type, brief = _build_group_brief(
        [
            MorphoReplayEvent(
                tx_hash="0xabc",
                log_index=1,
                block_number=1,
                block_timestamp=datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
                operation_type="borrow",
                assets=1_250_000,
            ),
            MorphoReplayEvent(
                tx_hash="0xabc",
                log_index=2,
                block_number=1,
                block_timestamp=datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
                operation_type="borrow",
                assets=1_250_000,
            ),
        ],
        loan_symbol="USDC",
        collateral_symbol="wstETH",
        loan_decimals=6,
        collateral_decimals=18,
        loan_price_usd=Decimal("1"),
        collateral_price_usd=Decimal("1500"),
    )

    assert operation_type == "borrow"
    assert brief == "借入 1.25 USDC (价值 1.25 usd)"
