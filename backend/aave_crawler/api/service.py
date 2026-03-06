"""
业务逻辑层。
- 实时从链上查询用户仓位
- 计算 ETH liq_price
"""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import asyncpg
from web3 import AsyncWeb3

from ..constants import ETH_SYMBOLS as _ETH_SYMBOLS
from ..constants import ETH_SYMBOLS_SQL as _ETH_SYMBOLS_SQL
from ..constants import MAX_HF
from ..constants import MAX_UINT256 as _MAX_UINT256
from ..constants import WETH_ADDR as _WETH_ADDR
from ..db import (fetch_user_tx_history, get_cached_snapshots,
                  upsert_snapshot_cache)
from ..models import ReservePosition, UserPosition
from ..rpc import (EMPTY_POSITION, fetch_user_position,
                   fetch_user_position_at_block, get_all_reserve_tokens,
                   get_assets_prices, get_contracts, get_reserve_config)
from ..tx_parser import parse_briefs_from_metas, parse_tx_briefs
from ..utils import raw_to_decimal as _raw_to_dec
from .constants import ETH_COLLATERAL_RATIO_MIN, ETH_DEBT_RATIO_MIN
from .schemas import (BorrowPositionResponse, BorrowUserPositionResponse,
                      HistoricalPositionResponse, HistoricalReserveDetail,
                      LiqPriceResponse, LiquidationPeriodItem,
                      LiquidationSimItem, LiquidationSimResponse,
                      MarketReplayResponse, PositionReplayResponse,
                      PositionResponse, PositionSnapshotPoint, PricePeriodItem,
                      PricePeriodResponse, PriceResponse,
                      ReservePositionSchema, ShortLiqPeriodItem,
                      ShortLiqSimItem, ShortLiqSimResponse,
                      SnapshotReserveDetail, TxHistoryItem, TxHistoryResponse)

logger = logging.getLogger(__name__)


def _fmt(value: Decimal, decimals: int = 2) -> str:
    quantize = Decimal(10) ** -decimals
    return str(value.quantize(quantize, rounding=ROUND_HALF_UP))


# ── 公共数据缓存（每次进程内复用，减少 RPC 调用） ────────────────────────────

_cache: dict = {}


async def _get_common_data(w3: AsyncWeb3, protocol: str = "v3") -> tuple:
    """缓存当次进程内的储备资产列表 / 配置（按协议版本分别缓存，不缓存价格）"""
    contracts = get_contracts(protocol)
    cache_key_tokens = f"reserve_tokens_{protocol}"
    cache_key_configs = f"reserve_configs_{protocol}"
    cache_key_addresses = f"token_addresses_{protocol}"

    if cache_key_tokens not in _cache:
        reserve_tokens = await get_all_reserve_tokens(w3, contracts)
        token_addresses = [rt.token_address for rt in reserve_tokens]
        configs = await asyncio.gather(
            *[get_reserve_config(w3, a, contracts) for a in token_addresses],
            return_exceptions=True,
        )
        reserve_configs = {
            a: c
            for a, c in zip(token_addresses, configs)
            if not isinstance(c, Exception)
        }
        _cache[cache_key_tokens] = reserve_tokens
        _cache[cache_key_configs] = reserve_configs
        _cache[cache_key_addresses] = token_addresses
        logger.info(
            "[%s] 公共数据已缓存，储备资产数量: %d", protocol, len(reserve_tokens)
        )

    # 价格每次重新拉取
    prices = await get_assets_prices(w3, _cache[cache_key_addresses], contracts)
    asset_prices = dict(zip(_cache[cache_key_addresses], prices))

    return _cache[cache_key_tokens], _cache[cache_key_configs], asset_prices


def _format_position(pos: UserPosition) -> PositionResponse:
    s = pos.summary

    hf_raw = s.health_factor
    hf_str = "inf" if hf_raw >= _MAX_UINT256 else _fmt(_raw_to_dec(hf_raw, 18), 4)

    total_debt = _raw_to_dec(s.total_debt_base, 8)
    liq_threshold = Decimal(s.current_liquidation_threshold) / Decimal(10000)

    # 找 ETH/WETH 抵押仓位
    eth_reserve: ReservePosition | None = None
    for r in pos.reserves:
        if (
            r.symbol.upper() in _ETH_SYMBOLS
            and r.usage_as_collateral_enabled
            and r.supply_raw > 0
        ):
            eth_reserve = r
            break

    if eth_reserve is not None:
        eth_amount = _raw_to_dec(eth_reserve.supply_raw, eth_reserve.decimals)
        eth_price = _raw_to_dec(eth_reserve.price_raw, 8)
        eth_collateral_amount = _fmt(eth_amount, 6)
        eth_collateral_usd = _fmt(eth_amount * eth_price)
    else:
        eth_amount = Decimal("0")
        eth_collateral_amount = "0"
        eth_collateral_usd = "0"

    # 计算清算价
    # ETH 自身的清算阈值（精确值，不使用组合加权平均）
    eth_liq_threshold = (
        Decimal(eth_reserve.liquidation_threshold) / Decimal(10000)
        if eth_reserve is not None
        else Decimal("0")
    )
    if total_debt == 0 or eth_amount == 0 or eth_liq_threshold == 0:
        liq_price_str = "0"
    else:
        # 其他（非 ETH）抵押品的安全垫，使用各资产独立 liq_threshold
        other_safe = Decimal("0")
        for r in pos.reserves:
            if r.symbol.upper() in _ETH_SYMBOLS:
                continue
            if not r.usage_as_collateral_enabled or r.supply_raw == 0:
                continue
            r_liq_threshold = Decimal(r.liquidation_threshold) / Decimal(10000)
            other_safe += (
                _raw_to_dec(r.supply_raw, r.decimals)
                * _raw_to_dec(r.price_raw, 8)
                * r_liq_threshold
            )
        numerator = total_debt - other_safe
        liq_price_str = (
            "0"
            if numerator <= 0
            else _fmt(numerator / (eth_amount * eth_liq_threshold))
        )

    return PositionResponse(
        address=pos.user_address,
        eth_collateral_amount=eth_collateral_amount,
        eth_collateral_usd=eth_collateral_usd,
        total_collateral_usd=_fmt(_raw_to_dec(s.total_collateral_base, 8)),
        available_borrows_usd=_fmt(_raw_to_dec(s.available_borrows_base, 8)),
        total_debt_usd=_fmt(total_debt),
        health_factor=hf_str,
        ltv=_fmt(Decimal(s.ltv) / Decimal(10000), 4),
        liq_threshold=_fmt(liq_threshold, 4),
        liq_price=liq_price_str,
    )


def _calc_liquidation_line(pos: UserPosition) -> LiqPriceResponse:
    """
    计算 ETH 价格降至多少时触发清算风险（Health Factor ≤ 1）。

    公式（假设 WETH 为主要抵押品，其他资产价格不变）：
        HF = (eth_amount × P × liq_threshold + other_collateral_value × other_threshold) / total_debt = 1
        => P = (total_debt - other_stable_collateral) / (eth_amount × liq_threshold)

    简化版（rpc_example.py 同源，适用于纯 ETH 抵押用户）：
        eth_amount = total_collateral_usd / current_eth_price
        liq_price  = total_debt_usd / (eth_amount × avg_liq_threshold)
    """
    s = pos.summary

    total_debt = _raw_to_dec(s.total_debt_base, 8)

    # 找 ETH/WETH 抵押仓位
    eth_reserve: ReservePosition | None = None
    for r in pos.reserves:
        if (
            r.symbol.upper() in _ETH_SYMBOLS
            and r.usage_as_collateral_enabled
            and r.supply_raw > 0
        ):
            eth_reserve = r
            break

    addr = pos.user_address

    # 无借贷情况
    if total_debt == 0:
        current_eth_price = (
            _raw_to_dec(eth_reserve.price_raw, 8) if eth_reserve else Decimal("0")
        )
        return LiqPriceResponse(
            address=addr,
            current_eth_price_usd=_fmt(current_eth_price),
            liquidation_eth_price_usd="0",
            distance_pct="inf",
            health_factor="inf",
            note="该地址无借贷，不存在清算风险",
        )

    # 健康系数字符串
    hf_raw = s.health_factor
    hf_str = "inf" if hf_raw >= _MAX_UINT256 else _fmt(_raw_to_dec(hf_raw, 18), 4)

    if eth_reserve is None:
        # 无 ETH 抵押品，无法计算 ETH 清算价
        return LiqPriceResponse(
            address=addr,
            current_eth_price_usd="0",
            liquidation_eth_price_usd="0",
            distance_pct="0",
            health_factor=hf_str,
            note="未发现 ETH/WETH 抵押仓位，无法计算 ETH 清算价",
        )

    current_eth_price = _raw_to_dec(eth_reserve.price_raw, 8)
    eth_amount = _raw_to_dec(eth_reserve.supply_raw, eth_reserve.decimals)
    eth_liq_threshold = Decimal(eth_reserve.liquidation_threshold) / Decimal(10000)

    if eth_amount == 0 or eth_liq_threshold == 0:
        return LiqPriceResponse(
            address=addr,
            current_eth_price_usd=_fmt(current_eth_price),
            liquidation_eth_price_usd="0",
            distance_pct="0",
            health_factor=hf_str,
            note="ETH 供给量或清算阈值为 0，无法计算",
        )

    # 其他（非 ETH）抵押品的安全垫，使用各资产独立 liq_threshold
    other_safe = Decimal("0")
    for r in pos.reserves:
        if r.symbol.upper() in _ETH_SYMBOLS:
            continue
        if not r.usage_as_collateral_enabled or r.supply_raw == 0:
            continue
        r_liq_threshold = Decimal(r.liquidation_threshold) / Decimal(10000)
        price = _raw_to_dec(r.price_raw, 8)
        amount = _raw_to_dec(r.supply_raw, r.decimals)
        other_safe += amount * price * r_liq_threshold

    # P * eth_amount * eth_liq_threshold = total_debt - other_safe
    numerator = total_debt - other_safe
    if numerator <= 0:
        # other_safe 已足以覆盖 debt，ETH 价格降到 0 也不会清算
        liq_price = Decimal("0")
        distance_pct = "inf"
    else:
        liq_price = numerator / (eth_amount * eth_liq_threshold)
        distance = (current_eth_price - liq_price) / current_eth_price * 100
        distance_pct = _fmt(distance, 2)

    return LiqPriceResponse(
        address=addr,
        current_eth_price_usd=_fmt(current_eth_price),
        liquidation_eth_price_usd=_fmt(liq_price),
        distance_pct=distance_pct,
        health_factor=hf_str,
    )


