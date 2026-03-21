from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest

from compound_crawler.config import AppConfig
from compound_crawler.user_position_snapshots import (
    BackfillStats,
    UserPositionAssetRow,
    UserPositionSnapshotRow,
    iter_snapshot_points,
    parse_csv_address_cell,
    run_user_position_backfill,
    _solve_eth_liq_prices,
)


def test_parse_csv_address_cell_bytes_repr() -> None:
    raw = r"""b'\x00\x1f\xf1\xc2X \x9an3\xea\xf8P\xdaO\x90\x808l\x0c;'"""
    parsed = parse_csv_address_cell(raw)
    assert parsed.hex() == "001ff1c258209a6e33eaf850da4f9080386c0c3b"


def test_parse_csv_address_cell_hex() -> None:
    parsed = parse_csv_address_cell("0x123400000000000000000000000000000000abcd")
    assert parsed.hex() == "123400000000000000000000000000000000abcd"


def test_iter_snapshot_points_daily() -> None:
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end = datetime(2026, 3, 3, tzinfo=timezone.utc)
    points = iter_snapshot_points(start, end, 1)
    assert points == [
        datetime(2026, 3, 1, tzinfo=timezone.utc),
        datetime(2026, 3, 2, tzinfo=timezone.utc),
        datetime(2026, 3, 3, tzinfo=timezone.utc),
    ]


def test_solve_eth_liq_prices_downside() -> None:
    down, up, mode = _solve_eth_liq_prices(
        eth_price_usd=Decimal("3000"),
        discounted_eth_collateral_usd=Decimal("1200"),
        eth_debt_usd=Decimal("0"),
        discounted_stable_collateral_usd=Decimal("0"),
        stable_debt_usd=Decimal("1000"),
    )
    assert down == Decimal("2500")
    assert up is None
    assert mode == "down"


def test_solve_eth_liq_prices_upside() -> None:
    down, up, mode = _solve_eth_liq_prices(
        eth_price_usd=Decimal("3000"),
        discounted_eth_collateral_usd=Decimal("800"),
        eth_debt_usd=Decimal("1000"),
        discounted_stable_collateral_usd=Decimal("400"),
        stable_debt_usd=Decimal("0"),
    )
    assert down is None
    assert up == Decimal("6000")
    assert mode == "up"


def test_iter_snapshot_points_rejects_subdaily_interval() -> None:
    with pytest.raises(ValueError):
        iter_snapshot_points(
            datetime(2026, 3, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 2, tzinfo=timezone.utc),
            0,
        )


def test_backfill_stats_tracks_skipped_empty() -> None:
    stats = BackfillStats()
    stats.skipped_empty += 3
    assert stats.skipped_empty == 3


@pytest.mark.asyncio
async def test_run_user_position_backfill_flushes_in_batches() -> None:
    cfg = AppConfig()
    cfg.crawler.batch_size = 1
    cfg.market_state.use_timescaledb = False

    snapshot_row = UserPositionSnapshotRow(
        timestamp=datetime(2026, 3, 1, tzinfo=timezone.utc),
        block_number=123,
        market=bytes.fromhex("a17581a9e3356d9a858b789d68b4d866e593ae94"),
        symbol="WETH",
        user_address=bytes.fromhex("11" * 20),
        has_open_position=True,
        is_liquidatable=False,
        base_token=bytes.fromhex("c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"),
        base_symbol="WETH",
        base_price_usd=Decimal("2000"),
        eth_price_usd=Decimal("2000"),
        total_collateral_usd=Decimal("3000"),
        total_debt_usd=Decimal("1000"),
        discounted_collateral_usd=Decimal("2500"),
        liquidation_buffer_usd=Decimal("1500"),
        health_factor=Decimal("2.5"),
        eth_sensitive_collateral_usd=Decimal("3000"),
        eth_sensitive_debt_usd=Decimal("1000"),
        net_eth_exposure_usd=Decimal("2000"),
        non_eth_collateral_usd=Decimal("0"),
        non_eth_debt_usd=Decimal("0"),
        basis_risk_collateral_usd=Decimal("0"),
        eth_down_liq_price_usd=Decimal("1200"),
        eth_up_liq_price_usd=None,
        eth_liq_mode="down",
        dominant_risk="eth_down",
        assets_jsonb=[],
    )
    asset_row = UserPositionAssetRow(
        timestamp=datetime(2026, 3, 1, tzinfo=timezone.utc),
        block_number=123,
        market=bytes.fromhex("a17581a9e3356d9a858b789d68b4d866e593ae94"),
        user_address=bytes.fromhex("11" * 20),
        asset=bytes.fromhex("c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"),
        symbol="WETH",
        side="base_supply",
        decimals=18,
        amount=Decimal("1"),
        price_in_base=Decimal("1"),
        price_usd=Decimal("2000"),
        value_usd=Decimal("2000"),
        discounted_value_usd=Decimal("1800"),
        borrow_collateral_factor=None,
        liquidate_collateral_factor=None,
        liquidation_factor=None,
        beta_to_eth=Decimal("1"),
        is_eth_correlated=True,
        is_basis_risk_asset=False,
    )

    async def _fake_flush(pool, *, snapshot_rows, asset_rows, stats):
        _ = pool
        stats.snapshots += len(snapshot_rows)
        stats.assets += len(asset_rows)

    with (
        patch(
            "compound_crawler.user_position_snapshots.ensure_user_position_snapshot_tables",
            new=AsyncMock(),
        ),
        patch(
            "compound_crawler.user_position_snapshots._build_web3",
            new=AsyncMock(return_value=object()),
        ),
        patch(
            "compound_crawler.user_position_snapshots._block_at_timestamp",
            new=AsyncMock(side_effect=[111, 222]),
        ),
        patch(
            "compound_crawler.user_position_snapshots._load_users_from_csv",
            return_value=[bytes.fromhex("11" * 20)],
        ),
        patch("pathlib.Path.exists", return_value=True),
        patch(
            "compound_crawler.user_position_snapshots._collect_market_point",
            new=AsyncMock(
                side_effect=[
                    ([snapshot_row], [asset_row]),
                    ([snapshot_row], [asset_row]),
                ]
            ),
        ),
        patch(
            "compound_crawler.user_position_snapshots._flush_backfill_write_batch",
            new=AsyncMock(side_effect=_fake_flush),
        ) as mocked_flush,
    ):
        stats = await run_user_position_backfill(
            cfg,
            pool=cast(asyncpg.Pool, object()),
            markets=["weth"],
            derived_users_dir=Path("."),
            start=datetime(2026, 3, 1, tzinfo=timezone.utc),
            end=datetime(2026, 3, 2, tzinfo=timezone.utc),
            interval_days=1,
            skip_existing=False,
            dry_run=False,
        )

    assert stats.snapshots == 2
    assert stats.assets == 2
    mocked_flush.assert_awaited_once()
