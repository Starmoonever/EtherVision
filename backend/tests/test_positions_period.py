"""
get_positions_period 服务函数单元测试。

覆盖：
  - 协议名称 → 表名映射
  - interval_days 采样逻辑
  - sim_eth_price_distance 清算过滤语义（多头 / 空头 / 累积）
  - weth_debt 债务端计算
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

_WETH = int(1e18)  # 1 WETH in raw units


def _make_row(
    snapshot_date: date,
    eth_collateral_amount: float = 10.0,
    liq_price: float = 0.0,
    liq_price_rise: float = 0.0,
    weth_debt_raw: int = 0,
    eth_price_usd: float = 3000.0,
) -> MagicMock:
    """构造一条模拟 asyncpg.Record 行（行级 schema）。"""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "snapshot_date": snapshot_date,
        "eth_collateral_amount": Decimal(str(eth_collateral_amount)),
        "liq_price": Decimal(str(liq_price)),
        "liq_price_rise": Decimal(str(liq_price_rise)),
        "weth_debt_raw": weth_debt_raw,
        "eth_price_usd": Decimal(str(eth_price_usd)),
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
    async def test_no_sim_returns_zero_liquidations(self):
        """sim_distance=0 时价格不变，无仓位触发清算，liquidation_cnt=0。"""
        rows = [_make_row(date(2025, 1, 1), liq_price=2000.0, eth_price_usd=3000.0)]
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
        assert item.liquidation_cnt == "0"
        assert item.total_eth_collateral_amount == "0.000000"
        assert item.total_eth_collateral_usd == "0.00"
        assert item.eth_price == "3000.00"
        assert item.sim_eth_price == "3000.00"

    @pytest.mark.asyncio
    async def test_price_drop_liquidates_long_positions(self):
        """ETH 跌 10%：liq_price >= sim_price 的仓位被计入清算。"""
        # sim_price = 3000 * 0.90 = 2700
        # liq_price=2800 >= 2700 → 清算；liq_price=2600 < 2700 → 不清算
        rows = [
            _make_row(
                date(2025, 1, 1),
                eth_collateral_amount=10.0,
                liq_price=2800.0,
                eth_price_usd=3000.0,
            ),
            _make_row(
                date(2025, 1, 1),
                eth_collateral_amount=5.0,
                liq_price=2600.0,
                eth_price_usd=3000.0,
            ),
        ]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool,
            protocol="v3",
            start_ts=_ts("2025-01-01"),
            end_ts=_ts("2025-01-01"),
            sim_eth_price_distance=-10.0,
        )
        item = result[0]
        assert item.liquidation_cnt == "1"
        assert item.total_eth_collateral_amount == "10.000000"
        assert item.sim_eth_price == "2700.00"

    @pytest.mark.asyncio
    async def test_price_drop_cumulative(self):
        """跌 20% 包含跌 10% 的清算（累积语义）。"""
        # sim_price @-10% = 2700：liq_price 2800, 2750 触发
        # sim_price @-20% = 2400：liq_price 2800, 2750, 2500 触发
        rows = [
            _make_row(
                date(2025, 1, 1),
                eth_collateral_amount=1.0,
                liq_price=2800.0,
                eth_price_usd=3000.0,
            ),
            _make_row(
                date(2025, 1, 1),
                eth_collateral_amount=1.0,
                liq_price=2750.0,
                eth_price_usd=3000.0,
            ),
            _make_row(
                date(2025, 1, 1),
                eth_collateral_amount=1.0,
                liq_price=2500.0,
                eth_price_usd=3000.0,
            ),
            _make_row(
                date(2025, 1, 1),
                eth_collateral_amount=1.0,
                liq_price=2000.0,
                eth_price_usd=3000.0,
            ),
        ]
        pool_10 = _make_pool(rows)
        pool_20 = _make_pool(rows)

        res_10 = await get_positions_period(
            pool_10,
            "v3",
            _ts("2025-01-01"),
            _ts("2025-01-01"),
            sim_eth_price_distance=-10.0,
        )
        res_20 = await get_positions_period(
            pool_20,
            "v3",
            _ts("2025-01-01"),
            _ts("2025-01-01"),
            sim_eth_price_distance=-20.0,
        )

        cnt_10 = int(res_10[0].liquidation_cnt)
        cnt_20 = int(res_20[0].liquidation_cnt)
        assert cnt_10 == 2  # liq_price 2800, 2750
        assert cnt_20 == 3  # liq_price 2800, 2750, 2500
        assert cnt_20 >= cnt_10

    @pytest.mark.asyncio
    async def test_price_rise_liquidates_short_positions(self):
        """ETH 涨 10%：liq_price_rise > 0 且 liq_price_rise <= sim_price 的仓位被清算。"""
        # sim_price = 3000 * 1.10 = 3300
        # liq_price_rise=3200 <= 3300 → 清算；liq_price_rise=3500 > 3300 → 不清算
        rows = [
            _make_row(
                date(2025, 1, 1),
                eth_collateral_amount=8.0,
                liq_price_rise=3200.0,
                eth_price_usd=3000.0,
            ),
            _make_row(
                date(2025, 1, 1),
                eth_collateral_amount=4.0,
                liq_price_rise=3500.0,
                eth_price_usd=3000.0,
            ),
        ]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool,
            protocol="v3",
            start_ts=_ts("2025-01-01"),
            end_ts=_ts("2025-01-01"),
            sim_eth_price_distance=10.0,
        )
        item = result[0]
        assert item.liquidation_cnt == "1"
        assert item.total_eth_collateral_amount == "8.000000"
        assert item.sim_eth_price == "3300.00"

    @pytest.mark.asyncio
    async def test_zero_liq_price_rise_excluded(self):
        """liq_price_rise=0 的行在涨价场景下不参与清算统计。"""
        rows = [
            _make_row(
                date(2025, 1, 1),
                eth_collateral_amount=5.0,
                liq_price_rise=0.0,
                eth_price_usd=3000.0,
            ),
        ]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool,
            "v3",
            _ts("2025-01-01"),
            _ts("2025-01-01"),
            sim_eth_price_distance=10.0,
        )
        assert result[0].liquidation_cnt == "0"

    @pytest.mark.asyncio
    async def test_weth_debt_included_in_output(self):
        """weth_debt_raw 正确换算为 ETH 单位并按 sim_price 估值。"""
        # 2 WETH debt, sim_price = 2700 → debt_usd = 2 * 2700 = 5400
        rows = [
            _make_row(
                date(2025, 1, 1),
                eth_collateral_amount=10.0,
                liq_price=2800.0,
                weth_debt_raw=2 * _WETH,
                eth_price_usd=3000.0,
            )
        ]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool,
            "v3",
            _ts("2025-01-01"),
            _ts("2025-01-01"),
            sim_eth_price_distance=-10.0,
        )
        item = result[0]
        assert item.liquidation_cnt == "1"
        assert item.total_weth_debt_amount == "2.000000"
        assert item.total_weth_debt_usd == "5400.00"  # 2 * 2700

    @pytest.mark.asyncio
    async def test_zero_eth_collateral_excluded(self):
        """eth_collateral_amount=0 的行不参与任何统计。"""
        rows = [
            _make_row(
                date(2025, 1, 1),
                eth_collateral_amount=0.0,
                liq_price=2800.0,
                eth_price_usd=3000.0,
            ),
        ]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool,
            "v3",
            _ts("2025-01-01"),
            _ts("2025-01-01"),
            sim_eth_price_distance=-10.0,
        )
        assert result[0].liquidation_cnt == "0"

    @pytest.mark.asyncio
    async def test_interval_1_returns_all_dates(self):
        """interval_days=1（默认）时所有日期均返回。"""
        rows = [_make_row(date(2025, 1, d), eth_price_usd=3000.0) for d in range(1, 8)]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool, "v3", _ts("2025-01-01"), _ts("2025-01-07"), interval_days=1
        )
        assert len(result) == 7

    @pytest.mark.asyncio
    async def test_interval_2_returns_every_other_date(self):
        """interval_days=2 时返回第 1、3、5、7 日（按日期排序索引 0、2、4、6）。"""
        rows = [_make_row(date(2025, 1, d), eth_price_usd=3000.0) for d in range(1, 8)]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool, "v3", _ts("2025-01-01"), _ts("2025-01-07"), interval_days=2
        )
        assert len(result) == 4
        assert result[0].snapshot_date == "2025-01-01"
        assert result[1].snapshot_date == "2025-01-03"
        assert result[2].snapshot_date == "2025-01-05"
        assert result[3].snapshot_date == "2025-01-07"

    @pytest.mark.asyncio
    async def test_interval_7_returns_first_date_only(self):
        """interval_days=7 时只返回第一个日期（索引 0）。"""
        rows = [_make_row(date(2025, 1, d), eth_price_usd=3000.0) for d in range(1, 8)]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool, "v3", _ts("2025-01-01"), _ts("2025-01-07"), interval_days=7
        )
        assert len(result) == 1
        assert result[0].snapshot_date == "2025-01-01"

    @pytest.mark.asyncio
    async def test_pool_receives_correct_date_range(self):
        """验证 pool.fetch 收到正确的日期对象参数。"""
        pool = _make_pool([])
        await get_positions_period(pool, "v3", _ts("2025-03-01"), _ts("2025-03-31"))
        pool.fetch.assert_called_once()
        pos_args = pool.fetch.call_args.args  # (sql, start_date, end_date)
        assert pos_args[1] == date(2025, 3, 1)
        assert pos_args[2] == date(2025, 3, 31)

    @pytest.mark.asyncio
    async def test_collateral_amount_formatted_to_6_decimals(self):
        rows = [
            _make_row(
                date(2025, 1, 1),
                eth_collateral_amount=1.5,
                liq_price=2800.0,
                eth_price_usd=3000.0,
            )
        ]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool,
            "v3",
            _ts("2025-01-01"),
            _ts("2025-01-01"),
            sim_eth_price_distance=-10.0,
        )
        assert result[0].total_eth_collateral_amount == "1.500000"

    @pytest.mark.asyncio
    async def test_eth_price_formatted_to_2_decimals(self):
        rows = [_make_row(date(2025, 1, 1), eth_price_usd=3123.456789)]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool, "v3", _ts("2025-01-01"), _ts("2025-01-01")
        )
        assert result[0].eth_price == "3123.46"

    @pytest.mark.asyncio
    async def test_v2_protocol_accepted(self):
        """协议版本 v2 不影响结果结构。"""
        rows = [
            _make_row(
                date(2025, 1, 1),
                eth_collateral_amount=20.0,
                liq_price=2800.0,
                eth_price_usd=2500.0,
            )
        ]
        pool = _make_pool(rows)
        result = await get_positions_period(
            pool,
            "v2",
            _ts("2025-01-01"),
            _ts("2025-01-01"),
            sim_eth_price_distance=-10.0,
        )
        assert len(result) == 1
        assert result[0].liquidation_cnt == "1"