# ── 对外接口 ──────────────────────────────────────────────────────────────────


async def get_user_position(
    w3: AsyncWeb3, address: str, protocol: str = "v3"
) -> PositionResponse:
    reserve_tokens, reserve_configs, asset_prices = await _get_common_data(w3, protocol)
    contracts = get_contracts(protocol)
    sem = asyncio.Semaphore(1)
    pos = await fetch_user_position(
        w3, address, reserve_tokens, reserve_configs, asset_prices, sem, contracts
    )
    from fastapi import HTTPException

    if pos is EMPTY_POSITION:
        raise HTTPException(
            status_code=404,
            detail=f"地址 {address} 当前在 Aave {protocol.upper()} 无任何仓位（已平仓或从未使用）",
        )
    if pos is None:
        raise HTTPException(
            status_code=502, detail=f"查询地址 {address} 时 RPC 调用失败，请稍后重试"
        )
    return _format_position(pos)


async def get_liq_price(
    w3: AsyncWeb3, address: str, protocol: str = "v3"
) -> LiqPriceResponse:
    reserve_tokens, reserve_configs, asset_prices = await _get_common_data(w3, protocol)
    contracts = get_contracts(protocol)
    sem = asyncio.Semaphore(1)
    pos = await fetch_user_position(
        w3, address, reserve_tokens, reserve_configs, asset_prices, sem, contracts
    )
    from fastapi import HTTPException

    if pos is EMPTY_POSITION:
        raise HTTPException(
            status_code=404,
            detail=f"地址 {address} 当前在 Aave {protocol.upper()} 无任何仓位",
        )
    if pos is None:
        raise HTTPException(
            status_code=502, detail=f"查询地址 {address} 时 RPC 调用失败，请稍后重试"
        )
    return _calc_liquidation_line(pos)


# ── DB 批量查询（预爬取数据） ──────────────────────────────────────────────────

# 健康系数阈值：DB 中 ∞ 存为 Decimal("1e18")，大于该阈值视为 inf
_INF_HF_THRESHOLD = Decimal("1e15")

# 合法的排序字段白名单（防止 SQL 注入）
_SORT_COLS = {
    "liquidation_price": "liq_price",
    "liq_price": "liq_price",
    "health_factor": "health_factor",
    "eth_collateral_amount": "eth_collateral_amount",
    "eth_collateral_usd": "eth_collateral_usd",
    "total_debt_usd": "total_debt_usd",
}
_SORT_DIRS = {"asc": "ASC", "desc": "DESC"}


def _tables(protocol: str) -> tuple[str, str]:
    """(主仓位表, 资产明细表)"""
    if protocol.lower() in ("v2", "v2_borrow"):
        suffix = "_borrow" if "borrow" in protocol.lower() else "_collateral"
        return (
            f"aave_v2_eth_positions{suffix}",
            f"aave_v2_eth_reserve_positions{suffix}",
        )
    suffix = "_borrow" if "borrow" in protocol.lower() else "_collateral"
    return f"aave_v3_eth_positions{suffix}", f"aave_v3_eth_reserve_positions{suffix}"


async def get_sorted_positions(
    pool,
    orderby: str = "liq_price",
    order: str = "asc",
    limit: int = 10,
    protocol: str = "v3",
) -> list[PositionResponse]:
    """\u4ece\u6570\u636e\u5e93\u8bfb\u53d6\u5df2\u722c\u53d6\u7684\u4ed3\u4f4d\uff0c\u6309\u6307\u5b9a\u5b57\u6bb5\u6392\u5e8f\u540e\u8fd4\u56de\u3002

    Args:
        pool: asyncpg 连接池
        orderby: 排序字段，``liquidation_price`` 或 ``health_factor``
        order: 方向，``asc`` 或 ``desc``
        limit: 最多返回多少条（上限 200）
        protocol: aave 协议版本 v2/v3
    """
    order_col = _SORT_COLS.get(orderby, "liq_price")
    order_dir = _SORT_DIRS.get(order, "ASC")
    pos_table, res_table = _tables(protocol)

    sql = f"""
WITH eth_col AS (
    SELECT
        user_address,
        SUM(supply_raw::numeric / POWER(10::numeric, decimals)) AS eth_amount,
        SUM(supply_usd::numeric)                               AS eth_collateral_usd
    FROM loan.{res_table}
    WHERE symbol IN ({_ETH_SYMBOLS_SQL})
      AND use_as_collateral = true
      AND supply_raw > 0
    GROUP BY user_address
)
SELECT
    p.user_address                                            AS address,
    COALESCE(e.eth_amount,        0::numeric)                AS eth_collateral_amount,
    COALESCE(e.eth_collateral_usd, 0::numeric)               AS eth_collateral_usd,
    p.total_collateral_usd,
    p.available_borrows_usd,
    p.total_debt_usd,
    p.health_factor,
    p.ltv,
    p.liq_threshold,
    p.liq_price
FROM loan.{pos_table} p
LEFT JOIN eth_col e ON p.user_address = e.user_address
WHERE p.liq_price > 0
  AND p.liq_price < 9999999.99
ORDER BY {order_col} {order_dir}
LIMIT $1
"""

    rows = await pool.fetch(sql, limit)

    results: list[PositionResponse] = []
    for row in rows:
        hf = Decimal(str(row["health_factor"]))
        hf_str = "inf" if hf >= _INF_HF_THRESHOLD else _fmt(hf, 4)

        lp = Decimal(str(row["liq_price"]))
        results.append(
            PositionResponse(
                address=row["address"],
                eth_collateral_amount=_fmt(
                    Decimal(str(row["eth_collateral_amount"])), 6
                ),
                eth_collateral_usd=_fmt(Decimal(str(row["eth_collateral_usd"]))),
                total_collateral_usd=_fmt(Decimal(str(row["total_collateral_usd"]))),
                available_borrows_usd=_fmt(Decimal(str(row["available_borrows_usd"]))),
                total_debt_usd=_fmt(Decimal(str(row["total_debt_usd"]))),
                health_factor=hf_str,
                ltv=_fmt(Decimal(str(row["ltv"])), 4),
                liq_threshold=_fmt(Decimal(str(row["liq_threshold"])), 4),
                liq_price=_fmt(lp) if lp > 0 else "0",
            )
        )
    return results


# Aave V3 WETH 默认清算奖励系数（liquidation_bonus = 5%，即 0.05 on top of debt）
_WETH_LIQ_BONUS = Decimal("1.05")

# 清算模拟排序字段白名单
_SIM_SORT_COLS = {
    "liq_price": "liq_price",
    "eth_collateral_amount": "eth_collateral_amount",
    "eth_collateral_usd": "eth_collateral_usd",
    "total_debt_usd": "total_debt_usd",
}


def _build_simulate_sql(
    order_col: str,
    order_dir: str,
    pos_table: str,
    res_table: str,
    use_cap: bool = False,
    use_current_eth_price: bool = False,
) -> str:
    # 参数顺序：$1=模拟ETH价格, [$2=当前ETH价格], [$2/$3=cap上限]
    next_param = 2
    current_price_filter = ""
    if use_current_eth_price:
        current_price_filter = f"  AND p.liq_price <= ${next_param}::numeric"
        next_param += 1
    cap_filter = f"  AND p.liq_price < ${next_param}::numeric" if use_cap else ""
    return f"""
WITH eth_col AS (
    SELECT
        user_address,
        SUM(supply_raw::numeric / POWER(10::numeric, decimals)) AS eth_amount,
        SUM(supply_usd::numeric)                               AS eth_supply_usd_stored
    FROM loan.{res_table}
    WHERE symbol IN ({_ETH_SYMBOLS_SQL})
      AND use_as_collateral = true
      AND supply_raw > 0
    GROUP BY user_address
)
SELECT
    p.user_address                                                AS address,
    COALESCE(e.eth_amount, 0::numeric)                            AS eth_collateral_amount,
    COALESCE(e.eth_amount, 0::numeric) * $1::numeric              AS eth_collateral_usd,
    COALESCE(e.eth_supply_usd_stored, 0::numeric)                 AS eth_supply_usd_stored,
    p.total_collateral_usd,
    p.total_debt_usd,
    p.liq_price
FROM loan.{pos_table} p
LEFT JOIN eth_col e ON p.user_address = e.user_address
WHERE p.liq_price > 0
  AND p.liq_price < 9999999.99
  AND p.liq_price >= $1::numeric
{current_price_filter}
{cap_filter}
ORDER BY {order_col} {order_dir}
"""


