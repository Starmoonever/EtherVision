"""
业务逻辑层。
- 实时从链上查询用户仓位
- 计算 ETH liq_price
"""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import cast

import asyncpg
from crawler_shared.api.schemas import (
    PriceAssetsResponse,
    PricePeriodResponse,
    PriceResponse,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from web3 import AsyncWeb3

from ..constants import ETH_SYMBOLS as _ETH_SYMBOLS
from ..constants import MAX_HF
from ..constants import MAX_UINT256 as _MAX_UINT256
from ..constants import WETH_ADDR as _WETH_ADDR
from ..db import (
    TABLES_V2,
    TABLES_V2_BORROW,
    TABLES_V3,
    TABLES_V3_BORROW,
    _calc_eth_collateral,
    _calc_liq_price_rise,
    _calc_weth_debt,
    _get_weth_price,
    fetch_user_tx_history,
    get_cached_snapshots,
    upsert_positions,
    upsert_snapshot_cache,
)
from ..models import ReservePosition, UserPosition
from ..rpc import (
    CONTRACTS_V3,
    EMPTY_POSITION,
    ORACLE_ABI,
    WETH_ADDRESS,
    fetch_user_position,
    fetch_user_position_at_block,
    get_all_reserve_tokens,
    get_assets_prices,
    get_contracts,
    get_reserve_config,
)
from ..tx_parser import parse_briefs_from_metas, parse_tx_briefs
from ..utils import raw_to_decimal as _raw_to_dec
from .constants import ETH_COLLATERAL_RATIO_MIN, ETH_DEBT_RATIO_MIN
from .schemas import (
    BorrowPositionResponse,
    BorrowUserPositionResponse,
    HistoricalLiquidationDetailItem,
    HistoricalLiquidationDetailResponse,
    HistoricalPositionResponse,
    HistoricalReserveDetail,
    LiqPriceResponse,
    LiquidationPeriodItem,
    LiquidationSimItem,
    LiquidationSimResponse,
    LiquidationWaterfallResponse,
    LiquidationWaterfallTurnItem,
    MarketReplayResponse,
    PositionPeriodItem,
    PositionReplayResponse,
    PositionResponse,
    PositionSnapshotPoint,
    ReservePositionSchema,
    ShortLiqPeriodItem,
    ShortLiqSimItem,
    ShortLiqSimResponse,
    SnapshotReserveDetail,
    TxHistoryItem,
    TxHistoryResponse,
)

logger = logging.getLogger(__name__)


def _fmt(value: Decimal, decimals: int = 2) -> str:
    quantize = Decimal(10) ** -decimals
    return str(value.quantize(quantize, rounding=ROUND_HALF_UP))


# ── 公共数据缓存（每次进程内复用，减少 RPC 调用） ────────────────────────────

_cache: dict = {}

# 单次 API 触发最多在线补采区块数，防止长时阻塞
_MAX_MARKET_ONLINE_COLLECT = 15


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

    # V2 oracle 返回 ETH/18dec，需归一化为 USD/8dec（与 fetch_block_prices 逻辑一致）
    if contracts.oracle_price_in_eth:
        v3_oracle = w3.eth.contract(address=CONTRACTS_V3.oracle, abi=ORACLE_ABI)
        eth_usd_raw: int = await v3_oracle.functions.getAssetPrice(WETH_ADDRESS).call()
        if eth_usd_raw > 0:
            asset_prices = {
                addr: (p * eth_usd_raw) // (10**18) for addr, p in asset_prices.items()
            }
            # WETH 键存储 eth_usd_raw，供 fetch_user_position 归一化 AccountSummary
            asset_prices[WETH_ADDRESS] = eth_usd_raw
        else:
            logger.warning("[v2] 无法获取实时 ETH/USD 价格，V2 仓位数值将不准确")

    return _cache[cache_key_tokens], _cache[cache_key_configs], asset_prices


async def get_supported_price_assets(
    w3: AsyncWeb3,
    pool: "asyncpg.Pool | None" = None,
    justlend_cfg: object | None = None,
) -> PriceAssetsResponse:
    _ = (w3, pool, justlend_cfg)
    from crawler_shared.api.service import get_supported_price_assets as _shared_impl

    return await _shared_impl()


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

    # 借贷端（做空 ETH）字段
    weth_debt_raw_dec, weth_debt_usd_val = _calc_weth_debt(pos)
    weth_price = _get_weth_price(pos)
    liq_price_rise_val = (
        _calc_liq_price_rise(pos, weth_price) if weth_price > 0 else Decimal("0")
    )

    # 各资产明细，过滤余额为 0 的资产
    reserves: list[ReservePositionSchema] = []
    for r in pos.reserves:
        if r.supply_raw == 0 and r.stable_debt_raw == 0 and r.variable_debt_raw == 0:
            continue
        price = _raw_to_dec(r.price_raw, 8)
        supply_amt = _raw_to_dec(r.supply_raw, r.decimals)
        stable_amt = _raw_to_dec(r.stable_debt_raw, r.decimals)
        variable_amt = _raw_to_dec(r.variable_debt_raw, r.decimals)
        total_debt_amt = stable_amt + variable_amt
        reserves.append(
            ReservePositionSchema(
                symbol=r.symbol,
                token_address=r.token_address,
                price_usd=_fmt(price),
                supply_amount=_fmt(supply_amt, 6),
                supply_usd=_fmt(supply_amt * price),
                stable_debt_amount=_fmt(stable_amt, 6),
                variable_debt_amount=_fmt(variable_amt, 6),
                total_debt_amount=_fmt(total_debt_amt, 6),
                total_debt_usd=_fmt(total_debt_amt * price),
                use_as_collateral=r.usage_as_collateral_enabled,
            )
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
        weth_debt_amount=_fmt(weth_debt_raw_dec / Decimal("1e18"), 6),
        weth_debt_usd=_fmt(weth_debt_usd_val),
        liq_price_rise=_fmt(liq_price_rise_val) if liq_price_rise_val > 0 else "0",
        reserves=reserves,
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
    w3: AsyncWeb3, pool: asyncpg.Pool, address: str, protocol: str = "v3"
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
    # Type narrowing: 排除 EMPTY_POSITION 和 None 后，pos 必定是 UserPosition
    user_pos = cast(UserPosition, pos)

    # 写表缓存：链上数据获取后同步 upsert 到数据库
    col_tables = TABLES_V3 if protocol == "v3" else TABLES_V2
    borrow_tables = TABLES_V3_BORROW if protocol == "v3" else TABLES_V2_BORROW
    try:
        eth_col_amount, _ = _calc_eth_collateral(user_pos)
        if eth_col_amount > 0:
            await upsert_positions(pool, [user_pos], col_tables)
        weth_raw, _ = _calc_weth_debt(user_pos)
        if weth_raw > 0:
            await upsert_positions(pool, [user_pos], borrow_tables)
    except Exception as _upsert_exc:
        logger.warning("写表缓存失败（不影响响应）: %s", _upsert_exc)

    return _format_position(user_pos)


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
    # Type narrowing: 排除 EMPTY_POSITION 和 None 后，pos 必定是 UserPosition
    return _calc_liquidation_line(cast(UserPosition, pos))


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
    session: AsyncSession,
    orderby: str = "liq_price",
    order: str = "asc",
    limit: int = 10,
    protocol: str = "v3",
) -> list[PositionResponse]:
    """从数据库读取已爬取的仓位，按指定字段排序后返回。

    Args:
        session: SQLAlchemy AsyncSession
        orderby: 排序字段，``liquidation_price`` 或 ``health_factor``
        order: 方向，``asc`` 或 ``desc``
        limit: 最多返回多少条（上限 200）
        protocol: aave 协议版本 v2/v3
    """
    order_col = _SORT_COLS.get(orderby, "liq_price")
    order_dir = _SORT_DIRS.get(order, "ASC")
    pos_table, res_table = _tables(protocol)
    eth_upper_sql = ", ".join(f"'{s}'" for s in sorted(_ETH_SYMBOLS))

    sql_text = text(
        f"""
WITH eth_cols AS (
    SELECT
        r.user_address,
        SUM(r.supply_raw / POWER(10, r.decimals::NUMERIC))  AS eth_col_amount,
        SUM(r.supply_usd)                                    AS eth_col_usd
    FROM loan."{res_table}" r
    WHERE UPPER(r.symbol) = ANY(ARRAY[{eth_upper_sql}]::text[])
      AND r.use_as_collateral = true
      AND r.supply_raw > 0
    GROUP BY r.user_address
),
latest_snaps AS (
    SELECT DISTINCT ON (user_address)
        user_address,
        liq_price_weth
    FROM loan.aave_position_snapshots
    WHERE protocol = :protocol
      AND liq_price_weth > 0
    ORDER BY user_address, block_timestamp DESC
)
SELECT
    p.user_address                                            AS address,
    COALESCE(e.eth_col_amount, 0)                             AS eth_collateral_amount,
    COALESCE(e.eth_col_usd, 0)                                AS eth_collateral_usd,
    p.total_collateral_usd,
    p.available_borrows_usd,
    p.total_debt_usd,
    p.health_factor,
    p.ltv,
    p.liq_threshold,
    COALESCE(s.liq_price_weth, p.liq_price)                  AS liq_price
FROM loan."{pos_table}" p
LEFT JOIN eth_cols e     ON e.user_address = p.user_address
LEFT JOIN latest_snaps s ON s.user_address = p.user_address
WHERE COALESCE(s.liq_price_weth, p.liq_price) > 0
  AND COALESCE(s.liq_price_weth, p.liq_price) < 9999999.99
ORDER BY {order_col} {order_dir}
LIMIT :limit
"""
    )

    result = await session.execute(sql_text, {"protocol": protocol, "limit": limit})
    rows = result.fetchall()

    results: list[PositionResponse] = []
    for row in rows:
        hf = Decimal(str(row.health_factor))
        hf_str = "inf" if hf >= _INF_HF_THRESHOLD else _fmt(hf, 4)

        lp = Decimal(str(row.liq_price))
        results.append(
            PositionResponse(
                address=row.address,
                eth_collateral_amount=_fmt(Decimal(str(row.eth_collateral_amount)), 6),
                eth_collateral_usd=_fmt(Decimal(str(row.eth_collateral_usd))),
                total_collateral_usd=_fmt(Decimal(str(row.total_collateral_usd))),
                available_borrows_usd=_fmt(Decimal(str(row.available_borrows_usd))),
                total_debt_usd=_fmt(Decimal(str(row.total_debt_usd))),
                health_factor=hf_str,
                ltv=_fmt(Decimal(str(row.ltv)), 4),
                liq_threshold=_fmt(Decimal(str(row.liq_threshold)), 4),
                liq_price=_fmt(lp) if lp > 0 else "0",
            )
        )
    return results


# Aave V3 WETH 默认清算奖励系数（liquidation_bonus = 5%，即 0.05 on top of debt）
_WETH_LIQ_BONUS = Decimal("1.05")
# Aave V3 单次清算最大可偿还债务比例（close factor）
_V3_CLOSE_FACTOR = Decimal("0.5")

# 清算模拟排序字段白名单
_SIM_SORT_COLS = {
    "liq_price": "liq_price",
    "eth_collateral_amount": "eth_collateral_amount",
    "eth_collateral_usd": "eth_collateral_usd",
    "total_collateral_usd": "total_collateral_usd",
    "total_debt_usd": "total_debt_usd",
}


def _build_simulate_sql(
    order_col: str,
    order_dir: str,
    pos_table: str,
    res_table: str,
    protocol: str,
    use_cap: bool = False,
    use_current_eth_price: bool = False,
) -> str:
    eth_upper_sql = ", ".join(f"'{s}'" for s in sorted(_ETH_SYMBOLS))
    current_price_filter = ""
    if use_current_eth_price:
        current_price_filter = "  AND liq_price < :current_eth_price"
    cap_filter = "  AND liq_price < :cap" if use_cap else ""
    return f"""
WITH eth_cols AS (
    SELECT
        r.user_address,
        SUM(r.supply_raw / POWER(10, r.decimals::NUMERIC))  AS eth_col_amount,
        SUM(r.supply_usd)                                    AS eth_col_usd
    FROM loan."{res_table}" r
    WHERE UPPER(r.symbol) = ANY(ARRAY[{eth_upper_sql}]::text[])
      AND r.use_as_collateral = true
      AND r.supply_raw > 0
    GROUP BY r.user_address
),
all_cols AS (
    SELECT
        r.user_address,
        SUM(r.supply_usd) AS total_collateral_usd_stored
    FROM loan."{res_table}" r
    WHERE r.use_as_collateral = true
      AND r.supply_raw > 0
    GROUP BY r.user_address
),
latest_snaps AS (
    SELECT DISTINCT ON (user_address)
        user_address,
        liq_price_weth
    FROM loan.aave_position_snapshots
    WHERE protocol = '{protocol}'
      AND liq_price_weth > 0
    ORDER BY user_address, block_timestamp DESC
),
base AS (
    SELECT
        p.user_address                                                AS address,
        COALESCE(e.eth_col_amount, 0)                                 AS eth_collateral_amount,
        COALESCE(e.eth_col_amount, 0) * :eth_price                    AS eth_collateral_usd,
        COALESCE(e.eth_col_usd, 0)                                    AS eth_supply_usd_stored,
        COALESCE(c.total_collateral_usd_stored, p.total_collateral_usd, 0)
                                                                    AS total_collateral_usd_stored,
        GREATEST(
            COALESCE(c.total_collateral_usd_stored, p.total_collateral_usd, 0)
            - COALESCE(e.eth_col_usd, 0)
            + COALESCE(e.eth_col_amount, 0) * :eth_price,
            0
        )                                                           AS total_collateral_usd,
        p.total_debt_usd,
        p.health_factor,
        COALESCE(s.liq_price_weth, p.liq_price)                      AS liq_price
    FROM loan."{pos_table}" p
    LEFT JOIN eth_cols e    ON e.user_address = p.user_address
    LEFT JOIN all_cols c    ON c.user_address = p.user_address
    LEFT JOIN latest_snaps s ON s.user_address = p.user_address
)
SELECT * FROM base
WHERE liq_price > 0
  AND liq_price < 9999999.99
  AND total_debt_usd > 0
  AND health_factor > 1
  AND liq_price >= :eth_price
{current_price_filter}
{cap_filter}
ORDER BY {order_col} {order_dir}
"""


async def simulate_liquidation(
    session: AsyncSession,
    eth_price: Decimal,
    orderby: str = "liq_price",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
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
        session: SQLAlchemy AsyncSession
        current_eth_price: 实时 ETH 价格（用于过滤掉 liq_price > 当前价格的仓位，
            即那些只有在 ETH 上涨时才会被清算的做空仓位）。传入后只有
            liq_price <= current_eth_price 的仓位才会被纳入跌价清算模拟。
    """
    order_col = _SIM_SORT_COLS.get(orderby, "liq_price")
    order_dir = "DESC" if order.lower() == "desc" else "ASC"
    pos_table, res_table = _tables(protocol)
    sql_str = _build_simulate_sql(
        order_col,
        order_dir,
        pos_table,
        res_table,
        protocol,
        use_cap=cap is not None,
        use_current_eth_price=current_eth_price is not None,
    )
    # 全量拉取所有触发清算仓位，以便统计数据覆盖全部；limit/offset 仅限制 positions 列表
    params = {"eth_price": float(eth_price)}
    if current_eth_price is not None:
        params["current_eth_price"] = float(current_eth_price)
    if cap is not None:
        params["cap"] = float(cap)

    result = await session.execute(text(sql_str), params)
    rows = result.fetchall()

    total_eth_amount = Decimal("0")
    total_eth_usd = Decimal("0")
    total_liq_usd = Decimal("0")
    all_items: list[LiquidationSimItem] = []

    for row in rows:
        eth_amt = Decimal(str(row.eth_collateral_amount))
        eth_usd = Decimal(str(row.eth_collateral_usd))
        eth_usd_stored = Decimal(str(row.eth_supply_usd_stored))
        total_col_usd_stored = Decimal(str(row.total_collateral_usd_stored))
        total_col_usd = Decimal(str(row.total_collateral_usd))
        debt_usd = Decimal(str(row.total_debt_usd))
        liq_p = Decimal(str(row.liq_price))

        # ETH 抵押品比例过滤：使用爬取时存储价值，避免模拟价格远低于爬取价格时比例失真
        if (
            total_col_usd_stored <= 0
            or eth_usd_stored / total_col_usd_stored < eth_ratio
        ):
            continue

        # 清算人实际可获取的抵押品价值：不超过可用抵押品，含 5% 奖励加码
        seized = min(debt_usd * _WETH_LIQ_BONUS, eth_usd)

        total_eth_amount += eth_amt
        total_eth_usd += eth_usd
        total_liq_usd += seized

        all_items.append(
            LiquidationSimItem(
                address=row.address,
                liq_price=_fmt(liq_p),
                eth_collateral_amount=_fmt(eth_amt, 6),
                eth_collateral_usd=_fmt(eth_usd),
                total_collateral_usd=_fmt(total_col_usd),
                total_debt_usd=_fmt(debt_usd),
            )
        )

    total_count = len(all_items)
    page_start = min(offset, total_count)
    items = all_items[page_start : page_start + limit]

    cap_note = f"；liq_price 上限过滤：< {cap}" if cap is not None else ""
    cur_price_note = (
        f"；当前 ETH 实时价格：${current_eth_price}（仅含跌价清算风险仓位）"
        if current_eth_price is not None
        else ""
    )
    page_note = (
        f"；本次返回第 {page_start + 1} - {page_start + len(items)} 条"
        if total_count > 0
        else "；本次返回 0 条"
    )
    note = (
        f"共 {total_count} 个仓位将在 ETH=${eth_price} 时触发清算"
        f"{page_note}；"
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
def _sql_all_liq_positions(pos_table: str, res_table: str, protocol: str) -> str:
    """构建查询 SQL。
    - 通过 JOIN reserve_positions 表实时计算 eth_collateral_amount/usd（避免依赖可能为 0 的预计算列）。
    - 优先使用 aave_position_snapshots 中经过修正的 liq_price_weth，回退到主表的 liq_price。
    """
    eth_upper_sql = ", ".join(f"'{s}'" for s in sorted(_ETH_SYMBOLS))
    return f"""
WITH eth_cols AS (
    SELECT
        r.user_address,
        SUM(r.supply_raw / POWER(10, r.decimals::NUMERIC))  AS eth_col_amount,
        SUM(r.supply_usd)                                    AS eth_col_usd
    FROM loan."{res_table}" r
    WHERE UPPER(r.symbol) = ANY(ARRAY[{eth_upper_sql}]::text[])
      AND r.use_as_collateral = true
      AND r.supply_raw > 0
    GROUP BY r.user_address
),
latest_snaps AS (
    SELECT DISTINCT ON (user_address)
        user_address,
        liq_price_weth
    FROM loan.aave_position_snapshots
    WHERE protocol = '{protocol}'
      AND liq_price_weth > 0
    ORDER BY user_address, block_timestamp DESC
)
SELECT
    COALESCE(e.eth_col_amount, 0)                AS eth_collateral_amount,
    COALESCE(e.eth_col_usd, 0)                   AS eth_supply_usd_stored,
    p.total_collateral_usd,
    p.total_debt_usd,
    p.health_factor,
    COALESCE(s.liq_price_weth, p.liq_price)      AS liq_price
FROM loan."{pos_table}" p
LEFT JOIN eth_cols e    ON e.user_address = p.user_address
LEFT JOIN latest_snaps s ON s.user_address = p.user_address
WHERE COALESCE(s.liq_price_weth, p.liq_price) > 0
  AND COALESCE(s.liq_price_weth, p.liq_price) < 9999999.99
  AND p.health_factor > 1
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
    rows = await pool.fetch(_sql_all_liq_positions(pos_table, res_table, protocol))
    positions = [
        (
            Decimal(str(r["eth_collateral_amount"])),
            Decimal(str(r["eth_supply_usd_stored"])),
            Decimal(str(r["total_collateral_usd"])),
            Decimal(str(r["total_debt_usd"])),
            Decimal(str(r["health_factor"])),
            Decimal(str(r["liq_price"])),
        )
        for r in rows
        # 仅保留跌价清算仓位：liq_price 必须 <= 当前 ETH 价格
        if (
            (
                current_eth_price is None
                or Decimal(str(r["liq_price"])) < current_eth_price
            )
            and _is_healthy_snapshot(Decimal(str(r["health_factor"])))
        )
    ]

    result: list[LiquidationPeriodItem] = []
    price = start_price
    while price <= end_price:
        total_eth_amount = Decimal("0")
        total_eth_usd = Decimal("0")
        total_liq_usd = Decimal("0")
        cnt = 0
        for (
            eth_amt,
            eth_usd_stored,
            total_col_usd,
            debt_usd,
            _health_factor,
            liq_p,
        ) in positions:
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


async def simulate_liquidation_waterfall(
    pool: asyncpg.Pool,
    protocol: str,
    snapshot_date,
    initial_price_shock_eth: Decimal,
    impact_k: Decimal,
    sell_partition_eth: Decimal,
) -> LiquidationWaterfallResponse:
    """清算瀑布模拟（第二阶段）。

    逻辑：
    1) 对参考价格施加初始冲击；
    2) 在当前价格下识别可清算账户并执行部分清算（close factor=50%）；
    3) 将本轮卖出 ETH 映射为价格冲击，进入下一轮；
    4) 循环直至没有可清算账户或价格冲击趋近 0。

    说明：仅考虑 ETH 价格变化，不联动 ETH 系资产价格。
    """
    from datetime import date as _date

    def _fmt_fixed(value: Decimal, decimals: int) -> str:
        quantize = Decimal(10) ** -decimals
        return format(value.quantize(quantize, rounding=ROUND_HALF_UP), "f")

    if protocol.lower() != "v3":
        raise ValueError("waterfall 目前仅支持 v3")

    day = snapshot_date or datetime.now(timezone.utc).date()
    if not isinstance(day, _date):
        raise ValueError("snapshot_date 必须是 date 或 None")

    table = _daily_positions_table(protocol)
    sql = f"""
        SELECT
            user_address,
            total_debt_usd,
            eth_collateral_amount,
            liq_price,
            health_factor,
            eth_price_usd
        FROM loan."{table}"
        WHERE snapshot_date = $1
          AND liq_price > 0
          AND eth_collateral_amount > 0
          AND total_debt_usd > 0
    """
    rows = await pool.fetch(sql, day)

    if not rows:
        return LiquidationWaterfallResponse(
            total_liquidation_usd="0.00",
            total_eth_sold_amount="0.000000",
            total_eth_sold_value="0.00",
            initial_decline=_fmt_fixed(initial_price_shock_eth, 8),
            cascade_decline="0.00000000",
            total_decline=_fmt_fixed(initial_price_shock_eth, 8),
            total_liquidation_accounts="0",
            max_hf="0",
            liquidation_turns_cnt="0",
            liquidation_turns=[],
            note=(
                f"{day} 无可用日级仓位数据；"
                "liquidation_turns[*].eth_price_decline 仅表示每轮级联跌幅，不含 initial_decline"
            ),
        )

    # eth_price_usd 在同一天理论上相同，按首个正值兜底读取。
    ref_price = Decimal("0")
    for r in rows:
        p = Decimal(str(r["eth_price_usd"]))
        if p > 0:
            ref_price = p
            break

    if ref_price <= 0:
        return LiquidationWaterfallResponse(
            total_liquidation_usd="0.00",
            total_eth_sold_amount="0.000000",
            total_eth_sold_value="0.00",
            initial_decline=_fmt_fixed(initial_price_shock_eth, 8),
            cascade_decline="0.00000000",
            total_decline=_fmt_fixed(initial_price_shock_eth, 8),
            total_liquidation_accounts="0",
            max_hf="0",
            liquidation_turns_cnt="0",
            liquidation_turns=[],
            note=f"{day} 快照缺失 eth_price_usd；未执行级联迭代",
        )

    shocked_price = ref_price * (Decimal("1") - initial_price_shock_eth)
    if shocked_price <= 0:
        shocked_price = Decimal("0.00000001")

    # 账户状态：债务/抵押在每轮清算后递减；liq_threshold 由初始状态推导并固定。
    states: dict[str, dict[str, Decimal]] = {}
    market_eth_amount = Decimal("0")
    for row in rows:
        addr = str(row["user_address"])
        debt_usd = Decimal(str(row["total_debt_usd"]))
        eth_col = Decimal(str(row["eth_collateral_amount"]))
        liq_price = Decimal(str(row["liq_price"]))
        hf = Decimal(str(row["health_factor"]))
        if debt_usd <= 0 or eth_col <= 0 or liq_price <= 0:
            continue

        liq_threshold = debt_usd / (eth_col * liq_price)
        if liq_threshold <= 0:
            continue

        states[addr] = {
            "debt_usd": debt_usd,
            "eth_col": eth_col,
            "liq_threshold": liq_threshold,
            "initial_hf": hf,
        }
        market_eth_amount += eth_col

    if not states:
        return LiquidationWaterfallResponse(
            total_liquidation_usd="0.00",
            total_eth_sold_amount="0.000000",
            total_eth_sold_value="0.00",
            initial_decline=_fmt_fixed(initial_price_shock_eth, 8),
            cascade_decline="0.00000000",
            total_decline=_fmt_fixed(initial_price_shock_eth, 8),
            total_liquidation_accounts="0",
            max_hf="0",
            liquidation_turns_cnt="0",
            liquidation_turns=[],
            note=f"{day} 无可模拟账户（债务/抵押/清算价不完整）",
        )

    total_liq_usd = Decimal("0")
    total_eth_sold = Decimal("0")
    total_eth_sold_value = Decimal("0")
    liquidated_users: set[str] = set()
    total_liq_accounts = 0

    turns: list[LiquidationWaterfallTurnItem] = []
    current_price = shocked_price
    current_decline = initial_price_shock_eth
    max_turns = 200
    eps = Decimal("0.00000001")

    for _ in range(max_turns):
        round_liq_usd = Decimal("0")
        round_sold_eth = Decimal("0")
        round_sold_value = Decimal("0")
        round_accounts = 0

        for addr, st in states.items():
            debt_usd = st["debt_usd"]
            eth_col = st["eth_col"]
            liq_threshold = st["liq_threshold"]

            if debt_usd <= eps or eth_col <= eps or liq_threshold <= eps:
                continue

            # 当前价格下推导触发价：liq_price = debt / (eth_col * liq_threshold)
            liq_price_now = debt_usd / (eth_col * liq_threshold)
            if current_price > liq_price_now:
                continue

            max_repay_debt = debt_usd * _V3_CLOSE_FACTOR
            max_seize_usd = eth_col * current_price
            if max_repay_debt <= eps or max_seize_usd <= eps:
                continue

            repaid_debt = min(max_repay_debt, max_seize_usd / _WETH_LIQ_BONUS)
            seized_usd = repaid_debt * _WETH_LIQ_BONUS
            seized_eth = seized_usd / current_price
            sold_eth = seized_eth * sell_partition_eth
            sold_value = sold_eth * current_price

            if repaid_debt <= eps or seized_eth <= eps:
                continue

            st["debt_usd"] = max(Decimal("0"), debt_usd - repaid_debt)
            st["eth_col"] = max(Decimal("0"), eth_col - seized_eth)

            round_liq_usd += seized_usd
            round_sold_eth += sold_eth
            round_sold_value += sold_value
            round_accounts += 1
            liquidated_users.add(addr)

        if round_accounts == 0:
            break

        total_liq_usd += round_liq_usd
        total_eth_sold += round_sold_eth
        total_eth_sold_value += round_sold_value
        total_liq_accounts += round_accounts

        # 线性冲击：price_impact = k * (sell_volume / daily_volume)
        # daily_volume 采用 (market_eth_amount + cumulative_sold_eth)。
        daily_volume = market_eth_amount + total_eth_sold
        price_impact = (
            impact_k * (round_sold_eth / daily_volume)
            if daily_volume > eps and round_sold_eth > eps
            else Decimal("0")
        )
        if price_impact < 0:
            price_impact = Decimal("0")

        next_price = current_price * (Decimal("1") - price_impact)
        if next_price <= eps:
            next_price = eps

        turns.append(
            LiquidationWaterfallTurnItem(
                eth_sold_amount=_fmt(round_sold_eth, 6),
                eth_sold_value=_fmt(round_sold_value),
                liquidation_accounts=str(round_accounts),
                liquidation_volume_usd=_fmt(round_liq_usd),
                # 当前轮在 current_price 上执行清算；turn[0] 对应 initial shock 后的第一轮。
                eth_price=_fmt_fixed(current_price, 4),
                eth_price_decline=_fmt_fixed(current_decline, 8),
            )
        )

        current_price = next_price
        current_decline = price_impact
        if price_impact <= eps:
            break

    max_hf = Decimal("0")
    for addr in liquidated_users:
        hf = states[addr]["initial_hf"]
        if hf > max_hf:
            max_hf = hf

    cascade_decline = (shocked_price - current_price) / ref_price
    if cascade_decline < 0:
        cascade_decline = Decimal("0")

    total_decline = initial_price_shock_eth + cascade_decline
    if total_decline < 0:
        total_decline = Decimal("0")

    hf_str = "inf" if max_hf >= MAX_HF else _fmt(max_hf, 4)
    return LiquidationWaterfallResponse(
        total_liquidation_usd=_fmt(total_liq_usd),
        total_eth_sold_amount=_fmt(total_eth_sold, 6),
        total_eth_sold_value=_fmt(total_eth_sold_value),
        initial_decline=_fmt_fixed(initial_price_shock_eth, 8),
        cascade_decline=_fmt_fixed(cascade_decline, 8),
        total_decline=_fmt_fixed(total_decline, 8),
        # 定义为累计清算账户次数，等于各轮 liquidation_accounts 求和。
        total_liquidation_accounts=str(total_liq_accounts),
        max_hf=hf_str,
        liquidation_turns_cnt=str(len(turns)),
        liquidation_turns=turns,
        note=(
            "第二阶段：已启用级联迭代（仅 ETH 价格变化，非 ETH 系资产价格固定）；"
            f"impact_k={_fmt(impact_k, 6)}，sell_partition_eth={_fmt(sell_partition_eth, 6)}；"
            "liquidation_turns[0] 对应 initial shock 触发的第一轮清算；"
            "total_liquidation_accounts 为各轮 liquidation_accounts 求和"
        ),
    )


# ── 借贷端（做空 ETH / borrow WETH）清算分析 ─────────────────────────────────

# 借贷端排序字段白名单
_BORROW_SORT_COLS = {
    "liq_price_rise": "liq_price_rise",
    "weth_debt_usd": "weth_debt_usd",
    "total_collateral_usd": "total_collateral_usd",
    "total_debt_usd": "total_debt_usd",
    "health_factor": "health_factor",
}


async def get_sorted_borrow_positions(
    session: AsyncSession,
    orderby: str = "liq_price_rise",
    order: str = "asc",
    limit: int = 10,
    protocol: str = "v3_borrow",
) -> list[BorrowPositionResponse]:
    """从数据库读取借贷端仓位（借入 WETH），按指定字段排序后返回。

    Args:
        session: SQLAlchemy AsyncSession
        orderby: 排序字段，liq_price_rise / weth_debt_usd / total_debt_usd / health_factor
        order:   方向，asc 或 desc
        limit:   最多返回多少条
        protocol: v3_borrow 或 v2_borrow
    """
    from sqlalchemy import text

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
LIMIT :limit
"""
    result = await session.execute(text(sql), {"limit": limit})
    rows = result.fetchall()

    results: list[BorrowPositionResponse] = []
    for row in rows:
        hf = Decimal(str(row.health_factor))
        hf_str = "inf" if hf >= _INF_HF_THRESHOLD else _fmt(hf, 4)
        results.append(
            BorrowPositionResponse(
                address=row.address,
                weth_debt_amount=_fmt(Decimal(str(row.weth_debt_amount)), 6),
                weth_debt_usd=_fmt(Decimal(str(row.weth_debt_usd))),
                total_collateral_usd=_fmt(Decimal(str(row.total_collateral_usd))),
                total_debt_usd=_fmt(Decimal(str(row.total_debt_usd))),
                health_factor=hf_str,
                liq_price_rise=_fmt(Decimal(str(row.liq_price_rise))),
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
    offset: int = 0,
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
    pos_table, res_table = _tables(protocol)

    cap_filter = "  AND p.liq_price_rise < $2::numeric" if cap is not None else ""
    sql = f"""
WITH all_cols AS (
    SELECT
        r.user_address,
        SUM(r.supply_usd) AS total_collateral_usd_stored
    FROM loan.{res_table} r
    WHERE r.use_as_collateral = true
      AND r.supply_raw > 0
    GROUP BY r.user_address
),
eth_cols AS (
    SELECT
        r.user_address,
        SUM(r.supply_raw / POWER(10, r.decimals::NUMERIC)) AS eth_col_amount,
        SUM(r.supply_usd) AS eth_col_usd
    FROM loan.{res_table} r
    WHERE UPPER(r.symbol) = ANY(ARRAY[{", ".join(f"'{s}'" for s in sorted(_ETH_SYMBOLS))}]::text[])
      AND r.use_as_collateral = true
      AND r.supply_raw > 0
    GROUP BY r.user_address
)
SELECT
    p.user_address                                                          AS address,
    p.liq_price_rise,
    (p.weth_debt_raw::numeric / POWER(10::numeric, 18))                     AS weth_debt_amount,
    (p.weth_debt_raw::numeric / POWER(10::numeric, 18)) * $1::numeric       AS weth_debt_usd_sim,
    p.weth_debt_usd                                                         AS weth_debt_usd_stored,
    GREATEST(
        COALESCE(c.total_collateral_usd_stored, p.total_collateral_usd, 0)
        - COALESCE(e.eth_col_usd, 0)
        + COALESCE(e.eth_col_amount, 0) * $1::numeric,
        0
    )                                                                       AS total_collateral_usd,
    p.total_debt_usd
FROM loan.{pos_table} p
LEFT JOIN all_cols c ON c.user_address = p.user_address
LEFT JOIN eth_cols e ON e.user_address = p.user_address
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
    page_start = min(offset, total_count)
    items = all_items[page_start : page_start + limit]

    cap_note = f"；liq_price_rise 上限过滤：< {cap}" if cap is not None else ""
    page_note = (
        f"；本次返回第 {page_start + 1} - {page_start + len(items)} 条"
        if total_count > 0
        else "；本次返回 0 条"
    )
    note = (
        f"共 {total_count} 个仓位将在 ETH=${eth_price} 时触发做空清算"
        f"{page_note}；"
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
    w3: AsyncWeb3,
    symbol: str | None = None,
    address: str | None = None,
    timestamp: int | None = None,
    pool: "asyncpg.Pool | None" = None,
) -> PriceResponse:
    from crawler_shared.api.service import get_price as _shared_impl

    return await _shared_impl(
        w3,
        symbol=symbol,
        address=address,
        pool=pool,
        timestamp=timestamp,
    )


async def get_price_period(
    w3: AsyncWeb3,
    *,
    symbol: str | None = None,
    address: str | None = None,
    start_ts: int,
    end_ts: int,
    interval_minutes: int,
    pool: "asyncpg.Pool | None" = None,
) -> PricePeriodResponse:
    from crawler_shared.api.service import get_price_period_service as _shared_impl

    return await _shared_impl(
        w3,
        pool,
        symbol=symbol,
        address=address,
        start=start_ts,
        end=end_ts,
        interval=interval_minutes,
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
# 历史仓位回放（基于 aave_position_snapshots + aave_history + RPC at block）
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
    row,  # asyncpg.Record from aave_position_snapshots
    detail: bool = False,
    operation_type: str = "",
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
        liq_price=_fmt(Decimal(str(row.get("liq_price_weth") or row["liq_price"])), 2),
        liq_price_rise=_fmt(Decimal(str(row["liq_price_rise"])), 2),
        eth_collateral_amount=_fmt(Decimal(str(row["eth_collateral_amount"])), 6),
        eth_collateral_usd=_fmt(Decimal(str(row["eth_collateral_usd"])), 2),
        weth_debt_amount=_fmt(Decimal(str(row["weth_debt_amount"])), 6),
        weth_debt_usd=_fmt(Decimal(str(row["weth_debt_usd"])), 2),
        operation_type=operation_type,
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
    fresh_briefs = await parse_tx_briefs(pool, uncached_hashes, protocol=protocol)
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
    interval_hours: int = 24,
    detail: bool = False,
    w3: "AsyncWeb3 | None" = None,
) -> "MarketReplayResponse":
    """查询大盘历史快照序列。

    从 loan.aave_v{2|3}_market_totals（汇总表）和可选的
    loan.aave_v{2|3}_market_snapshots（reserve 明细）读取，
    按 interval_hours 小时间隔抽样（每个间隔取时间最近的区块）。

    当 w3 不为 None 时，若检测到时间范围内存在缺失的数据桶，会实时
    通过 RPC 补采缺失区块并写表，随后滚动更新汇总表再返回。
    """
    from .schemas import MarketReplayResponse, MarketReservePoint, MarketSnapshotPoint

    base = protocol.split("_")[0].lower()
    totals_table = f"aave_{base}_market_totals"
    detail_table = f"aave_{base}_market_snapshots"

    from_dt = datetime.fromtimestamp(from_ts, tz=timezone.utc)
    to_dt = datetime.fromtimestamp(to_ts, tz=timezone.utc)

    # 每 interval_hours 小时一个"锚点时刻"，取距该锚点最近的已有区块
    # 使用 DISTINCT ON (day_bucket) 按桶选最近区块，单次查询全部数据点
    interval_epoch = interval_hours * 3600
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

    # ── 在线补采：若有缺失时间桶，实时 RPC 采集写表 ───────────────────────────
    if w3 is not None:
        # 已覆盖的桶 key 集合（UTC epoch 对齐到 interval_epoch 的整数倍）
        covered = {
            (int(r["block_timestamp"].timestamp()) // interval_epoch) * interval_epoch
            for r in rows
        }
        # 期望桶列表：从 from_ts 所在桶到 to_ts 所在桶，步长 interval_epoch
        bk_start = (from_ts // interval_epoch) * interval_epoch
        missing = [
            bk
            for bk in range(bk_start, to_ts + interval_epoch, interval_epoch)
            if bk + interval_epoch > from_ts and bk <= to_ts and bk not in covered
        ]
        if missing:
            from ..market_collector import _block_at_timestamp
            from ..market_collector import (
                collect_block_snapshot as _collect_block_snapshot,
            )
            from ..market_collector import (
                ensure_market_snapshot_table as _ensure_mkt_table,
            )
            from ..market_collector import refresh_market_totals as _refresh_mkt_totals

            if len(missing) > _MAX_MARKET_ONLINE_COLLECT:
                logger.warning(
                    "market_replay[%s]: 缺失 %d 个时间桶，仅补采最近 %d 个",
                    protocol,
                    len(missing),
                    _MAX_MARKET_ONLINE_COLLECT,
                )
                missing = missing[-_MAX_MARKET_ONLINE_COLLECT:]
            logger.info(
                "market_replay[%s]: 开始在线补采 %d 个缺失时间桶",
                protocol,
                len(missing),
            )
            await _ensure_mkt_table(pool, protocol)
            now_unix = int(datetime.now(tz=timezone.utc).timestamp())
            collect_sem = asyncio.Semaphore(12)

            async def _find_and_collect(bk_anchor: int) -> None:
                # 取桶中心时间戳（不超过当前时间 -60s，防止越界最新区块）
                target_ts = min(bk_anchor + interval_epoch // 2, now_unix - 60)
                try:
                    block = await _block_at_timestamp(w3, target_ts, pool)
                    await _collect_block_snapshot(
                        w3, pool, protocol, block, collect_sem
                    )
                except Exception as exc:
                    logger.warning(
                        "market_replay[%s]: 补采桶 %s 失败: %s",
                        protocol,
                        datetime.fromtimestamp(bk_anchor, tz=timezone.utc).isoformat(),
                        exc,
                    )

            await asyncio.gather(*[_find_and_collect(bk) for bk in missing])
            await _refresh_mkt_totals(pool, protocol)
            # 补采完成后重新查询
            rows = await pool.fetch(sql_totals, from_dt, to_dt)

    if not rows:
        return MarketReplayResponse(
            protocol=protocol,
            from_time=from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            to_time=to_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            interval_hours=interval_hours,
            points=[],
            total_points=0,
        )

    selected_blocks = [r["block_number"] for r in rows]

    eth_reserve_map: dict[int, asyncpg.Record] = {}
    if selected_blocks:
        placeholders = ", ".join(f"${i + 1}" for i in range(len(selected_blocks)))
        sql_eth_detail = f"""
            SELECT DISTINCT ON (block_number)
                block_number,
                token_address,
                symbol,
                price_usd,
                total_supply_usd,
                total_debt_usd,
                available_liquidity_usd,
                utilization_rate,
                liquidity_rate_ray,
                variable_borrow_rate_ray,
                stable_borrow_rate_ray
            FROM loan.{detail_table}
            WHERE block_number IN ({placeholders})
              AND UPPER(symbol) IN ('WETH', 'ETH')
            ORDER BY
                block_number,
                CASE
                    WHEN UPPER(symbol) = 'WETH' THEN 0
                    WHEN UPPER(symbol) = 'ETH' THEN 1
                    ELSE 2
                END,
                total_supply_usd DESC
        """
        eth_detail_rows = await pool.fetch(sql_eth_detail, *selected_blocks)
        eth_reserve_map = {int(dr["block_number"]): dr for dr in eth_detail_rows}

    # 只有 detail=true 时才查 reserve 明细
    reserve_map: dict[int, list[MarketReservePoint]] = {}
    if detail and selected_blocks:
        placeholders = ", ".join(f"${i + 1}" for i in range(len(selected_blocks)))
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
        eth_row = eth_reserve_map.get(blk)
        eth_price_usd = (
            _fmt(Decimal(str(eth_row["price_usd"])), 8)
            if eth_row is not None
            else _fmt(Decimal("0"), 8)
        )
        eth_total_supply_usd = (
            _fmt(Decimal(str(eth_row["total_supply_usd"])), 2)
            if eth_row is not None
            else _fmt(Decimal("0"), 2)
        )
        eth_total_debt_usd = (
            _fmt(Decimal(str(eth_row["total_debt_usd"])), 2)
            if eth_row is not None
            else _fmt(Decimal("0"), 2)
        )
        eth_available_liquidity_usd = (
            _fmt(Decimal(str(eth_row["available_liquidity_usd"])), 2)
            if eth_row is not None
            else _fmt(Decimal("0"), 2)
        )
        eth_utilization_rate = (
            _fmt(Decimal(str(eth_row["utilization_rate"])), 8)
            if eth_row is not None
            else _fmt(Decimal("0"), 8)
        )
        eth_supply_apy = (
            _fmt(Decimal(str(eth_row["liquidity_rate_ray"])) / _RAY, 8)
            if eth_row is not None
            else _fmt(Decimal("0"), 8)
        )
        eth_variable_borrow_apy = (
            _fmt(Decimal(str(eth_row["variable_borrow_rate_ray"])) / _RAY, 8)
            if eth_row is not None
            else _fmt(Decimal("0"), 8)
        )
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
                eth_price_usd=eth_price_usd,
                eth_total_supply_usd=eth_total_supply_usd,
                eth_total_debt_usd=eth_total_debt_usd,
                eth_available_liquidity_usd=eth_available_liquidity_usd,
                eth_utilization_rate=eth_utilization_rate,
                eth_supply_apy=eth_supply_apy,
                eth_variable_borrow_apy=eth_variable_borrow_apy,
                reserves=reserve_map.get(blk, []),
            )
        )

    return MarketReplayResponse(
        protocol=protocol,
        from_time=from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        to_time=to_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        interval_hours=interval_hours,
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
    2. 查 aave_position_snapshots 确认哪些 tx 已缓存
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
                        pool, [r["meta"] for r in batch_records]
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
        points.append(
            _format_snapshot_point(
                row, detail=detail, operation_type=t.get("operation_type", "")
            )
        )
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


# ── 日级仓位统计序列 ─────────────────────────────────────────────────────────


def _daily_positions_table(protocol: str) -> str:
    """返回日级仓位表名（不含 schema）。"""
    ver = "v2" if protocol.lower().startswith("v2") else "v3"
    return f"aave_{ver}_eth_daily_positions"


def _daily_reserve_positions_table(protocol: str) -> str:
    """返回日级 reserve 仓位表名（不含 schema）。"""
    ver = "v2" if protocol.lower().startswith("v2") else "v3"
    return f"aave_{ver}_eth_daily_reserve_positions"


def _is_healthy_snapshot(health_factor: Decimal) -> bool:
    return health_factor >= MAX_HF or health_factor > Decimal("1")


async def get_daily_user_position(
    pool: asyncpg.Pool,
    address: str,
    snapshot_date,
    protocol: str = "v3",
) -> PositionResponse | None:
    pos_table = _daily_positions_table(protocol)
    res_table = _daily_reserve_positions_table(protocol)

    pos_row = await pool.fetchrow(
        f"""
        SELECT
            user_address,
            total_collateral_usd,
            available_borrows_usd,
            total_debt_usd,
            health_factor,
            ltv,
            liq_threshold,
            liq_price,
            liq_price_rise,
            eth_collateral_amount,
            eth_collateral_usd,
            weth_debt_raw,
            weth_debt_usd
        FROM loan."{pos_table}"
        WHERE snapshot_date = $1
          AND lower(user_address) = lower($2)
        LIMIT 1
        """,
        snapshot_date,
        address,
    )
    if pos_row is None:
        return None

    reserve_rows = await pool.fetch(
        f"""
        SELECT
            symbol,
            token_address,
            decimals,
            price_usd,
            supply_raw,
            supply_usd,
            stable_debt_raw,
            variable_debt_raw,
            total_debt_usd,
            use_as_collateral
        FROM loan."{res_table}"
        WHERE snapshot_date = $1
          AND lower(user_address) = lower($2)
          AND (supply_raw > 0 OR stable_debt_raw > 0 OR variable_debt_raw > 0)
        ORDER BY GREATEST(supply_usd, total_debt_usd) DESC, symbol ASC
        """,
        snapshot_date,
        address,
    )

    hf_val = Decimal(str(pos_row["health_factor"]))
    hf_str = "inf" if hf_val >= MAX_HF else _fmt(hf_val, 4)

    reserves: list[ReservePositionSchema] = []
    for row in reserve_rows:
        decimals = int(row["decimals"])
        denom = Decimal(10) ** decimals
        supply_amount = Decimal(str(row["supply_raw"])) / denom
        stable_debt_amount = Decimal(str(row["stable_debt_raw"])) / denom
        variable_debt_amount = Decimal(str(row["variable_debt_raw"])) / denom
        total_debt_amount = stable_debt_amount + variable_debt_amount

        reserves.append(
            ReservePositionSchema(
                symbol=str(row["symbol"]),
                token_address=str(row["token_address"]),
                price_usd=_fmt(Decimal(str(row["price_usd"]))),
                supply_amount=_fmt(supply_amount, 6),
                supply_usd=_fmt(Decimal(str(row["supply_usd"]))),
                stable_debt_amount=_fmt(stable_debt_amount, 6),
                variable_debt_amount=_fmt(variable_debt_amount, 6),
                total_debt_amount=_fmt(total_debt_amount, 6),
                total_debt_usd=_fmt(Decimal(str(row["total_debt_usd"]))),
                use_as_collateral=bool(row["use_as_collateral"]),
            )
        )

    return PositionResponse(
        address=str(pos_row["user_address"]),
        eth_collateral_amount=_fmt(Decimal(str(pos_row["eth_collateral_amount"])), 6),
        eth_collateral_usd=_fmt(Decimal(str(pos_row["eth_collateral_usd"]))),
        total_collateral_usd=_fmt(Decimal(str(pos_row["total_collateral_usd"]))),
        available_borrows_usd=_fmt(Decimal(str(pos_row["available_borrows_usd"]))),
        total_debt_usd=_fmt(Decimal(str(pos_row["total_debt_usd"]))),
        health_factor=hf_str,
        ltv=_fmt(Decimal(str(pos_row["ltv"])), 4),
        liq_threshold=_fmt(Decimal(str(pos_row["liq_threshold"])), 4),
        liq_price=_fmt(Decimal(str(pos_row["liq_price"]))),
        weth_debt_amount=_fmt(
            Decimal(str(pos_row["weth_debt_raw"])) / Decimal("1e18"),
            6,
        ),
        weth_debt_usd=_fmt(Decimal(str(pos_row["weth_debt_usd"]))),
        liq_price_rise=_fmt(Decimal(str(pos_row["liq_price_rise"]))),
        reserves=reserves,
    )


async def get_positions_period(
    pool: asyncpg.Pool,
    protocol: str,
    start_ts: int,
    end_ts: int,
    interval_days: int = 1,
    sim_eth_price_distance: float = 0.0,
) -> list[PositionPeriodItem]:
    """查询日级仓位清算统计时序数据。

    语义：在每个快照日，若 ETH 价格波动至 sim_eth_price，统计会被触发清算的仓位。
    - 价格下跌（sim_eth_price < eth_price）：liq_price >= sim_eth_price 的仓位被清算（多头）
    - 价格上涨（sim_eth_price > eth_price）：liq_price_rise > 0 且 liq_price_rise <= sim_eth_price 的仓位被清算（空头）
    - 累积语义：跌20%包含跌10%的清算（liq_price 越高越先被清算）

    :param start_ts:               起始 Unix 时间戳（秒）
    :param end_ts:                 结束 Unix 时间戳（秒）
    :param interval_days:          采样间隔（天），≥ 1
    :param sim_eth_price_distance: ETH 价格模拟偏移（百分制，如 -10 表示跌 10%）
    """
    start_date = datetime.fromtimestamp(start_ts, tz=timezone.utc).date()
    end_date = datetime.fromtimestamp(end_ts, tz=timezone.utc).date()

    table = _daily_positions_table(protocol)
    # 行级查询，在内存中聚合以支持按 sim_price 过滤清算仓位
    sql = f"""
        SELECT
            snapshot_date,
            eth_collateral_amount,
            health_factor,
            liq_price,
            liq_price_rise,
            weth_debt_raw,
            eth_price_usd
        FROM loan."{table}"
        WHERE snapshot_date >= $1
          AND snapshot_date <= $2
        ORDER BY snapshot_date
    """
    rows = await pool.fetch(sql, start_date, end_date)

    # 按日分组
    by_date: dict = defaultdict(list)
    for r in rows:
        by_date[r["snapshot_date"]].append(r)

    sim_factor = Decimal(str(1 + sim_eth_price_distance / 100))
    sampled_dates = [d for i, d in enumerate(sorted(by_date)) if i % interval_days == 0]

    _WETH_DECIMALS = Decimal("1000000000000000000")  # 1e18

    result: list[PositionPeriodItem] = []
    for d in sampled_dates:
        day_rows = by_date[d]
        eth_price = Decimal(
            str(
                next(
                    (r["eth_price_usd"] for r in day_rows if r["eth_price_usd"] > 0), 0
                )
            )
        )
        sim_price = eth_price * sim_factor
        price_dropped = sim_price < eth_price
        price_rose = sim_price > eth_price

        total_eth_col = Decimal("0")
        total_weth_debt = Decimal("0")
        cnt = 0

        for r in day_rows:
            eth_col = Decimal(str(r["eth_collateral_amount"]))
            if eth_col <= 0:
                continue
            health_factor = Decimal(str(r["health_factor"]))
            if not _is_healthy_snapshot(health_factor):
                continue
            liq_price = Decimal(str(r["liq_price"]))
            liq_price_rise = Decimal(str(r["liq_price_rise"]))
            if price_dropped and liq_price >= eth_price:
                continue
            if price_rose and liq_price_rise <= eth_price:
                continue

            liquidated = (
                price_dropped and liq_price > 0 and liq_price >= sim_price
            ) or (price_rose and liq_price_rise > 0 and liq_price_rise <= sim_price)
            if not liquidated:
                continue

            cnt += 1
            total_eth_col += eth_col
            total_weth_debt += Decimal(str(r["weth_debt_raw"])) / _WETH_DECIMALS

        result.append(
            PositionPeriodItem(
                snapshot_date=str(d),
                liquidation_cnt=str(cnt),
                total_eth_collateral_amount=_fmt(total_eth_col, 6),
                total_eth_collateral_usd=_fmt(total_eth_col * sim_price),
                total_weth_debt_amount=_fmt(total_weth_debt, 6),
                total_weth_debt_usd=_fmt(total_weth_debt * sim_price),
                eth_price=_fmt(eth_price),
                sim_eth_price=_fmt(sim_price),
            )
        )
    return result


async def get_positions_period_detail(
    pool: asyncpg.Pool,
    protocol: str,
    snapshot_date,
    side: str,
    sim_eth_price_distance: float,
    orderby: str = "liq_price",
    order: str = "desc",
    limit: int = 20,
    offset: int = 0,
) -> HistoricalLiquidationDetailResponse:
    table = _daily_positions_table(protocol)
    rows = await pool.fetch(
        f"""
        SELECT
            user_address,
            total_collateral_usd,
            total_debt_usd,
            health_factor,
            liq_price,
            liq_price_rise,
            eth_collateral_amount,
            eth_collateral_usd,
            weth_debt_raw,
            eth_price_usd
        FROM loan."{table}"
        WHERE snapshot_date = $1
        """,
        snapshot_date,
    )

    eth_price = Decimal(
        str(next((row["eth_price_usd"] for row in rows if row["eth_price_usd"] > 0), 0))
    )
    sim_price = eth_price * Decimal(str(1 + sim_eth_price_distance / 100))

    all_items: list[HistoricalLiquidationDetailItem] = []
    total_eth_collateral_amount = Decimal("0")
    total_eth_collateral_usd = Decimal("0")
    total_weth_debt_amount = Decimal("0")
    total_weth_debt_usd = Decimal("0")
    total_liquidation_usd = Decimal("0")

    for row in rows:
        total_collateral_usd_stored = Decimal(str(row["total_collateral_usd"]))
        total_debt_usd = Decimal(str(row["total_debt_usd"]))
        health_factor = Decimal(str(row["health_factor"]))
        if not _is_healthy_snapshot(health_factor):
            continue
        liq_price = Decimal(str(row["liq_price"]))
        liq_price_rise = Decimal(str(row["liq_price_rise"]))
        eth_collateral_amount = Decimal(str(row["eth_collateral_amount"]))
        eth_collateral_usd_stored = Decimal(str(row["eth_collateral_usd"]))
        weth_debt_amount = Decimal(str(row["weth_debt_raw"])) / Decimal("1e18")

        eth_collateral_usd_sim = eth_collateral_amount * sim_price
        total_collateral_usd_sim = max(
            total_collateral_usd_stored
            - eth_collateral_usd_stored
            + eth_collateral_usd_sim,
            Decimal("0"),
        )
        weth_debt_usd_sim = weth_debt_amount * sim_price

        liquidated = (
            liq_price_rise > eth_price and liq_price_rise <= sim_price
            if side == "borrow"
            else liq_price > 0 and liq_price < eth_price and liq_price >= sim_price
        )
        if not liquidated:
            continue

        if side == "borrow":
            total_weth_debt_amount += weth_debt_amount
            total_weth_debt_usd += weth_debt_usd_sim
            total_liquidation_usd += min(
                weth_debt_usd_sim * _WETH_LIQ_BONUS,
                total_collateral_usd_sim,
            )
        else:
            total_eth_collateral_amount += eth_collateral_amount
            total_eth_collateral_usd += eth_collateral_usd_sim
            total_liquidation_usd += min(
                total_debt_usd * _WETH_LIQ_BONUS,
                eth_collateral_usd_sim,
            )

        all_items.append(
            HistoricalLiquidationDetailItem(
                address=str(row["user_address"]),
                liq_price=_fmt(liq_price) if liq_price > 0 else "0",
                liq_price_rise=_fmt(liq_price_rise) if liq_price_rise > 0 else "0",
                eth_collateral_amount=_fmt(eth_collateral_amount, 6),
                eth_collateral_usd=_fmt(eth_collateral_usd_sim),
                total_collateral_usd=_fmt(total_collateral_usd_sim),
                total_debt_usd=_fmt(total_debt_usd),
                weth_debt_amount=_fmt(weth_debt_amount, 6),
                weth_debt_usd=_fmt(weth_debt_usd_sim),
            )
        )

    collateral_sort_cols = {
        "liq_price": "liq_price",
        "eth_collateral_usd": "eth_collateral_usd",
        "total_collateral_usd": "total_collateral_usd",
        "total_debt_usd": "total_debt_usd",
    }
    borrow_sort_cols = {
        "liq_price_rise": "liq_price_rise",
        "weth_debt_usd": "weth_debt_usd",
        "total_collateral_usd": "total_collateral_usd",
    }
    sort_field = (
        borrow_sort_cols.get(orderby, "liq_price_rise")
        if side == "borrow"
        else collateral_sort_cols.get(orderby, "liq_price")
    )
    all_items.sort(
        key=lambda item: Decimal(getattr(item, sort_field) or "0"),
        reverse=order.lower() == "desc",
    )

    total_count = len(all_items)
    page_start = min(offset, total_count)
    items = all_items[page_start : page_start + limit]
    range_note = (
        f"第 {page_start + 1} - {page_start + len(items)} 条"
        if total_count > 0
        else "0 条"
    )
    note = (
        f"历史仓位数据截止 {snapshot_date} 00:00 UTC；"
        f"本次按 ETH 价格变动 {sim_eth_price_distance}% 模拟，返回 {range_note}；"
        "仓位展开明细同样基于该时点快照，不反映当日盘中变化。"
    )

    return HistoricalLiquidationDetailResponse(
        snapshot_date=str(snapshot_date),
        simulated_eth_price=_fmt(sim_price),
        positions=items,
        positions_cnt=str(total_count),
        total_eth_collateral_amount=_fmt(total_eth_collateral_amount, 6),
        total_eth_collateral_usd=_fmt(total_eth_collateral_usd),
        total_weth_debt_amount=_fmt(total_weth_debt_amount, 6),
        total_weth_debt_usd=_fmt(total_weth_debt_usd),
        total_liquidation_usd=_fmt(total_liquidation_usd),
        note=note,
    )
