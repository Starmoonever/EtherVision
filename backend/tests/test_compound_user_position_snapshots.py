from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from compound_crawler.user_position_snapshots import (
    BackfillStats,
    iter_snapshot_points,
    parse_csv_address_cell,
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