async def simulate_liquidation(
    pool,
    eth_price: Decimal,
    orderby: str = "liq_price",
    order: str = "desc",
    limit: int = 100,
    eth_ratio: Decimal = ETH_COLLATERAL_RATIO_MIN,
    protocol: str = "v3",
    cap: Decimal | None = None,
    current_eth_price: Decimal | None = None,
) -> LiquidationSimResponse:
    """模拟当 ETH 价格为 eth_price 时，哪些仓位将被触发清算及汇总统计。

    清算奖励折价说明：
        Aave V3 WETH 清算奖励系数为 1.05（5%），即清算人偿还 1 USD 债务
        可从协议获得价值 1.05 USD 的 ETH 抵押品。
        因此 ``total_liquidation_usd`` = sum( min(debt × 1.05, eth_collateral_usd) )。

    Args:
        current_eth_price: 实时 ETH 价格（用于过滤掉 liq_price > 当前价格的仓位，
            即那些只有在 ETH 上涨时才会被清算的做空仓位）。传入后只有
            liq_price <= current_eth_price 的仓位才会被纳入跌价清算模拟。
    """
    order_col = _SIM_SORT_COLS.get(orderby, "liq_price")
    order_dir = "DESC" if order.lower() == "desc" else "ASC"
    pos_table, res_table = _tables(protocol)
    sql = _build_simulate_sql(
        order_col,
        order_dir,
        pos_table,
        res_table,
        use_cap=cap is not None,
        use_current_eth_price=current_eth_price is not None,
    )
    # 全量拉取所有触发清算仓位，以便统计数据覆盖全部；limit 仅限制 positions 列表
    fetch_args: list = [float(eth_price)]
    if current_eth_price is not None:
        fetch_args.append(float(current_eth_price))
    if cap is not None:
        fetch_args.append(float(cap))
    rows = await pool.fetch(sql, *fetch_args)

    total_eth_amount = Decimal("0")
    total_eth_usd = Decimal("0")
    total_liq_usd = Decimal("0")
    all_items: list[LiquidationSimItem] = []

    for row in rows:
        eth_amt = Decimal(str(row["eth_collateral_amount"]))
        eth_usd = Decimal(str(row["eth_collateral_usd"]))
        eth_usd_stored = Decimal(str(row["eth_supply_usd_stored"]))
        total_col_usd = Decimal(str(row["total_collateral_usd"]))
        debt_usd = Decimal(str(row["total_debt_usd"]))
        liq_p = Decimal(str(row["liq_price"]))

        # ETH 抵押品比例过滤：使用爬取时存储价值，避免模拟价格远低于爬取价格时比例失真
        if total_col_usd <= 0 or eth_usd_stored / total_col_usd < eth_ratio:
            continue

        # 清算人实际可获取的抵押品价值：不超过可用抵押品，含 5% 奖励加码
        seized = min(debt_usd * _WETH_LIQ_BONUS, eth_usd)

        total_eth_amount += eth_amt
        total_eth_usd += eth_usd
        total_liq_usd += seized

        all_items.append(
            LiquidationSimItem(
                address=row["address"],
                liq_price=_fmt(liq_p),
                eth_collateral_amount=_fmt(eth_amt, 6),
                eth_collateral_usd=_fmt(eth_usd),
                total_debt_usd=_fmt(debt_usd),
            )
        )

    total_count = len(all_items)
    items = all_items[:limit]

    cap_note = f"；liq_price 上限过滤：< {cap}" if cap is not None else ""
    cur_price_note = (
        f"；当前 ETH 实时价格：${current_eth_price}（仅含跌价清算风险仓位）"
        if current_eth_price is not None
        else ""
    )
    note = (
        f"共 {total_count} 个仓位将在 ETH=${eth_price} 时触发清算"
        f"（本次返回前 {len(items)} 条）；"
        f"清算奖励系数 {_WETH_LIQ_BONUS}（WETH Aave V3 默认），"
        f"total_liquidation_usd = Σ min(债务 × {_WETH_LIQ_BONUS}, ETH抵押品USD)，"
        f"统计基于全部 {total_count} 个仓位；"
        f"ETH 抵押品占比过滤：>= {eth_ratio}"
        f"{cap_note}{cur_price_note}"
    )

    return LiquidationSimResponse(
        simulated_eth_price=_fmt(eth_price),
        positions=items,
        positions_cnt=str(total_count),
        total_eth_collateral_amount=_fmt(total_eth_amount, 6),
        total_eth_collateral_usd=_fmt(total_eth_usd),
        total_liquidation_usd=_fmt(total_liq_usd),
        note=note,
    )


# 全量拉取所有有清算价的仓位（用于区间模拟，避免每个价格点单独查询）
def _sql_all_liq_positions(pos_table: str, res_table: str) -> str:
    return f"""
WITH eth_col AS (
    SELECT
        user_address,
        SUM(supply_raw::numeric / POWER(10::numeric, decimals)) AS eth_amount,
        SUM(supply_usd::numeric)                               AS eth_supply_usd_stored
    FROM loan.{res_table}
    WHERE symbol IN ({_ETH_SYMBOLS_SQL})
      AND use_as_collateral = true
      AND supply_raw > 0
    GROUP BY user_address
)
SELECT
    COALESCE(e.eth_amount, 0::numeric)           AS eth_collateral_amount,
    COALESCE(e.eth_supply_usd_stored, 0::numeric) AS eth_supply_usd_stored,
    p.total_collateral_usd,
    p.total_debt_usd,
    p.liq_price
FROM loan.{pos_table} p
LEFT JOIN eth_col e ON p.user_address = e.user_address
WHERE p.liq_price > 0
  AND p.liq_price < 9999999.99
"""


async def simulate_liquidation_period(
    pool,
    start_price: Decimal,
    end_price: Decimal,
    interval: Decimal,
    eth_ratio: Decimal = ETH_COLLATERAL_RATIO_MIN,
    protocol: str = "v3",
    current_eth_price: Decimal | None = None,
) -> list[LiquidationPeriodItem]:
    """模拟 ETH 价格在 [start_price, end_price] 区间内每隔 interval 步长时的清算汇总。

    - 仅做一次数据库查询，在内存中对每个价格点分别统计，效率较高。
    - 返回按价格升序排列的清算快照列表，可观察不同价格下清算量的变化趋势。
    - current_eth_price: 传入后只统计 liq_price <= current_eth_price 的仓位（跌价清算）。
    """
    from fastapi import HTTPException

    if start_price > end_price:
        raise HTTPException(status_code=400, detail="start 必须 <= end")

    # 一次拉取所有有清算价的仓位
    pos_table, res_table = _tables(protocol)
    rows = await pool.fetch(_sql_all_liq_positions(pos_table, res_table))
    positions = [
        (
            Decimal(str(r["eth_collateral_amount"])),
            Decimal(str(r["eth_supply_usd_stored"])),
            Decimal(str(r["total_collateral_usd"])),
            Decimal(str(r["total_debt_usd"])),
            Decimal(str(r["liq_price"])),
        )
        for r in rows
        # 仅保留跌价清算仓位：liq_price 必须 <= 当前 ETH 价格
        if current_eth_price is None
        or Decimal(str(r["liq_price"])) <= current_eth_price
    ]

    result: list[LiquidationPeriodItem] = []
    price = start_price
    while price <= end_price:
        total_eth_amount = Decimal("0")
        total_eth_usd = Decimal("0")
        total_liq_usd = Decimal("0")
        cnt = 0
        for eth_amt, eth_usd_stored, total_col_usd, debt_usd, liq_p in positions:
            if liq_p >= price:
                eth_usd = eth_amt * price
                # ETH 抵押品比例过滤：使用爬取时存储价值，避免模拟价格远低于爬取价格时比例失真
                if total_col_usd <= 0 or eth_usd_stored / total_col_usd < eth_ratio:
                    continue
                seized = min(debt_usd * _WETH_LIQ_BONUS, eth_usd)
                total_eth_amount += eth_amt
                total_eth_usd += eth_usd
                total_liq_usd += seized
                cnt += 1
        result.append(
            LiquidationPeriodItem(
                simulated_eth_price=_fmt(price),
                positions_cnt=str(cnt),
                total_eth_collateral_amount=_fmt(total_eth_amount, 6),
                total_eth_collateral_usd=_fmt(total_eth_usd),
                total_liquidation_usd=_fmt(total_liq_usd),
            )
        )
        price += interval
    return result


# ── 借贷端（做空 ETH / borrow WETH）清算分析 ─────────────────────────────────

# 借贷端排序字段白名单
_BORROW_SORT_COLS = {
    "liq_price_rise": "liq_price_rise",
    "weth_debt_usd": "weth_debt_usd",
    "total_debt_usd": "total_debt_usd",
    "health_factor": "health_factor",
}


async def get_sorted_borrow_positions(
    pool,
    orderby: str = "liq_price_rise",
    order: str = "asc",
    limit: int = 10,
    protocol: str = "v3_borrow",
) -> list[BorrowPositionResponse]:
    """从数据库读取借贷端仓位（借入 WETH），按指定字段排序后返回。

    Args:
        pool:    asyncpg 连接池
        orderby: 排序字段，liq_price_rise / weth_debt_usd / total_debt_usd / health_factor
        order:   方向，asc 或 desc
        limit:   最多返回多少条
        protocol: v3_borrow 或 v2_borrow
    """
    order_col = _BORROW_SORT_COLS.get(orderby, "liq_price_rise")
    order_dir = _SORT_DIRS.get(order, "ASC")
    pos_table, _ = _tables(protocol)

    # 仅返回有上涨清算风险的仓位（liq_price_rise > 0），weth_debt_amount 通过 raw/1e18 计算
    sql = f"""
SELECT
    p.user_address                                                      AS address,
    (p.weth_debt_raw::numeric / POWER(10::numeric, 18))                 AS weth_debt_amount,
    p.weth_debt_usd,
    p.total_collateral_usd,
    p.total_debt_usd,
    p.health_factor,
    p.liq_price_rise
FROM loan.{pos_table} p
WHERE p.liq_price_rise > 0
  AND p.liq_price_rise < 9999999.99
ORDER BY {order_col} {order_dir}
LIMIT $1
"""
    rows = await pool.fetch(sql, limit)

    results: list[BorrowPositionResponse] = []
    for row in rows:
        hf = Decimal(str(row["health_factor"]))
        hf_str = "inf" if hf >= _INF_HF_THRESHOLD else _fmt(hf, 4)
        results.append(
            BorrowPositionResponse(
                address=row["address"],
                weth_debt_amount=_fmt(Decimal(str(row["weth_debt_amount"])), 6),
                weth_debt_usd=_fmt(Decimal(str(row["weth_debt_usd"]))),
                total_collateral_usd=_fmt(Decimal(str(row["total_collateral_usd"]))),
                total_debt_usd=_fmt(Decimal(str(row["total_debt_usd"]))),
                health_factor=hf_str,
                liq_price_rise=_fmt(Decimal(str(row["liq_price_rise"]))),
            )
        )
    return results


async def get_borrow_user_position(
    pool,
    address: str,
    protocol: str = "v3_borrow",
) -> BorrowUserPositionResponse | None:
    """查询单个地址的借贷端仓位详情（汇总 + reserve 明细）。

    返回 None 表示地址不在数据库中（未爬取或无仓位）。
    """
    pos_table, res_table = _tables(protocol)
    addr = address.lower()

    async with pool.acquire() as conn:
        pos = await conn.fetchrow(
            f"""
            SELECT user_address, scanned_at,
                   weth_debt_raw, weth_debt_usd,
                   total_collateral_usd, total_debt_usd, available_borrows_usd,
                   health_factor, ltv, liq_threshold, liq_price, liq_price_rise
            FROM loan.{pos_table}
            WHERE user_address = $1
            """,
            addr,
        )
        if pos is None:
            return None

        reserve_rows = await conn.fetch(
            f"""
            SELECT symbol, token_address, decimals,
                   price_usd, supply_raw, supply_usd,
                   stable_debt_raw, variable_debt_raw, total_debt_usd,
                   use_as_collateral
            FROM loan.{res_table}
            WHERE user_address = $1
            ORDER BY total_debt_usd DESC, supply_usd DESC
            """,
            addr,
        )

    hf = Decimal(str(pos["health_factor"]))
    hf_str = "inf" if hf >= _INF_HF_THRESHOLD else _fmt(hf, 4)

    reserves = []
    for r in reserve_rows:
        dec = r["decimals"]
        supply_dec = _raw_to_dec(int(r["supply_raw"]), dec)
        stable_dec = _raw_to_dec(int(r["stable_debt_raw"]), dec)
        variable_dec = _raw_to_dec(int(r["variable_debt_raw"]), dec)
        reserves.append(
            ReservePositionSchema(
                symbol=r["symbol"],
                token_address=r["token_address"],
                price_usd=_fmt(Decimal(str(r["price_usd"]))),
                supply_amount=_fmt(supply_dec, 6),
                supply_usd=_fmt(Decimal(str(r["supply_usd"]))),
                stable_debt_amount=_fmt(stable_dec, 6),
                variable_debt_amount=_fmt(variable_dec, 6),
                total_debt_amount=_fmt(stable_dec + variable_dec, 6),
                total_debt_usd=_fmt(Decimal(str(r["total_debt_usd"]))),
                use_as_collateral=r["use_as_collateral"],
            )
        )

    return BorrowUserPositionResponse(
        address=pos["user_address"],
        scanned_at=pos["scanned_at"].isoformat().replace("+00:00", "Z"),
        weth_debt_amount=_fmt(_raw_to_dec(int(pos["weth_debt_raw"]), 18), 6),
        weth_debt_usd=_fmt(Decimal(str(pos["weth_debt_usd"]))),
        health_factor=hf_str,
        liq_price_rise=_fmt(Decimal(str(pos["liq_price_rise"]))),
        reserves=reserves,
    )


