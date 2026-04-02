from __future__ import annotations

from datetime import date
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from typing import cast

import asyncpg
import pytest

from compound_crawler.db import (
    UserPositionAssetRow,
    UserPositionSnapshotRow,
    activate_compound_v2_users,
    activate_compound_v2_users_with_event_rows,
    ensure_compound_v2_current_position_tables,
    ensure_compound_v3_current_position_tables,
    fetch_compound_v2_run_watermark,
    fetch_compound_v2_active_users,
    fetch_compound_v2_current_positions,
    fetch_compound_v3_current_positions,
    fetch_compound_v2_users_from_detail_tables_day,
    fetch_compound_v2_users_from_history_day,
    fetch_compound_v2_users_affected_by_events,
    refresh_compound_v2_current_positions,
    refresh_compound_v3_current_positions,
    refresh_compound_v2_active_users_from_snapshots,
    upsert_compound_v2_run_watermark,
)


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _TransactionCtx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self):
        self.fetch_rows = []
        self.fetch_results: list[list[dict[str, Any]]] = []
        self.fetchrow_result: Any | None = None
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []
        self.executemany_calls: list[tuple[str, list[tuple[object, ...]]]] = []

    async def fetch(self, _sql: str, *_args):
        if self.fetch_results:
            return self.fetch_results.pop(0)
        return self.fetch_rows

    async def executemany(self, sql: str, rows: list[tuple[object, ...]]):
        self.executemany_calls.append((sql, rows))

    async def fetchrow(self, _sql: str, *_args):
        return self.fetchrow_result

    async def execute(self, sql: str, *args):
        self.execute_calls.append((sql, args))

    def transaction(self):
        return _TransactionCtx()


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


@pytest.mark.asyncio
async def test_fetch_compound_v2_active_users_returns_addresses() -> None:
    conn = _FakeConn()
    conn.fetch_rows = [
        {"user_address": bytes.fromhex("11" * 20)},
        {"user_address": bytes.fromhex("22" * 20)},
    ]

    rows = await fetch_compound_v2_active_users(cast(asyncpg.Pool, _FakePool(conn)))

    assert rows == [bytes.fromhex("11" * 20), bytes.fromhex("22" * 20)]


@pytest.mark.asyncio
async def test_activate_compound_v2_users_deduplicates_addresses() -> None:
    conn = _FakeConn()
    user = bytes.fromhex("11" * 20)

    inserted = await activate_compound_v2_users(
        cast(asyncpg.Pool, _FakePool(conn)),
        [user, user],
        event_timestamp=datetime(2026, 3, 26, tzinfo=timezone.utc),
    )

    assert inserted == 1
    assert len(conn.executemany_calls) == 1
    assert len(conn.executemany_calls[0][1]) == 1


@pytest.mark.asyncio
async def test_refresh_compound_v2_active_users_from_snapshots_aggregates_per_user() -> (
    None
):
    conn = _FakeConn()
    point_ts = datetime(2026, 3, 26, tzinfo=timezone.utc)
    user_address = bytes.fromhex("11" * 20)
    market_a = bytes.fromhex("aa" * 20)
    market_b = bytes.fromhex("bb" * 20)
    base_token = bytes.fromhex("cc" * 20)

    rows = [
        UserPositionSnapshotRow(
            timestamp=point_ts,
            block_number=1,
            market=market_a,
            symbol="cDAI",
            user_address=user_address,
            has_open_position=True,
            is_liquidatable=False,
            base_token=base_token,
            base_symbol="DAI",
            base_price_usd=Decimal("1"),
            eth_price_usd=Decimal("3000"),
            total_collateral_usd=Decimal("100"),
            total_debt_usd=Decimal("0"),
            discounted_collateral_usd=Decimal("80"),
            liquidation_buffer_usd=Decimal("80"),
            health_factor=Decimal("1000000000000000000"),
            eth_sensitive_collateral_usd=Decimal("0"),
            eth_sensitive_debt_usd=Decimal("0"),
            net_eth_exposure_usd=Decimal("0"),
            non_eth_collateral_usd=Decimal("100"),
            non_eth_debt_usd=Decimal("0"),
            basis_risk_collateral_usd=Decimal("0"),
            eth_down_liq_price_usd=None,
            eth_up_liq_price_usd=None,
            eth_liq_mode="neutral",
            dominant_risk="neutral",
            assets_jsonb=[],
        ),
        UserPositionSnapshotRow(
            timestamp=point_ts,
            block_number=1,
            market=market_b,
            symbol="cUSDC",
            user_address=user_address,
            has_open_position=False,
            is_liquidatable=False,
            base_token=base_token,
            base_symbol="USDC",
            base_price_usd=Decimal("1"),
            eth_price_usd=Decimal("3000"),
            total_collateral_usd=Decimal("0"),
            total_debt_usd=Decimal("0"),
            discounted_collateral_usd=Decimal("0"),
            liquidation_buffer_usd=Decimal("0"),
            health_factor=Decimal("0"),
            eth_sensitive_collateral_usd=Decimal("0"),
            eth_sensitive_debt_usd=Decimal("0"),
            net_eth_exposure_usd=Decimal("0"),
            non_eth_collateral_usd=Decimal("0"),
            non_eth_debt_usd=Decimal("0"),
            basis_risk_collateral_usd=Decimal("0"),
            eth_down_liq_price_usd=None,
            eth_up_liq_price_usd=None,
            eth_liq_mode="neutral",
            dominant_risk="neutral",
            assets_jsonb=[],
        ),
    ]

    updated = await refresh_compound_v2_active_users_from_snapshots(
        cast(asyncpg.Pool, _FakePool(conn)),
        rows,
        point_ts=point_ts,
    )

    assert updated == 1
    assert len(conn.executemany_calls) == 1
    payload = conn.executemany_calls[0][1][0]
    assert payload[0] == user_address
    assert payload[1] is True
    assert payload[4] == point_ts
    assert payload[7] == Decimal("100")


