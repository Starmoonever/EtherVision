"""
get_positions_period 服务函数单元测试。

覆盖：
  - 协议名称 → 表名映射
  - interval_days 采样逻辑
  - sim_eth_price_distance 价格换算
  - DB 空结果处理
  - 字段格式（小数位数）
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from aave_crawler.api.service import _daily_positions_table, get_positions_period


# ── 辅助 ─────────────────────────────────────────────────────────────────────


def _make_row(
    snapshot_date: date,
    cnt: int,
    total_eth: float,
    eth_price: float,
) -> MagicMock:
    """构造一条模拟 asyncpg.Record 行。"""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "snapshot_date": snapshot_date,
        "cnt": cnt,
        "total_eth": Decimal(str(total_eth)),
        "eth_price": Decimal(str(eth_price)),
    }[key]
    return row


def _ts(d: str) -> int:
    """'YYYY-MM-DD' → UTC Unix 时间戳（秒）。"""
    return int(
        datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    )


def _make_pool(rows: list) -> AsyncMock:
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=rows)
    return pool


# ── 协议 → 表名 ───────────────────────────────────────────────────────────────


class TestDailyPositionsTable:
    def test_v3_returns_v3_table(self):
        assert _daily_positions_table("v3") == "aave_v3_eth_daily_positions"

    def test_v2_returns_v2_table(self):
        assert _daily_positions_table("v2") == "aave_v2_eth_daily_positions"

    def test_v3_case_insensitive(self):
        assert _daily_positions_table("V3") == "aave_v3_eth_daily_positions"

    def test_v2_case_insensitive(self):
        assert _daily_positions_table("V2") == "aave_v2_eth_daily_positions"


# ── get_positions_period ──────────────────────────────────────────────────────


class TestGetPositionsPeriod:
    """get_positions_period 业务逻辑单元测试（mock pool.fetch）。"""

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_list(self):
        pool = _make_pool([])
        result = await get_positions_period(
            pool,
            protocol="v3",
            start_ts=_ts("2025-01-01"),
            end_ts=_ts("2025-01-07"),
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_single_row_returned(self):
        rows = [_make_row(date(2025, 1, 1), cnt=100, total_eth=50.0, eth_price=3000.0)]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool,
            protocol="v3",
            start_ts=_ts("2025-01-01"),
            end_ts=_ts("2025-01-01"),
        )
        assert len(result) == 1
        item = result[0]
        assert item.snapshot_date == "2025-01-01"
        assert item.count == "100"
        assert item.total_eth_amount == "50.000000"
        assert item.eth_price == "3000.00"
        assert item.sim_eth_price == "3000.00"  # no shift
        assert item.total_usd == "150000.00"  # 50 * 3000

    @pytest.mark.asyncio
    async def test_sim_price_distance_positive(self):
        """+10% 上涨时 sim_eth_price = eth_price * 1.10，total_usd 相应增加。"""
        rows = [_make_row(date(2025, 1, 1), cnt=10, total_eth=10.0, eth_price=2000.0)]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool,
            protocol="v3",
            start_ts=_ts("2025-01-01"),
            end_ts=_ts("2025-01-01"),
            sim_eth_price_distance=10.0,
        )
        item = result[0]
        assert item.sim_eth_price == "2200.00"  # 2000 * 1.10
        assert item.total_usd == "22000.00"  # 10 * 2200

    @pytest.mark.asyncio
    async def test_sim_price_distance_negative(self):
        """-10% 下跌时 sim_eth_price = eth_price * 0.90。"""
        rows = [_make_row(date(2025, 1, 1), cnt=10, total_eth=10.0, eth_price=2000.0)]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool,
            protocol="v3",
            start_ts=_ts("2025-01-01"),
            end_ts=_ts("2025-01-01"),
            sim_eth_price_distance=-10.0,
        )
        item = result[0]
        assert item.sim_eth_price == "1800.00"  # 2000 * 0.90
        assert item.total_usd == "18000.00"  # 10 * 1800

    @pytest.mark.asyncio
    async def test_interval_1_returns_all_rows(self):
        """interval_days=1（默认）时所有行均返回。"""
        rows = [
            _make_row(
                date(2025, 1, d), cnt=10 + d, total_eth=float(d), eth_price=3000.0
            )
            for d in range(1, 8)
        ]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool,
            protocol="v3",
            start_ts=_ts("2025-01-01"),
            end_ts=_ts("2025-01-07"),
            interval_days=1,
        )
        assert len(result) == 7

    @pytest.mark.asyncio
    async def test_interval_2_returns_every_other_row(self):
        """interval_days=2 时返回第 1、3、5、7 行（索引 0、2、4、6）。"""
        rows = [
            _make_row(date(2025, 1, d), cnt=d, total_eth=float(d), eth_price=3000.0)
            for d in range(1, 8)
        ]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool,
            protocol="v3",
            start_ts=_ts("2025-01-01"),
            end_ts=_ts("2025-01-07"),
            interval_days=2,
        )
        assert len(result) == 4  # indices 0, 2, 4, 6
        assert result[0].snapshot_date == "2025-01-01"
        assert result[1].snapshot_date == "2025-01-03"
        assert result[2].snapshot_date == "2025-01-05"
        assert result[3].snapshot_date == "2025-01-07"

    @pytest.mark.asyncio
    async def test_interval_7_returns_weekly_rows(self):
        """interval_days=7 时只返回第一行（索引 0）。"""
        rows = [
            _make_row(date(2025, 1, d), cnt=d, total_eth=float(d), eth_price=3000.0)
            for d in range(1, 8)
        ]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool,
            protocol="v3",
            start_ts=_ts("2025-01-01"),
            end_ts=_ts("2025-01-07"),
            interval_days=7,
        )
        assert len(result) == 1
        assert result[0].snapshot_date == "2025-01-01"

    @pytest.mark.asyncio
    async def test_pool_receives_correct_date_range(self):
        """验证 pool.fetch 收到正确的日期对象参数。"""
        pool = _make_pool([])
        await get_positions_period(
            pool,
            protocol="v3",
            start_ts=_ts("2025-03-01"),
            end_ts=_ts("2025-03-31"),
        )
        pool.fetch.assert_called_once()
        pos_args = pool.fetch.call_args.args  # (sql, start_date, end_date)
        assert pos_args[1] == date(2025, 3, 1)
        assert pos_args[2] == date(2025, 3, 31)

    @pytest.mark.asyncio
    async def test_total_eth_amount_formatted_to_6_decimals(self):
        rows = [_make_row(date(2025, 1, 1), cnt=1, total_eth=1.5, eth_price=3000.0)]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool, protocol="v3", start_ts=_ts("2025-01-01"), end_ts=_ts("2025-01-01")
        )
        assert result[0].total_eth_amount == "1.500000"

    @pytest.mark.asyncio
    async def test_eth_price_formatted_to_2_decimals(self):
        rows = [
            _make_row(date(2025, 1, 1), cnt=1, total_eth=1.0, eth_price=3123.456789)
        ]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool, protocol="v3", start_ts=_ts("2025-01-01"), end_ts=_ts("2025-01-01")
        )
        assert result[0].eth_price == "3123.46"

    @pytest.mark.asyncio
    async def test_v2_protocol_accepted(self):
        """协议版本 v2 不影响结果结构。"""
        rows = [_make_row(date(2025, 1, 1), cnt=50, total_eth=20.0, eth_price=2500.0)]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool,
            protocol="v2",
            start_ts=_ts("2025-01-01"),
            end_ts=_ts("2025-01-01"),
        )
        assert len(result) == 1
        assert result[0].count == "50"