async def simulate_short_liquidation(
    pool,
    eth_price: Decimal,
    orderby: str = "liq_price_rise",
    order: str = "asc",
    limit: int = 100,
    protocol: str = "v3_borrow",
    cap: Decimal | None = None,
    eth_ratio: Decimal = ETH_DEBT_RATIO_MIN,
) -> ShortLiqSimResponse:
    """模拟当 ETH 价格涨至 eth_price 时，哪些借贷仓位将被触发清算及汇总统计。

    触发条件：liq_price_rise > 0 AND liq_price_rise <= eth_price
    （即 ETH 实际价格已超过该仓位的做空清算触发线）

    eth_ratio: weth_debt_usd / total_debt_usd 最小占比，过滤掉非 WETH 主导的债务仓位。
    """
    order_col = _BORROW_SORT_COLS.get(orderby, "liq_price_rise")
    order_dir = "DESC" if order.lower() == "desc" else "ASC"
    pos_table, _ = _tables(protocol)

    cap_filter = "  AND p.liq_price_rise < $2::numeric" if cap is not None else ""
    sql = f"""
SELECT
    p.user_address                                                          AS address,
    p.liq_price_rise,
    (p.weth_debt_raw::numeric / POWER(10::numeric, 18))                     AS weth_debt_amount,
    (p.weth_debt_raw::numeric / POWER(10::numeric, 18)) * $1::numeric       AS weth_debt_usd_sim,
    p.weth_debt_usd                                                         AS weth_debt_usd_stored,
    p.total_collateral_usd,
    p.total_debt_usd
FROM loan.{pos_table} p
WHERE p.liq_price_rise > 0
  AND p.liq_price_rise <= $1::numeric
{cap_filter}
ORDER BY {order_col} {order_dir}
"""
    fetch_args: list = [float(eth_price)]
    if cap is not None:
        fetch_args.append(float(cap))
    rows = await pool.fetch(sql, *fetch_args)

    total_weth_amount = Decimal("0")
    total_weth_usd = Decimal("0")
    total_liq_usd = Decimal("0")
    all_items: list[ShortLiqSimItem] = []

    for row in rows:
        weth_amt = Decimal(str(row["weth_debt_amount"]))
        weth_usd_sim = Decimal(str(row["weth_debt_usd_sim"]))
        weth_usd_stored = Decimal(str(row["weth_debt_usd_stored"]))
        total_col_usd = Decimal(str(row["total_collateral_usd"]))
        total_debt_usd = Decimal(str(row["total_debt_usd"]))
        liq_r = Decimal(str(row["liq_price_rise"]))

        # WETH 债务占比过滤：使用爬取时存储价值，避免模拟价格偏差失真
        if total_debt_usd <= 0 or weth_usd_stored / total_debt_usd < eth_ratio:
            continue

        # 清算人偿还 WETH 债务并获取抵押品（不超过可用抵押品）
        seized = min(weth_usd_sim * _WETH_LIQ_BONUS, total_col_usd)

        total_weth_amount += weth_amt
        total_weth_usd += weth_usd_sim
        total_liq_usd += seized

        all_items.append(
            ShortLiqSimItem(
                address=row["address"],
                liq_price_rise=_fmt(liq_r),
                weth_debt_amount=_fmt(weth_amt, 6),
                weth_debt_usd=_fmt(weth_usd_sim),
                total_collateral_usd=_fmt(total_col_usd),
            )
        )

    total_count = len(all_items)
    items = all_items[:limit]

    cap_note = f"；liq_price_rise 上限过滤：< {cap}" if cap is not None else ""
    note = (
        f"共 {total_count} 个仓位将在 ETH=${eth_price} 时触发做空清算"
        f"（本次返回前 {len(items)} 条）；"
        f"清算奖励系数 {_WETH_LIQ_BONUS}（WETH Aave V3 默认），"
        f"total_liquidation_usd = Σ min(WETH债务USD × {_WETH_LIQ_BONUS}, 总抵押USD)；"
        f"统计基于全部 {total_count} 个仓位；"
        f"WETH 债务占比过滤：>= {eth_ratio}"
        f"{cap_note}"
    )

    return ShortLiqSimResponse(
        simulated_eth_price=_fmt(eth_price),
        positions=items,
        positions_cnt=str(total_count),
        total_weth_debt_amount=_fmt(total_weth_amount, 6),
        total_weth_debt_usd=_fmt(total_weth_usd),
        total_liquidation_usd=_fmt(total_liq_usd),
        note=note,
    )


async def simulate_short_liquidation_period(
    pool,
    start_price: Decimal,
    end_price: Decimal,
    interval: Decimal,
    protocol: str = "v3_borrow",
    eth_ratio: Decimal = ETH_DEBT_RATIO_MIN,
) -> list[ShortLiqPeriodItem]:
    """模拟 ETH 价格在 [start_price, end_price] 区间内每隔 interval 步长时的做空清算汇总。

    - 仅做一次数据库查询，在内存中对每个价格点分别统计，效率较高。
    - 返回按价格升序排列的清算快照列表，可观察不同价格下清算量的变化趋势。
    - eth_ratio: weth_debt_usd / total_debt_usd 最小占比过滤。
    """
    from fastapi import HTTPException

    if start_price > end_price:
        raise HTTPException(status_code=400, detail="start 必须 <= end")

    pos_table, _ = _tables(protocol)
    sql = f"""
SELECT
    (p.weth_debt_raw::numeric / POWER(10::numeric, 18)) AS weth_debt_amount,
    p.weth_debt_usd,
    p.total_collateral_usd,
    p.total_debt_usd,
    p.liq_price_rise
FROM loan.{pos_table} p
WHERE p.liq_price_rise > 0
"""
    rows = await pool.fetch(sql)
    # (weth_debt_amount, weth_debt_usd_stored, total_collateral_usd, total_debt_usd, liq_price_rise)
    positions = [
        (
            Decimal(str(r["weth_debt_amount"])),
            Decimal(str(r["weth_debt_usd"])),
            Decimal(str(r["total_collateral_usd"])),
            Decimal(str(r["total_debt_usd"])),
            Decimal(str(r["liq_price_rise"])),
        )
        for r in rows
    ]

    result: list[ShortLiqPeriodItem] = []
    price = start_price
    while price <= end_price:
        total_weth_amount = Decimal("0")
        total_weth_usd = Decimal("0")
        total_liq_usd = Decimal("0")
        cnt = 0
        for (
            weth_amt,
            weth_usd_stored,
            total_col_usd,
            total_debt_usd,
            liq_r,
        ) in positions:
            if liq_r <= price:  # ETH 已涨超触发价
                # WETH 债务占比过滤
                if total_debt_usd <= 0 or weth_usd_stored / total_debt_usd < eth_ratio:
                    continue
                weth_usd_sim = weth_amt * price
                seized = min(weth_usd_sim * _WETH_LIQ_BONUS, total_col_usd)
                total_weth_amount += weth_amt
                total_weth_usd += weth_usd_sim
                total_liq_usd += seized
                cnt += 1
        result.append(
            ShortLiqPeriodItem(
                simulated_eth_price=_fmt(price),
                positions_cnt=str(cnt),
                total_weth_debt_amount=_fmt(total_weth_amount, 6),
                total_weth_debt_usd=_fmt(total_weth_usd),
                total_liquidation_usd=_fmt(total_liq_usd),
            )
        )
        price += interval
    return result


async def get_eth_price(
    w3: AsyncWeb3, asset: str, timestamp: int | None = None
) -> PriceResponse:
    """获取指定资产的 USD 价格。

    - ``timestamp=None``：从链上 Aave Oracle 实时查询
    - ``timestamp=<unix_ts>``：从 DeFiLlama Coins API 查询历史价格

    Args:
        w3:        AsyncWeb3 实例
        asset:     资产符号，如 ``eth``、``wbtc``；大小写不敏感
        timestamp: Unix 时间戳（秒），None 表示查当前价格
    """
    import time as _time
    from datetime import datetime, timezone

    import aiohttp
    from fastapi import HTTPException

    def _ts_to_utc_str(ts: int) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    # 预热缓存，确保 reserve_tokens 已加载（价格查询只需 v3 的 token 列表，两版本共用同一 Oracle）
    await _get_common_data(w3, "v3")

    # "eth" 在 Aave 中以 WETH 表示
    target = asset.upper()
    if target == "ETH":
        target = "WETH"

    reserve_tokens = _cache["reserve_tokens_v3"]
    matching = [rt for rt in reserve_tokens if rt.symbol.upper() == target]
    if not matching:
        raise HTTPException(
            status_code=404, detail=f"未找到资产 '{asset}'，请确认符号正确"
        )

    token_address = matching[0].token_address

    if timestamp is None:
        # ── 实时价格：链上 Oracle ─────────────────────────────────────────
        prices = await get_assets_prices(w3, [token_address])
        price = _raw_to_dec(prices[0], 8)
        return PriceResponse(
            asset=asset.upper(),
            price_usd=_fmt(price, 2),
            token_address=token_address,
            timestamp=_ts_to_utc_str(int(_time.time())),
            source="on-chain",
        )
    else:
        # ── 历史价格：DeFiLlama Coins API ────────────────────────────────
        # https://coins.llama.fi/prices/historical/{timestamp}/ethereum:{address}
        coin_key = f"ethereum:{token_address.lower()}"
        url = f"https://coins.llama.fi/prices/historical/{timestamp}/{coin_key}"
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            ) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise HTTPException(
                            status_code=502,
                            detail=f"DeFiLlama 返回 HTTP {resp.status}",
                        )
                    data = await resp.json()
        except aiohttp.ClientError as exc:
            raise HTTPException(
                status_code=502, detail=f"无法连接 DeFiLlama: {exc}"
            ) from exc

        coins = data.get("coins", {})
        if coin_key not in coins:
            raise HTTPException(
                status_code=404,
                detail=f"DeFiLlama 未返回 '{asset}' 在该时间点的价格数据",
            )
        entry = coins[coin_key]
        price = Decimal(str(entry["price"]))
        actual_ts = int(entry.get("timestamp", timestamp))
        return PriceResponse(
            asset=asset.upper(),
            price_usd=_fmt(price, 2),
            token_address=token_address,
            timestamp=_ts_to_utc_str(actual_ts),
            source="defillama",
        )