@pytest.mark.asyncio
async def test_fetch_compound_v2_users_affected_by_events_returns_addresses() -> None:
    conn = _FakeConn()
    conn.fetch_rows = [
        {
            "user_address": bytes.fromhex("11" * 20),
            "last_event_at": datetime(2026, 3, 26, tzinfo=timezone.utc),
        },
        {
            "user_address": bytes.fromhex("22" * 20),
            "last_event_at": datetime(2026, 3, 26, tzinfo=timezone.utc),
        },
    ]

    rows = await fetch_compound_v2_users_affected_by_events(
        cast(asyncpg.Pool, _FakePool(conn)),
        from_dt=datetime(2026, 3, 25, tzinfo=timezone.utc),
        to_dt=datetime(2026, 3, 26, tzinfo=timezone.utc),
    )

    assert rows == [bytes.fromhex("11" * 20), bytes.fromhex("22" * 20)]


@pytest.mark.asyncio
async def test_fetch_compound_v2_users_from_history_day_returns_addresses_with_ts() -> (
    None
):
    conn = _FakeConn()
    ts_a = datetime(2019, 5, 7, 11, 0, 0, tzinfo=timezone.utc)
    ts_b = datetime(2019, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
    conn.fetch_rows = [
        {"user_address": bytes.fromhex("11" * 20), "last_event_at": ts_a},
        {"user_address": bytes.fromhex("22" * 20), "last_event_at": ts_b},
    ]

    rows = await fetch_compound_v2_users_from_history_day(
        cast(asyncpg.Pool, _FakePool(conn)),
        day_start=datetime(2019, 5, 7, 0, 0, 0, tzinfo=timezone.utc),
        day_end=datetime(2019, 5, 7, 23, 59, 59, tzinfo=timezone.utc),
    )

    assert rows == [
        (bytes.fromhex("11" * 20), ts_a),
        (bytes.fromhex("22" * 20), ts_b),
    ]


@pytest.mark.asyncio
async def test_fetch_compound_v2_users_from_detail_tables_day_returns_addresses_with_ts() -> (
    None
):
    conn = _FakeConn()
    ts_a = datetime(2019, 5, 7, 11, 0, 0, tzinfo=timezone.utc)
    ts_b = datetime(2019, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
    conn.fetch_rows = [
        {"user_address": bytes.fromhex("33" * 20), "last_event_at": ts_a},
        {"user_address": bytes.fromhex("44" * 20), "last_event_at": ts_b},
    ]

    rows = await fetch_compound_v2_users_from_detail_tables_day(
        cast(asyncpg.Pool, _FakePool(conn)),
        day_start=datetime(2019, 5, 7, 0, 0, 0, tzinfo=timezone.utc),
        day_end=datetime(2019, 5, 7, 23, 59, 59, tzinfo=timezone.utc),
    )

    assert rows == [
        (bytes.fromhex("33" * 20), ts_a),
        (bytes.fromhex("44" * 20), ts_b),
    ]


@pytest.mark.asyncio
async def test_activate_compound_v2_users_with_event_rows_dedup_keeps_latest() -> None:
    conn = _FakeConn()
    user = bytes.fromhex("11" * 20)
    ts_old = datetime(2019, 5, 7, 10, 0, 0, tzinfo=timezone.utc)
    ts_new = datetime(2019, 5, 7, 20, 0, 0, tzinfo=timezone.utc)

    inserted = await activate_compound_v2_users_with_event_rows(
        cast(asyncpg.Pool, _FakePool(conn)),
        [(user, ts_old), (user, ts_new)],
    )

    assert inserted == 1
    assert len(conn.executemany_calls) == 1
    payload = conn.executemany_calls[0][1][0]
    assert payload[0] == user
    assert payload[2] == ts_new
    assert payload[3] == ts_new


@pytest.mark.asyncio
async def test_compound_v2_run_watermark_roundtrip() -> None:
    conn = _FakeConn()
    conn.fetchrow_result = {"last_processed_date": date(2019, 5, 7)}
    pool = cast(asyncpg.Pool, _FakePool(conn))

    await upsert_compound_v2_run_watermark(
        pool,
        runner_name="runner-a",
        processed_date=date(2019, 5, 8),
    )
    watermark = await fetch_compound_v2_run_watermark(
        pool,
        runner_name="runner-a",
    )

    assert watermark == date(2019, 5, 7)
    assert len(conn.execute_calls) == 1


@pytest.mark.asyncio
async def test_ensure_compound_v3_current_position_tables_executes_ddl() -> None:
    conn = _FakeConn()

    await ensure_compound_v3_current_position_tables(
        cast(asyncpg.Pool, _FakePool(conn))
    )

    assert len(conn.execute_calls) == 6


@pytest.mark.asyncio
async def test_ensure_compound_v2_current_position_tables_executes_ddl() -> None:
    conn = _FakeConn()

    await ensure_compound_v2_current_position_tables(
        cast(asyncpg.Pool, _FakePool(conn))
    )

    assert len(conn.execute_calls) == 6


@pytest.mark.asyncio
async def test_refresh_compound_v3_current_positions_replaces_open_rows() -> None:
    conn = _FakeConn()
    conn.fetch_results = [[]]
    pool = cast(asyncpg.Pool, _FakePool(conn))
    ts = datetime(2026, 3, 27, 0, 0, 0, tzinfo=timezone.utc)
    market = bytes.fromhex("aa" * 20)
    user = bytes.fromhex("11" * 20)
    base_token = bytes.fromhex("22" * 20)
    asset = bytes.fromhex("33" * 20)

    touched = await refresh_compound_v3_current_positions(
        pool,
        snapshot_rows=[
            UserPositionSnapshotRow(
                timestamp=ts,
                block_number=100,
                market=market,
                symbol="USDC",
                user_address=user,
                has_open_position=True,
                is_liquidatable=False,
                base_token=base_token,
                base_symbol="USDC",
                base_price_usd=Decimal("1"),
                eth_price_usd=Decimal("3000"),
                total_collateral_usd=Decimal("100"),
                total_debt_usd=Decimal("25"),
                discounted_collateral_usd=Decimal("80"),
                liquidation_buffer_usd=Decimal("55"),
                health_factor=Decimal("3.2"),
                eth_sensitive_collateral_usd=Decimal("0"),
                eth_sensitive_debt_usd=Decimal("0"),
                net_eth_exposure_usd=Decimal("0"),
                non_eth_collateral_usd=Decimal("100"),
                non_eth_debt_usd=Decimal("25"),
                basis_risk_collateral_usd=Decimal("0"),
                eth_down_liq_price_usd=None,
                eth_up_liq_price_usd=None,
                eth_liq_mode="neutral",
                dominant_risk="neutral",
                assets_jsonb=[{"symbol": "USDC"}],
            )
        ],
        asset_rows=[
            UserPositionAssetRow(
                timestamp=ts,
                block_number=100,
                market=market,
                user_address=user,
                asset=asset,
                symbol="USDC",
                side="base_supply",
                decimals=6,
                amount=Decimal("100"),
                price_in_base=Decimal("1"),
                price_usd=Decimal("1"),
                value_usd=Decimal("100"),
                discounted_value_usd=Decimal("80"),
                borrow_collateral_factor=Decimal("0.8"),
                liquidate_collateral_factor=Decimal("0.85"),
                liquidation_factor=Decimal("0.92"),
                beta_to_eth=Decimal("0"),
                is_eth_correlated=False,
                is_basis_risk_asset=False,
            )
        ],
    )

    assert touched == 1
    assert len(conn.execute_calls) == 1
    assert len(conn.executemany_calls) == 2
    assert conn.executemany_calls[0][1][0][0] == market
    assert conn.executemany_calls[0][1][0][1] == user
    assert conn.executemany_calls[1][1][0][0] == market
    assert conn.executemany_calls[1][1][0][1] == user
    assert conn.executemany_calls[1][1][0][2] == asset


@pytest.mark.asyncio
async def test_refresh_compound_v2_current_positions_replaces_open_rows() -> None:
    conn = _FakeConn()
    conn.fetch_results = [[]]
    pool = cast(asyncpg.Pool, _FakePool(conn))
    ts = datetime(2026, 3, 27, 0, 0, 0, tzinfo=timezone.utc)
    market = bytes.fromhex("aa" * 20)
    user = bytes.fromhex("11" * 20)
    base_token = bytes.fromhex("22" * 20)
    asset = bytes.fromhex("33" * 20)

    touched = await refresh_compound_v2_current_positions(
        pool,
        snapshot_rows=[
            UserPositionSnapshotRow(
                timestamp=ts,
                block_number=100,
                market=market,
                symbol="cETH",
                user_address=user,
                has_open_position=True,
                is_liquidatable=False,
                base_token=base_token,
                base_symbol="WETH",
                base_price_usd=Decimal("3000"),
                eth_price_usd=Decimal("3000"),
                total_collateral_usd=Decimal("100"),
                total_debt_usd=Decimal("25"),
                discounted_collateral_usd=Decimal("80"),
                liquidation_buffer_usd=Decimal("55"),
                health_factor=Decimal("3.2"),
                eth_sensitive_collateral_usd=Decimal("100"),
                eth_sensitive_debt_usd=Decimal("25"),
                net_eth_exposure_usd=Decimal("75"),
                non_eth_collateral_usd=Decimal("0"),
                non_eth_debt_usd=Decimal("0"),
                basis_risk_collateral_usd=Decimal("0"),
                eth_down_liq_price_usd=Decimal("1800"),
                eth_up_liq_price_usd=None,
                eth_liq_mode="down",
                dominant_risk="eth_down",
                assets_jsonb=[{"symbol": "WETH"}],
            )
        ],
        asset_rows=[
            UserPositionAssetRow(
                timestamp=ts,
                block_number=100,
                market=market,
                user_address=user,
                asset=asset,
                symbol="WETH",
                side="collateral",
                decimals=None,
                amount=Decimal("1"),
                price_in_base=None,
                price_usd=Decimal("3000"),
                value_usd=Decimal("3000"),
                discounted_value_usd=Decimal("2400"),
                borrow_collateral_factor=None,
                liquidate_collateral_factor=None,
                liquidation_factor=None,
                beta_to_eth=Decimal("1"),
                is_eth_correlated=True,
                is_basis_risk_asset=False,
            )
        ],
    )

    assert touched == 1
    assert len(conn.execute_calls) == 1
    assert len(conn.executemany_calls) == 2
    assert conn.executemany_calls[0][1][0][0] == market
    assert conn.executemany_calls[0][1][0][1] == user
    assert conn.executemany_calls[1][1][0][0] == market
    assert conn.executemany_calls[1][1][0][1] == user
    assert conn.executemany_calls[1][1][0][2] == asset


@pytest.mark.asyncio
async def test_refresh_compound_v3_current_positions_skips_stale_rows() -> None:
    conn = _FakeConn()
    ts_existing = datetime(2026, 3, 27, 0, 0, 1, tzinfo=timezone.utc)
    market = bytes.fromhex("aa" * 20)
    user = bytes.fromhex("11" * 20)
    conn.fetch_results = [
        [
            {
                "market": market,
                "user_address": user,
                "last_block_number": 200,
                "last_block_timestamp": ts_existing,
            }
        ]
    ]

    touched = await refresh_compound_v3_current_positions(
        cast(asyncpg.Pool, _FakePool(conn)),
        snapshot_rows=[
            UserPositionSnapshotRow(
                timestamp=datetime(2026, 3, 27, 0, 0, 0, tzinfo=timezone.utc),
                block_number=100,
                market=market,
                symbol="USDC",
                user_address=user,
                has_open_position=True,
                is_liquidatable=False,
                base_token=bytes.fromhex("22" * 20),
                base_symbol="USDC",
                base_price_usd=Decimal("1"),
                eth_price_usd=Decimal("3000"),
                total_collateral_usd=Decimal("100"),
                total_debt_usd=Decimal("25"),
                discounted_collateral_usd=Decimal("80"),
                liquidation_buffer_usd=Decimal("55"),
                health_factor=Decimal("3.2"),
                eth_sensitive_collateral_usd=Decimal("0"),
                eth_sensitive_debt_usd=Decimal("0"),
                net_eth_exposure_usd=Decimal("0"),
                non_eth_collateral_usd=Decimal("100"),
                non_eth_debt_usd=Decimal("25"),
                basis_risk_collateral_usd=Decimal("0"),
                eth_down_liq_price_usd=None,
                eth_up_liq_price_usd=None,
                eth_liq_mode="neutral",
                dominant_risk="neutral",
                assets_jsonb=[],
            )
        ],
        asset_rows=[],
    )

    assert touched == 0
    assert not conn.execute_calls
    assert not conn.executemany_calls


@pytest.mark.asyncio
async def test_fetch_compound_v3_current_positions_maps_rows() -> None:
    conn = _FakeConn()
    conn.fetch_rows = [
        {
            "market": bytes.fromhex("aa" * 20),
            "user_address": bytes.fromhex("11" * 20),
            "symbol": "USDC",
            "last_block_number": 100,
            "last_block_timestamp": datetime(2026, 3, 27, tzinfo=timezone.utc),
            "last_tx_hash": "0x" + "ab" * 32,
            "has_open_position": True,
            "is_liquidatable": False,
            "base_token": bytes.fromhex("22" * 20),
            "base_symbol": "USDC",
            "base_price_usd": Decimal("1"),
            "eth_price_usd": Decimal("3000"),
            "total_collateral_usd": Decimal("100"),
            "total_debt_usd": Decimal("25"),
            "discounted_collateral_usd": Decimal("80"),
            "liquidation_buffer_usd": Decimal("55"),
            "health_factor": Decimal("3.2"),
            "eth_sensitive_collateral_usd": Decimal("0"),
            "eth_sensitive_debt_usd": Decimal("0"),
            "net_eth_exposure_usd": Decimal("0"),
            "non_eth_collateral_usd": Decimal("100"),
            "non_eth_debt_usd": Decimal("25"),
            "basis_risk_collateral_usd": Decimal("0"),
            "eth_down_liq_price_usd": None,
            "eth_up_liq_price_usd": None,
            "eth_liq_mode": "neutral",
            "dominant_risk": "neutral",
            "assets_jsonb": '[{"symbol":"USDC"}]',
            "created_at": datetime(2026, 3, 27, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 3, 27, tzinfo=timezone.utc),
        }
    ]

    rows = await fetch_compound_v3_current_positions(
        cast(asyncpg.Pool, _FakePool(conn))
    )

    assert len(rows) == 1
    assert rows[0].last_tx_hash == "0x" + "ab" * 32
    assert rows[0].assets_jsonb == [{"symbol": "USDC"}]


@pytest.mark.asyncio
async def test_fetch_compound_v2_current_positions_maps_rows() -> None:
    conn = _FakeConn()
    conn.fetch_rows = [
        {
            "market": bytes.fromhex("aa" * 20),
            "user_address": bytes.fromhex("11" * 20),
            "symbol": "cETH",
            "last_block_number": 100,
            "last_block_timestamp": datetime(2026, 3, 27, tzinfo=timezone.utc),
            "last_tx_hash": "0x" + "ab" * 32,
            "has_open_position": True,
            "is_liquidatable": False,
            "base_token": bytes.fromhex("22" * 20),
            "base_symbol": "WETH",
            "base_price_usd": Decimal("3000"),
            "eth_price_usd": Decimal("3000"),
            "total_collateral_usd": Decimal("100"),
            "total_debt_usd": Decimal("25"),
            "discounted_collateral_usd": Decimal("80"),
            "liquidation_buffer_usd": Decimal("55"),
            "health_factor": Decimal("3.2"),
            "eth_sensitive_collateral_usd": Decimal("100"),
            "eth_sensitive_debt_usd": Decimal("25"),
            "net_eth_exposure_usd": Decimal("75"),
            "non_eth_collateral_usd": Decimal("0"),
            "non_eth_debt_usd": Decimal("0"),
            "basis_risk_collateral_usd": Decimal("0"),
            "eth_down_liq_price_usd": Decimal("1800"),
            "eth_up_liq_price_usd": None,
            "eth_liq_mode": "down",
            "dominant_risk": "eth_down",
            "assets_jsonb": '[{"symbol":"WETH"}]',
            "created_at": datetime(2026, 3, 27, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 3, 27, tzinfo=timezone.utc),
        }
    ]

    rows = await fetch_compound_v2_current_positions(
        cast(asyncpg.Pool, _FakePool(conn))
    )

    assert len(rows) == 1
    assert rows[0].symbol == "cETH"
    assert rows[0].last_tx_hash == "0x" + "ab" * 32
    assert rows[0].assets_jsonb == [{"symbol": "WETH"}]