async def get_price_period(
    w3: AsyncWeb3,
    asset: str,
    start_ts: int,
    end_ts: int,
    interval_minutes: int,
) -> PricePeriodResponse:
    """查询资产在指定时间段内按固定间隔的历史价格序列（来自 DeFiLlama）。

    改进策略（避免大量并发请求触发 429）：
    - interval_minutes >= 60：使用 ``GET /chart/{coins}?start=&span={n_points}&period={Xh}``
      DeFiLlama 原生时间序列接口，整个时间范围只需 **1 次 HTTP 请求**。
    - interval_minutes < 60：使用 ``POST /batchHistorical``，将所有时间戳打包进
      单次请求，每批最多 ``_BATCH_MAX`` 个时间戳，大幅减少请求数量。

    Args:
        w3:               AsyncWeb3 实例（用于解析 token_address）
        asset:            资产符号，如 ``eth``、``wbtc``；大小写不敏感
        start_ts:         起始 Unix 时间戳（秒）
        end_ts:           结束 Unix 时间戳（秒，含）
        interval_minutes: 采样间隔（分钟，>= 1）
    """
    from datetime import datetime, timezone

    import aiohttp
    from fastapi import HTTPException

    # 每批 batchHistorical 最多携带的时间戳数量
    _BATCH_MAX = 500

    def _ts_to_utc_str(ts: int) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    if end_ts < start_ts:
        raise HTTPException(status_code=400, detail="end 必须晚于或等于 start")
    if interval_minutes < 1:
        raise HTTPException(status_code=400, detail="interval 必须 >= 1 分钟")

    # 解析 token_address（复用 _get_common_data 缓存）
    await _get_common_data(w3, "v3")
    target = asset.upper()
    if target == "ETH":
        target = "WETH"
    reserve_tokens = _cache["reserve_tokens_v3"]
    matching = [rt for rt in reserve_tokens if rt.symbol.upper() == target]
    if not matching:
        raise HTTPException(
            status_code=404, detail=f"未找到资产 '{asset}'，请确认符号正确"
        )
    token_address = matching[0].token_address
    coin_key = f"ethereum:{token_address.lower()}"

    timeout = aiohttp.ClientTimeout(total=30)

    # ── /chart/ 接口：支持任意间隔（1m、15m、1h、24h 等），单次请求 ─────────
    # batchHistorical 已废弃，统一改用 /chart/
    step = interval_minutes * 60
    n_points = (end_ts - start_ts) // step + 1

    if interval_minutes < 60:
        period_str = f"{interval_minutes}m"
    else:
        period_str = f"{interval_minutes // 60}h"

    url = (
        f"https://coins.llama.fi/chart/{coin_key}"
        f"?start={start_ts}&span={n_points}&period={period_str}"
    )

    async with aiohttp.ClientSession(timeout=timeout) as sess:
        try:
            async with sess.get(url) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise HTTPException(
                        status_code=502,
                        detail=f"DeFiLlama /chart/ 返回 HTTP {resp.status}: {body[:200]}",
                    )
                data = await resp.json()
        except aiohttp.ClientError as exc:
            raise HTTPException(
                status_code=502, detail=f"请求 DeFiLlama 失败: {exc}"
            ) from exc

    raw_prices: list[dict] = data.get("coins", {}).get(coin_key, {}).get("prices", [])
    items: list[PricePeriodItem] = [
        PricePeriodItem(
            price_usd=_fmt(Decimal(str(p["price"])), 2),
            timestamp=_ts_to_utc_str(int(p["timestamp"])),
        )
        for p in raw_prices
        if "price" in p and "timestamp" in p
    ]
    if not items:
        raise HTTPException(
            status_code=404,
            detail=f"DeFiLlama 未返回 '{asset}' 在指定区间的价格数据",
        )
    return PricePeriodResponse(
        asset=asset.upper(),
        token_address=token_address,
        source="defillama",
        prices=items,
    )


# ── 历史仓位重建（基于 aave.aave_history + aave_reserve_data） ─────────────────

# 常见稳定币符号（历史价格视为 $1）
_STABLECOINS = {
    "USDC",
    "USDT",
    "DAI",
    "GHO",
    "LUSD",
    "FRAX",
    "USDE",
    "CRVUSD",
    "PYUSD",
    "SUSD",
    "TUSD",
    "BUSD",
}

# 单用户历史仓位 SQL（含利息：scaled balance × index_at_T）
# RAY = 1e27（Aave 内部利率精度）
_SQL_USER_HISTORY = """
WITH target_block AS (
    SELECT COALESCE(MAX(block_number), 0) AS blk
    FROM aave.aave_history
    WHERE created_at <= $2
),
ops AS (
    SELECT
        convert_from(h.token_address, 'UTF8')            AS token_addr,
        h.token_symbol,
        h.decimals,
        h.operation_type,
        h.amount,
        COALESCE(liq_r.liquidity_index,         1000000000000000000000000000::numeric) AS liq_idx_op,
        COALESCE(borrow_r.variable_borrow_index, 1000000000000000000000000000::numeric) AS borrow_idx_op
    FROM aave.aave_history h
    LEFT JOIN LATERAL (
        SELECT r.liquidity_index
        FROM   aave.aave_reserve_data r
        WHERE  r.underlying_token_address = h.token_address
          AND  r.block_number <= h.block_number
        ORDER BY r.block_number DESC LIMIT 1
    ) liq_r ON true
    LEFT JOIN LATERAL (
        SELECT r.variable_borrow_index
        FROM   aave.aave_reserve_data r
        WHERE  r.underlying_token_address = h.token_address
          AND  r.block_number <= h.block_number
        ORDER BY r.block_number DESC LIMIT 1
    ) borrow_r ON true
    WHERE convert_from(h.user_address, 'UTF8') ILIKE $1
      AND h.created_at   <= $2
      AND h.operation_type IN ('deposit', 'withdraw', 'borrow', 'repay')
),
current_idx AS (
    SELECT DISTINCT ON (underlying_token_address)
        convert_from(underlying_token_address, 'UTF8') AS token_addr,
        liquidity_index          AS cur_liq,
        variable_borrow_index    AS cur_borrow
    FROM aave.aave_reserve_data
    WHERE block_number <= (SELECT blk FROM target_block)
    ORDER BY underlying_token_address, block_number DESC
),
scaled AS (
    SELECT
        o.token_addr, o.token_symbol, o.decimals,
        SUM(CASE
            WHEN o.operation_type = 'deposit'  THEN  o.amount / o.liq_idx_op
            WHEN o.operation_type = 'withdraw' THEN -o.amount / o.liq_idx_op
            ELSE 0
        END) AS sc_supply,
        SUM(CASE
            WHEN o.operation_type = 'borrow' THEN  o.amount / o.borrow_idx_op
            WHEN o.operation_type = 'repay'  THEN -o.amount / o.borrow_idx_op
            ELSE 0
        END) AS sc_debt
    FROM ops o
    GROUP BY o.token_addr, o.token_symbol, o.decimals
)
SELECT
    s.token_addr,
    s.token_symbol,
    s.decimals,
    GREATEST(s.sc_supply * COALESCE(ci.cur_liq,    1000000000000000000000000000::numeric)
             / 1000000000000000000000000000::numeric / POWER(10::numeric, s.decimals), 0) AS supply_amount,
    GREATEST(s.sc_debt   * COALESCE(ci.cur_borrow, 1000000000000000000000000000::numeric)
             / 1000000000000000000000000000::numeric / POWER(10::numeric, s.decimals), 0) AS debt_amount
FROM scaled s
LEFT JOIN current_idx ci ON ci.token_addr = s.token_addr
WHERE s.sc_supply > 1e-9 OR s.sc_debt > 1e-9
ORDER BY s.token_symbol;
"""

# 批量历史仓位 SQL（近似：直接累加原始金额，不含利息，速度快）
_SQL_BATCH_HISTORY = """
WITH user_token_ops AS (
    SELECT
        convert_from(h.user_address,  'UTF8') AS address,
        convert_from(h.token_address, 'UTF8') AS token_addr,
        h.token_symbol,
        h.decimals,
        SUM(CASE
            WHEN operation_type = 'deposit'  THEN  amount / POWER(10::numeric, decimals)
            WHEN operation_type = 'withdraw' THEN -amount / POWER(10::numeric, decimals)
            ELSE 0
        END) AS net_supply,
        SUM(CASE
            WHEN operation_type = 'borrow' THEN  amount / POWER(10::numeric, decimals)
            WHEN operation_type = 'repay'  THEN -amount / POWER(10::numeric, decimals)
            ELSE 0
        END) AS net_debt
    FROM aave.aave_history
    WHERE created_at <= $1
      AND operation_type IN ('deposit', 'withdraw', 'borrow', 'repay')
    GROUP BY 1, 2, 3, 4
),
top_eth AS (
    SELECT address,
           SUM(GREATEST(net_supply, 0)) AS eth_amount
    FROM   user_token_ops
    WHERE  UPPER(token_symbol) IN ('WETH','ETH','CBETH','WSTETH','RETH')
    GROUP BY address
    HAVING SUM(GREATEST(net_supply, 0)) > 0.001
    ORDER BY eth_amount DESC
    LIMIT  $2
)
SELECT
    t.address,
    t.eth_amount,
    u.token_addr,
    u.token_symbol,
    GREATEST(u.net_debt, 0) AS debt_amount
FROM top_eth t
LEFT JOIN user_token_ops u ON u.address = t.address AND GREATEST(u.net_debt, 0) > 1e-6
ORDER BY t.eth_amount DESC, t.address, u.token_symbol;
"""


async def _defillama_prices_bulk(
    token_map: dict[str, str],  # symbol → "ethereum:0x..." (or "coingecko:...")
    timestamp: int,
) -> dict[str, Decimal]:
    """批量从 DeFiLlama 获取多个资产在同一时间点的历史价格。
    返回 symbol → Decimal(price_usd)。
    稳定币直接返回 1，其余并发查询。
    """
    from datetime import datetime, timezone

    import aiohttp

    result: dict[str, Decimal] = {}
    to_fetch: list[tuple[str, str]] = []  # [(symbol, coin_key), ...]

    for sym, coin_key in token_map.items():
        if sym.upper() in _STABLECOINS:
            result[sym] = Decimal("1")
        else:
            to_fetch.append((sym, coin_key))

    if not to_fetch:
        return result

    async def _fetch_one(
        session: aiohttp.ClientSession, sym: str, coin_key: str
    ) -> tuple[str, Decimal]:
        url = f"https://coins.llama.fi/prices/historical/{timestamp}/{coin_key}"
        try:
            async with session.get(url) as resp:
                data = await resp.json()
                entry = data.get("coins", {}).get(coin_key, {})
                price = (
                    Decimal(str(entry["price"])) if "price" in entry else Decimal("0")
                )
        except Exception:
            price = Decimal("0")
        return sym, price

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as sess:
        tasks = [_fetch_one(sess, sym, ck) for sym, ck in to_fetch]
        results = await asyncio.gather(*tasks)
        for sym, price in results:
            result[sym] = price

    return result


async def get_user_position_history(
    pool,
    address: str,
    at_time_ts: int,
) -> HistoricalPositionResponse | None:
    """
    从 aave.aave_history + aave_reserve_data 重建指定用户在历史时间点的仓位。

    供给量使用 scaled balance × liquidity_index(T) 计算，含利息。
    但不包含用户最后一次操作到时间点 T 之间的利息累积。
    历史 USD 价格来自 DeFiLlama。
    """
    from datetime import datetime, timezone

    def _ts_to_utc(ts: int) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    at_dt = datetime.fromtimestamp(at_time_ts, tz=timezone.utc)

    rows = await pool.fetch(_SQL_USER_HISTORY, address.lower(), at_dt)

    if not rows:
        # 无操作记录 → 返回 None，由调用方决定如何回退
        return None

    # 过滤掉供给和债务都为 0 的行
    rows = [
        r
        for r in rows
        if Decimal(str(r["supply_amount"])) > Decimal("1e-6")
        or Decimal(str(r["debt_amount"])) > Decimal("1e-6")
    ]
    if not rows:
        # 有操作记录但净额为零 → 已平仓，返回空仓位
        return HistoricalPositionResponse(
            address=address,
            at_time=_ts_to_utc(at_time_ts),
            eth_collateral_amount="0",
            eth_price_usd="0",
            eth_collateral_usd="0",
            total_debt_approx_usd="0",
            liq_price="0",
            reserves=[],
            note="该地址在此时间点的净仓位为零（存取相抵）",
        )

    # 收集需要查历史价格的 token
    # ETH 类代币：使用 WETH 地址代表 ETH 价格
    eth_syms = {"WETH", "ETH", "CBETH", "WSTETH", "RETH"}
    token_map: dict[str, str] = {}  # symbol → defillama coin_key
    for row in rows:
        sym = row["token_symbol"].upper()
        if sym not in _STABLECOINS:
            token_map[sym] = f"ethereum:{row['token_addr'].lower()}"

    prices = await _defillama_prices_bulk(token_map, at_time_ts)

    # 计算汇总
    eth_collateral = Decimal("0")
    total_debt_usd = Decimal("0")
    reserves: list[HistoricalReserveDetail] = []

    for row in rows:
        sym = row["token_symbol"].upper()
        supply = Decimal(str(row["supply_amount"]))
        debt = Decimal(str(row["debt_amount"]))
        price = prices.get(sym, Decimal("1"))  # 未知价格 fallback 为 1

        if sym in eth_syms and supply > 0:
            eth_collateral += supply

        if debt > 0:
            total_debt_usd += debt * price

        if supply > Decimal("1e-6") or debt > Decimal("1e-6"):
            reserves.append(
                HistoricalReserveDetail(
                    symbol=row["token_symbol"],
                    token_address=row["token_addr"],
                    supply_amount=_fmt(supply, 6),
                    debt_amount=_fmt(debt, 6),
                )
            )

    # ETH 价格：优先从 prices 字典取 WETH，其次 ETH
    eth_price = prices.get("WETH") or prices.get("ETH") or Decimal("0")
    eth_collateral_usd = eth_collateral * eth_price

    # liq_price（使用与实时端点相同公式，liq_threshold 近似 0.825 for WETH on ETH mainnet）
    _DEFAULT_LIQ_THRESHOLD = Decimal("0.825")
    if total_debt_usd > 0 and eth_collateral > 0:
        liq_price = total_debt_usd / (eth_collateral * _DEFAULT_LIQ_THRESHOLD)
    else:
        liq_price = Decimal("0")

    return HistoricalPositionResponse(
        address=address,
        at_time=_ts_to_utc(at_time_ts),
        eth_collateral_amount=_fmt(eth_collateral, 6),
        eth_price_usd=_fmt(eth_price, 2),
        eth_collateral_usd=_fmt(eth_collateral_usd, 2),
        total_debt_approx_usd=_fmt(total_debt_usd, 2),
        liq_price=_fmt(liq_price, 2) if liq_price > 0 else "0",
        reserves=reserves,
        note=(
            "供给量通过 scaled_balance × liquidity_index(T) 计算（含利息），"
            "但最后一次操作到 T 之间的利息未计。"
            "liq_price 使用 WETH liq_threshold=0.825 近似计算。"
        ),
    )


async def get_positions_history(
    pool,
    at_time_ts: int,
    limit: int = 10,
) -> list[HistoricalPositionResponse]:
    """
    批量重建历史时间点的仓位（近似，不含利息），按 ETH 抵押量降序排列。
    仅扫描 aave.aave_history，无需逐行联 aave_reserve_data（速度快）。
    历史 USD 价格来自 DeFiLlama。
    """
    from datetime import datetime, timezone

    from fastapi import HTTPException

    def _ts_to_utc(ts: int) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    at_dt = datetime.fromtimestamp(at_time_ts, tz=timezone.utc)
    rows = await pool.fetch(_SQL_BATCH_HISTORY, at_dt, limit)
    if not rows:
        raise HTTPException(status_code=404, detail="该时间点之前无 Aave 操作记录")

    # 收集所有需要查价格的 token
    token_map: dict[str, str] = {}
    for row in rows:
        sym = row["token_symbol"].upper() if row["token_symbol"] else None
        if sym and sym not in _STABLECOINS:
            token_map[sym] = f"ethereum:{row['token_addr'].lower()}"

    prices = await _defillama_prices_bulk(token_map, at_time_ts)
    eth_price = prices.get("WETH") or prices.get("ETH") or Decimal("0")
    _DEFAULT_LIQ_THRESHOLD = Decimal("0.825")

    # 按 address 分组
    from collections import defaultdict

    addr_eth: dict[str, Decimal] = {}
    addr_debts: dict[str, list[tuple[str, str, Decimal]]] = defaultdict(
        list
    )  # addr → [(sym, ta, debt)]

    seen = set()
    for row in rows:
        addr = row["address"]
        if addr not in addr_eth:
            addr_eth[addr] = Decimal(str(row["eth_amount"]))
        sym = row["token_symbol"]
        ta = row["token_addr"]
        if sym and ta:
            key = (addr, ta)
            if key not in seen:
                seen.add(key)
                addr_debts[addr].append((sym, ta, Decimal(str(row["debt_amount"]))))

    result: list[HistoricalPositionResponse] = []
    for addr in addr_eth:
        eth_amt = addr_eth[addr]
        total_debt_usd = Decimal("0")
        reserves: list[HistoricalReserveDetail] = []
        for sym, ta, debt in addr_debts.get(addr, []):
            sym_up = sym.upper()
            price = prices.get(sym_up, Decimal("1"))
            total_debt_usd += debt * price
            reserves.append(
                HistoricalReserveDetail(
                    symbol=sym,
                    token_address=ta,
                    supply_amount="0",
                    debt_amount=_fmt(debt, 6),
                )
            )

        liq_price = (
            total_debt_usd / (eth_amt * _DEFAULT_LIQ_THRESHOLD)
            if total_debt_usd > 0 and eth_amt > 0
            else Decimal("0")
        )
        result.append(
            HistoricalPositionResponse(
                address=addr,
                at_time=_ts_to_utc(at_time_ts),
                eth_collateral_amount=_fmt(eth_amt, 6),
                eth_price_usd=_fmt(eth_price, 2),
                eth_collateral_usd=_fmt(eth_amt * eth_price, 2),
                total_debt_approx_usd=_fmt(total_debt_usd, 2),
                liq_price=_fmt(liq_price, 2) if liq_price > 0 else "0",
                reserves=reserves,
                note="近似值：直接累加操作金额，未计利息；liq_price 使用 WETH liq_threshold=0.825",
            )
        )

    return result


# ══════════════════════════════════════════════════════════════════════════════
# 历史仓位回放（基于 position_snapshot_cache + aave_history + RPC at block）
# ══════════════════════════════════════════════════════════════════════════════

_MAX_REPLAY_CONCURRENCY = 5  # 并发 RPC 重放上限（避免公共节点限流）
_REPLAY_BATCH_SIZE = 200  # 每批 RPC gather 的 tx 数，解决万级 tx 坪展内存问题


def _utc_str(dt: datetime) -> str:
    """datetime → 'YYYY-MM-DDTHH:MM:SSZ' UTC 字符串"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts_to_dt(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _get_brief(row) -> str:
    """从缓存行中安全读取 brief 字段；字段不存在或为 None 时返回空字符串。"""
    try:
        return row["brief"] or ""
    except (KeyError, IndexError):
        return ""


def _format_snapshot_point(
    row,  # asyncpg.Record from position_snapshot_cache
    detail: bool = False,
) -> PositionSnapshotPoint:
    """将缓存表 Record 格式化为 PositionSnapshotPoint。"""
    import json

    hf_raw = Decimal(str(row["health_factor"]))
    hf_str = "inf" if hf_raw >= MAX_HF else _fmt(hf_raw, 4)

    reserves: list[SnapshotReserveDetail] = []
    if detail:
        raw_list = row["reserves_json"]
        if isinstance(raw_list, str):
            raw_list = json.loads(raw_list)
        for r in raw_list:
            reserves.append(
                SnapshotReserveDetail(
                    symbol=r["symbol"],
                    token_address=r["token_address"],
                    price_usd=_fmt(Decimal(r["price_usd"]), 2),
                    supply_usd=_fmt(Decimal(r["supply_usd"]), 2),
                    total_debt_usd=_fmt(Decimal(r["total_debt_usd"]), 2),
                    use_as_collateral=r["use_as_collateral"],
                )
            )

    return PositionSnapshotPoint(
        tx_hash=row["tx_hash"],
        block_number=row["block_number"],
        timestamp=_utc_str(row["block_timestamp"]),
        eth_price_usd=_fmt(Decimal(str(row["eth_price_usd"])), 2),
        total_collateral_usd=_fmt(Decimal(str(row["total_collateral_usd"])), 2),
        total_debt_usd=_fmt(Decimal(str(row["total_debt_usd"])), 2),
        available_borrows_usd=_fmt(Decimal(str(row["available_borrows_usd"])), 2),
        health_factor=hf_str,
        liq_threshold=_fmt(Decimal(str(row["liq_threshold"])), 4),
        liq_price=_fmt(Decimal(str(row["liq_price"])), 2),
        liq_price_rise=_fmt(Decimal(str(row["liq_price_rise"])), 2),
        eth_collateral_amount=_fmt(Decimal(str(row["eth_collateral_amount"])), 6),
        eth_collateral_usd=_fmt(Decimal(str(row["eth_collateral_usd"])), 2),
        weth_debt_amount=_fmt(Decimal(str(row["weth_debt_amount"])), 6),
        weth_debt_usd=_fmt(Decimal(str(row["weth_debt_usd"])), 2),
        brief=_get_brief(row),
        reserves=reserves,
    )


async def get_user_tx_history(
    pool: asyncpg.Pool,
    user_address: str,
    from_ts: int,
    to_ts: int,
    protocol: str = "v3",
    detail: bool = False,
) -> TxHistoryResponse:
    """查询用户在时间范围内的 Aave 历史事件列表。

    detail=False 时仅返回汇总统计（跳过 brief 解析，速度更快）。
    detail=True 时返回完整 txs 列表包含 brief。
    """
    from_dt = _ts_to_dt(from_ts)
    to_dt = _ts_to_dt(to_ts)

    tx_rows = await fetch_user_tx_history(pool, user_address, protocol, from_dt, to_dt)

    # 按 operation_type 汇总统计
    stats: dict[str, int] = {}
    for r in tx_rows:
        op = r["operation_type"] or "unknown"
        stats[op] = stats.get(op, 0) + 1

    if not detail:
        return TxHistoryResponse(
            address=user_address.lower(),
            protocol=protocol,
            from_time=_utc_str(from_dt),
            to_time=_utc_str(to_dt),
            total=len(tx_rows),
            stats=stats,
            txs=None,
        )

    cached_rows = await get_cached_snapshots(
        pool, user_address, protocol, from_dt, to_dt
    )
    cached_hashes = {r["tx_hash"] for r in cached_rows}
    cached_brief_map: dict[str, str] = {
        r["tx_hash"]: _get_brief(r) for r in cached_rows
    }

    # 对未缓存的 tx 异步获取 brief
    uncached_hashes = [
        r["tx_hash"] for r in tx_rows if r["tx_hash"] not in cached_hashes
    ]
    fresh_briefs = await parse_tx_briefs(uncached_hashes, protocol=protocol)
    fresh_brief_map: dict[str, str] = dict(zip(uncached_hashes, fresh_briefs))

    items = [
        TxHistoryItem(
            tx_hash=r["tx_hash"],
            block_number=r["block_number"],
            timestamp=_utc_str(r["block_timestamp"]),
            operation_type=r["operation_type"],
            token_symbol=r["token_symbol"] or "",
            cached=r["tx_hash"] in cached_hashes,
            brief=cached_brief_map.get(r["tx_hash"])
            or fresh_brief_map.get(r["tx_hash"], ""),
        )
        for r in tx_rows
    ]

    return TxHistoryResponse(
        address=user_address.lower(),
        protocol=protocol,
        from_time=_utc_str(from_dt),
        to_time=_utc_str(to_dt),
        total=len(items),
        stats=stats,
        txs=items,
    )


_RAY = Decimal(10**27)


async def get_market_replay(
    pool: asyncpg.Pool,
    protocol: str = "v3",
    from_ts: int = 0,
    to_ts: int = 0,
    interval_days: int = 1,
    detail: bool = False,
) -> "MarketReplayResponse":
    """查询大盘历史快照序列。

    从 loan.aave_v{2|3}_market_totals（物化视图）和可选的
    loan.aave_v{2|3}_market_snapshots（reserve 明细）读取，
    按 interval_days 天间隔抽样（每个间隔取时间最近的区块）。
    """
    from .schemas import (MarketReplayResponse, MarketReservePoint,
                          MarketSnapshotPoint)

    base = protocol.split("_")[0].lower()
    totals_table = f"aave_{base}_market_totals"
    detail_table = f"aave_{base}_market_snapshots"

    from_dt = datetime.fromtimestamp(from_ts, tz=timezone.utc)
    to_dt = datetime.fromtimestamp(to_ts, tz=timezone.utc)

    # 每 interval_days 天一个"锚点时刻"，取距该锚点最近的已有区块
    # 使用 DISTINCT ON (day_bucket) 按桶选最近区块，单次查询全部数据点
    interval_epoch = interval_days * 86400
    sql_totals = f"""
        WITH bucketed AS (
            SELECT
                block_number,
                block_timestamp,
                tvl_usd,
                debt_usd,
                liquidity_usd,
                weighted_utilization,
                weighted_supply_apy,
                weighted_borrow_apy,
                -- 将时间戳对齐到 interval_days 天的桶
                to_timestamp(
                    (EXTRACT(EPOCH FROM block_timestamp)::BIGINT
                     / {interval_epoch}) * {interval_epoch}
                ) AT TIME ZONE 'UTC' AS day_bucket,
                ABS(
                    EXTRACT(EPOCH FROM block_timestamp) -
                    (EXTRACT(EPOCH FROM block_timestamp)::BIGINT
                     / {interval_epoch}) * {interval_epoch}
                ) AS bucket_dist
            FROM loan.{totals_table}
            WHERE block_timestamp >= $1 AND block_timestamp <= $2
        )
        SELECT DISTINCT ON (day_bucket)
            block_number, block_timestamp,
            tvl_usd, debt_usd, liquidity_usd,
            weighted_utilization, weighted_supply_apy, weighted_borrow_apy
        FROM bucketed
        ORDER BY day_bucket, bucket_dist ASC
    """

    rows = await pool.fetch(sql_totals, from_dt, to_dt)

    if not rows:
        return MarketReplayResponse(
            protocol=protocol,
            from_time=from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            to_time=to_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            interval_days=interval_days,
            points=[],
            total_points=0,
        )

    selected_blocks = [r["block_number"] for r in rows]

    # 只有 detail=true 时才查 reserve 明细
    reserve_map: dict[int, list[MarketReservePoint]] = {}
    if detail and selected_blocks:
        placeholders = ", ".join(f"${i+1}" for i in range(len(selected_blocks)))
        sql_detail = f"""
            SELECT
                block_number, token_address, symbol,
                price_usd, total_supply_usd, total_debt_usd,
                available_liquidity_usd, utilization_rate,
                liquidity_rate_ray, variable_borrow_rate_ray, stable_borrow_rate_ray
            FROM loan.{detail_table}
            WHERE block_number IN ({placeholders})
            ORDER BY block_number, total_supply_usd DESC
        """
        detail_rows = await pool.fetch(sql_detail, *selected_blocks)
        for dr in detail_rows:
            blk = dr["block_number"]
            supply_apy = _fmt(Decimal(str(dr["liquidity_rate_ray"])) / _RAY, 8)
            var_apy = _fmt(Decimal(str(dr["variable_borrow_rate_ray"])) / _RAY, 8)
            stb_apy = _fmt(Decimal(str(dr["stable_borrow_rate_ray"])) / _RAY, 8)
            reserve_map.setdefault(blk, []).append(
                MarketReservePoint(
                    token_address=dr["token_address"],
                    symbol=dr["symbol"],
                    price_usd=_fmt(Decimal(str(dr["price_usd"])), 8),
                    total_supply_usd=_fmt(Decimal(str(dr["total_supply_usd"])), 2),
                    total_debt_usd=_fmt(Decimal(str(dr["total_debt_usd"])), 2),
                    available_liquidity_usd=_fmt(
                        Decimal(str(dr["available_liquidity_usd"])), 2
                    ),
                    utilization_rate=_fmt(Decimal(str(dr["utilization_rate"])), 6),
                    supply_apy=supply_apy,
                    variable_borrow_apy=var_apy,
                    stable_borrow_apy=stb_apy,
                )
            )

    points: list[MarketSnapshotPoint] = []
    for r in rows:
        blk = r["block_number"]
        ts_str = r["block_timestamp"].strftime("%Y-%m-%dT%H:%M:%SZ")
        points.append(
            MarketSnapshotPoint(
                block_number=blk,
                block_timestamp=ts_str,
                tvl_usd=_fmt(Decimal(str(r["tvl_usd"])), 2),
                debt_usd=_fmt(Decimal(str(r["debt_usd"])), 2),
                liquidity_usd=_fmt(Decimal(str(r["liquidity_usd"])), 2),
                weighted_utilization=_fmt(Decimal(str(r["weighted_utilization"])), 8),
                weighted_supply_apy=_fmt(Decimal(str(r["weighted_supply_apy"])), 8),
                weighted_borrow_apy=_fmt(Decimal(str(r["weighted_borrow_apy"])), 8),
                reserves=reserve_map.get(blk, []),
            )
        )

    return MarketReplayResponse(
        protocol=protocol,
        from_time=from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        to_time=to_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        interval_days=interval_days,
        points=points,
        total_points=len(points),
    )


async def get_user_position_replay(
    pool: asyncpg.Pool,
    w3: AsyncWeb3,
    user_address: str,
    from_ts: int,
    to_ts: int,
    protocol: str = "v3",
    use_cache: bool = True,
    detail: bool = False,
) -> PositionReplayResponse:
    """历史仓位回放主函数。

    流程：
    1. 从 aave_history 取用户的 tx 列表（已建索引，毫秒级）
    2. 查 position_snapshot_cache 确认哪些 tx 已缓存
    3. 对未缓存 tx 并发 RPC eth_call at block_number（真实链上值，无利息误差）
    4. 将新查询结果写入缓存（幂等 UPSERT）
    5. 合并 + 按 block_timestamp 升序返回
    """
    import time as _time_mod

    _t0 = _time_mod.perf_counter()

    from_dt = _ts_to_dt(from_ts)
    to_dt = _ts_to_dt(to_ts)

    # ── 1. 获取 tx 列表 ────────────────────────────────────────────────────────
    _t_db_tx0 = _time_mod.perf_counter()
    tx_rows = await fetch_user_tx_history(pool, user_address, protocol, from_dt, to_dt)
    _t_db_tx1 = _time_mod.perf_counter()
    logger.debug(
        "replay[%s] ① DB tx查询: %.3fs  raw_rows=%d",
        user_address[:10],
        _t_db_tx1 - _t_db_tx0,
        len(tx_rows),
    )

    if not tx_rows:
        return PositionReplayResponse(
            address=user_address.lower(),
            protocol=protocol,
            from_time=_utc_str(from_dt),
            to_time=_utc_str(to_dt),
            data_source="cache",
            points=[],
            total_points=0,
            total_tx_count=0,
            cache_hit_rate="1.00",
        )

    # ── 2. 查缓存 ──────────────────────────────────────────────────────────────
    _t_db_cache0 = _time_mod.perf_counter()
    if use_cache:
        cached_rows = await get_cached_snapshots(
            pool, user_address, protocol, from_dt, to_dt
        )
        cached_map: dict[str, object] = {r["tx_hash"]: r for r in cached_rows}
    else:
        cached_map = {}
    _t_db_cache1 = _time_mod.perf_counter()
    logger.debug(
        "replay[%s] ② DB缓存查询: %.3fs  cached=%d",
        user_address[:10],
        _t_db_cache1 - _t_db_cache0,
        len(cached_map),
    )

    # 去重：同一 block 可能有多条 tx_hash（主用户 + 清算目标角色各一条），
    # 取 block_number 唯一，优先使用缓存命中的 tx_hash
    seen_blocks: dict[int, dict] = {}
    for r in tx_rows:
        bn = r["block_number"]
        th = r["tx_hash"]
        if bn not in seen_blocks or (th in cached_map and r["tx_hash"] == th):
            seen_blocks[bn] = dict(r)

    deduped_txs = sorted(seen_blocks.values(), key=lambda x: x["block_number"])
    total_tx_count = len(deduped_txs)

    # ── 3. 区分缓存命中 / 需 RPC 重放 ─────────────────────────────────────────
    hit_txs = [t for t in deduped_txs if t["tx_hash"] in cached_map]
    miss_txs = [t for t in deduped_txs if t["tx_hash"] not in cached_map]
    logger.debug(
        "replay[%s] ③ 去重后 tx=%d  hit=%d  miss=%d",
        user_address[:10],
        len(deduped_txs),
        len(hit_txs),
        len(miss_txs),
    )

    # ── 4. 流水线并行：RPC producer ↔ brief+upsert consumer ──────────────────
    # 结构：RPC gather 与下一批的 brief 解析 + DB 写入并行执行，消除串行等待。
    # asyncio.Queue 作为 RPC→consumer 的传递通道：
    #   Producer：逐批提交 RPC gather，完成后放入队列
    #   Consumer：取出 RPC 结果，做 brief 解析 + upsert，与下一批 RPC 同时进行
    _t_rpc_total = 0.0
    _t_brief_total = 0.0
    _t_upsert_total = 0.0

    if miss_txs:
        _t_common0 = _time_mod.perf_counter()
        reserve_tokens, reserve_configs, _ = await _get_common_data(w3, protocol)
        contracts = get_contracts(protocol)
        semaphore = asyncio.Semaphore(_MAX_REPLAY_CONCURRENCY)
        logger.debug(
            "replay[%s] ④ _get_common_data: %.3fs",
            user_address[:10],
            _time_mod.perf_counter() - _t_common0,
        )

        # Queue 容量 1：producer 最多超前 consumer 一个批次，避免内存积压
        _queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        _SENTINEL = object()

        async def _rpc_producer() -> None:
            nonlocal _t_rpc_total
            for bs in range(0, len(miss_txs), _REPLAY_BATCH_SIZE):
                b = miss_txs[bs : bs + _REPLAY_BATCH_SIZE]
                tasks = [
                    fetch_user_position_at_block(
                        w3,
                        user_address,
                        reserve_tokens,
                        reserve_configs,
                        t["block_number"],
                        semaphore,
                        contracts,
                    )
                    for t in b
                ]
                _t0_rpc = _time_mod.perf_counter()
                results = await asyncio.gather(*tasks)
                _dt = _time_mod.perf_counter() - _t0_rpc
                _t_rpc_total += _dt
                logger.debug(
                    "replay[%s] ⑤ RPC批次[%d-%d]: %.3fs  batch_size=%d",
                    user_address[:10],
                    bs,
                    bs + len(b) - 1,
                    _dt,
                    len(b),
                )
                await _queue.put((bs, b, results))
            await _queue.put(_SENTINEL)

        async def _brief_upsert_consumer() -> None:
            nonlocal _t_brief_total, _t_upsert_total
            while True:
                item = await _queue.get()
                if item is _SENTINEL:
                    break
                bs, b, rpc_results = item

                batch_records: list[dict] = []
                for t, res in zip(b, rpc_results):
                    if res is None:
                        logger.warning(
                            "RPC 重放失败，跳过 tx %s (block %s, user %s)",
                            t["tx_hash"],
                            t["block_number"],
                            user_address,
                        )
                        continue
                    if res is EMPTY_POSITION:
                        continue
                    pos, eth_price_raw = res
                    eth_price_dec = Decimal(eth_price_raw) / Decimal(10**8)
                    _prices = {
                        r.token_address.lower(): Decimal(r.price_raw) / Decimal(10**8)
                        for r in pos.reserves
                    }
                    # WETH 可能因全额取出后余额为 0 而不在 reserves 里，
                    # 天然用 eth_price_usd 作为 WETH 价格
                    _prices.setdefault(_WETH_ADDR, eth_price_dec)
                    batch_records.append(
                        {
                            "position": pos,
                            "meta": {
                                "tx_hash": t["tx_hash"],
                                "block_timestamp": t["block_timestamp"],
                                "eth_price_usd": eth_price_dec,
                                "protocol": protocol,
                                "prices": _prices,
                            },
                        }
                    )

                if batch_records:
                    _t0_brief = _time_mod.perf_counter()
                    batch_briefs = await parse_briefs_from_metas(
                        [r["meta"] for r in batch_records]
                    )
                    _dt_brief = _time_mod.perf_counter() - _t0_brief
                    _t_brief_total += _dt_brief
                    logger.debug(
                        "replay[%s] ⑥ brief解析[%d-%d]: %.3fs  count=%d",
                        user_address[:10],
                        bs,
                        bs + len(b) - 1,
                        _dt_brief,
                        len(batch_records),
                    )

                    _t0_upsert = _time_mod.perf_counter()
                    await upsert_snapshot_cache(
                        pool,
                        positions=[r["position"] for r in batch_records],
                        tx_meta=[r["meta"] for r in batch_records],
                        briefs=batch_briefs,
                    )
                    _dt_upsert = _time_mod.perf_counter() - _t0_upsert
                    _t_upsert_total += _dt_upsert
                    logger.debug(
                        "replay[%s] ⑦ DB写缓存[%d-%d]: %.3fs  count=%d",
                        user_address[:10],
                        bs,
                        bs + len(b) - 1,
                        _dt_upsert,
                        len(batch_records),
                    )

        # producer 与 consumer 并发运行，实现 RPC ↔ brief+upsert 流水线
        await asyncio.gather(_rpc_producer(), _brief_upsert_consumer())

    # ── 5. 重新读取缓存（含刚写入的）──────────────────────────────────────────
    _t_final0 = _time_mod.perf_counter()
    final_cache = await get_cached_snapshots(
        pool, user_address, protocol, from_dt, to_dt
    )
    final_map: dict[str, object] = {r["tx_hash"]: r for r in final_cache}
    _t_final1 = _time_mod.perf_counter()
    logger.debug(
        "replay[%s] ⑧ DB最终读缓存: %.3fs  rows=%d",
        user_address[:10],
        _t_final1 - _t_final0,
        len(final_cache),
    )

    # ── 6. 按 block 排序拼装响应 ───────────────────────────────────────────────
    _t_fmt0 = _time_mod.perf_counter()
    points: list[PositionSnapshotPoint] = []
    for t in deduped_txs:
        row = final_map.get(t["tx_hash"])
        if row is None:
            continue  # 该 tx 的 RPC 重放失败，跳过
        points.append(_format_snapshot_point(row, detail=detail))
    _t_fmt1 = _time_mod.perf_counter()

    # 以「实际返回的点」为基准计算命中率和数据来源：
    # - 永久 RPC 失败的 tx 不计入分母（不影响命中率，也不在响应里）
    # - data_source 与命中率使用同一基准，避免 rate 四舍五入到 1.00 却显示 mixed
    served_txs = [t for t in deduped_txs if t["tx_hash"] in final_map]
    served_from_cache = sum(1 for t in served_txs if t["tx_hash"] in cached_map)
    served_total = len(served_txs)

    cache_hit_rate = (
        _fmt(Decimal(served_from_cache) / Decimal(served_total), 2)
        if served_total > 0
        else "1.00"
    )

    if served_from_cache == served_total:
        data_source = "cache"
    elif served_from_cache == 0:
        data_source = "rpc"
    else:
        data_source = "mixed"

    _t_total = _time_mod.perf_counter() - _t0
    logger.debug(
        "replay[%s] ✅ 总耗时: %.3fs  "
        "[DB-tx=%.3f DB-cache=%.3f RPC=%.3f brief=%.3f upsert=%.3f DB-final=%.3f fmt=%.3f]  "
        "points=%d miss=%d",
        user_address[:10],
        _t_total,
        _t_db_tx1 - _t_db_tx0,
        _t_db_cache1 - _t_db_cache0,
        _t_rpc_total,
        _t_brief_total,
        _t_upsert_total,
        _t_final1 - _t_final0,
        _t_fmt1 - _t_fmt0,
        len(points),
        len(miss_txs),
    )

    return PositionReplayResponse(
        address=user_address.lower(),
        protocol=protocol,
        from_time=_utc_str(from_dt),
        to_time=_utc_str(to_dt),
        data_source=data_source,
        points=points,
        total_points=len(points),
        total_tx_count=total_tx_count,
        cache_hit_rate=cache_hit_rate,
    )
