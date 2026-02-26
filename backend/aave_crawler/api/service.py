"""
业务逻辑层。
- 实时从链上查询用户仓位
- 计算 ETH liq_price
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal, ROUND_HALF_UP

from web3 import AsyncWeb3

from ..models import ReservePosition, UserPosition
from ..rpc import (
    EMPTY_POSITION,
    fetch_user_position,
    get_all_reserve_tokens,
    get_assets_prices,
    get_reserve_config,
)
from .schemas import (
    LiquidationLineResponse,
    PositionResponse,
    PriceResponse,
)

logger = logging.getLogger(__name__)

# ETH/WETH 识别关键词
_ETH_SYMBOLS = {"WETH", "ETH", "cbETH", "wstETH", "rETH"}

_MAX_UINT256 = (1 << 256) - 1


def _fmt(value: Decimal, decimals: int = 2) -> str:
    quantize = Decimal(10) ** -decimals
    return str(value.quantize(quantize, rounding=ROUND_HALF_UP))


def _raw_to_dec(raw: int, decimals: int) -> Decimal:
    return Decimal(raw) / Decimal(10 ** decimals)


# ── 公共数据缓存（每次进程内复用，减少 RPC 调用） ────────────────────────────

_cache: dict = {}


async def _get_common_data(w3: AsyncWeb3) -> tuple:
    """缓存当次进程内的储备资产列表 / 配置（不缓存价格，价格每次实时获取）"""
    if "reserve_tokens" not in _cache:
        reserve_tokens = await get_all_reserve_tokens(w3)
        token_addresses = [rt.token_address for rt in reserve_tokens]
        configs = await asyncio.gather(
            *[get_reserve_config(w3, a) for a in token_addresses],
            return_exceptions=True,
        )
        reserve_configs = {
            a: c
            for a, c in zip(token_addresses, configs)
            if not isinstance(c, Exception)
        }
        _cache["reserve_tokens"] = reserve_tokens
        _cache["reserve_configs"] = reserve_configs
        _cache["token_addresses"] = token_addresses
        logger.info("公共数据已缓存，储备资产数量: %d", len(reserve_tokens))

    # 价格每次重新拉取
    prices = await get_assets_prices(w3, _cache["token_addresses"])
    asset_prices = dict(zip(_cache["token_addresses"], prices))

    return _cache["reserve_tokens"], _cache["reserve_configs"], asset_prices


def _format_position(pos: UserPosition) -> PositionResponse:
    s = pos.summary

    hf_raw = s.health_factor
    hf_str = "inf" if hf_raw >= _MAX_UINT256 else _fmt(_raw_to_dec(hf_raw, 18), 4)

    total_debt = _raw_to_dec(s.total_debt_base, 8)
    liq_threshold = Decimal(s.current_liquidation_threshold) / Decimal(10000)

    # 找 ETH/WETH 抵押仓位
    eth_reserve: ReservePosition | None = None
    for r in pos.reserves:
        if r.symbol.upper() in _ETH_SYMBOLS and r.usage_as_collateral_enabled and r.supply_raw > 0:
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
    if total_debt == 0 or eth_amount == 0 or liq_threshold == 0:
        liq_price_str = "0"
    else:
        # 其他（非 ETH）抵押品的加权安全垫
        other_safe = Decimal("0")
        for r in pos.reserves:
            if r.symbol.upper() in _ETH_SYMBOLS:
                continue
            if not r.usage_as_collateral_enabled or r.supply_raw == 0:
                continue
            other_safe += _raw_to_dec(r.supply_raw, r.decimals) * _raw_to_dec(r.price_raw, 8) * liq_threshold
        numerator = total_debt - other_safe
        liq_price_str = "0" if numerator <= 0 else _fmt(numerator / (eth_amount * liq_threshold))

    return PositionResponse(
        address=pos.user_address,
        eth_collateral_amount=eth_collateral_amount,
        eth_collateral_usd=eth_collateral_usd,
        total_debt_usd=_fmt(total_debt),
        health_factor=hf_str,
        ltv=_fmt(Decimal(s.ltv) / Decimal(10000), 4),
        liq_threshold=_fmt(liq_threshold, 4),
        liq_price=liq_price_str,
    )


def _calc_liquidation_line(pos: UserPosition) -> LiquidationLineResponse:
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

    total_collateral = _raw_to_dec(s.total_collateral_base, 8)
    total_debt = _raw_to_dec(s.total_debt_base, 8)
    liq_threshold = Decimal(s.current_liquidation_threshold) / Decimal(10000)

    # 找 ETH/WETH 抵押仓位
    eth_reserve: ReservePosition | None = None
    for r in pos.reserves:
        if r.symbol.upper() in _ETH_SYMBOLS and r.usage_as_collateral_enabled and r.supply_raw > 0:
            eth_reserve = r
            break

    addr = pos.user_address

    # 无借贷情况
    if total_debt == 0:
        current_eth_price = (
            _raw_to_dec(eth_reserve.price_raw, 8) if eth_reserve else Decimal("0")
        )
        return LiquidationLineResponse(
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
        return LiquidationLineResponse(
            address=addr,
            current_eth_price_usd="0",
            liquidation_eth_price_usd="0",
            distance_pct="0",
            health_factor=hf_str,
            note="未发现 ETH/WETH 抵押仓位，无法计算 ETH 清算价",
        )

    current_eth_price = _raw_to_dec(eth_reserve.price_raw, 8)
    eth_amount = _raw_to_dec(eth_reserve.supply_raw, eth_reserve.decimals)

    if eth_amount == 0 or liq_threshold == 0:
        return LiquidationLineResponse(
            address=addr,
            current_eth_price_usd=_fmt(current_eth_price),
            liquidation_eth_price_usd="0",
            distance_pct="0",
            health_factor=hf_str,
            note="ETH 供给量或清算阈值为 0，无法计算",
        )

    # 其他（非 ETH）抵押品的加权安全垫
    other_safe = Decimal("0")
    for r in pos.reserves:
        if r.symbol.upper() in _ETH_SYMBOLS:
            continue
        if not r.usage_as_collateral_enabled or r.supply_raw == 0:
            continue
        price = _raw_to_dec(r.price_raw, 8)
        amount = _raw_to_dec(r.supply_raw, r.decimals)
        # 用 summary 的 liq_threshold 作为近似（精确需逐资产查配置）
        other_safe += amount * price * liq_threshold

    # P * eth_amount * liq_threshold = total_debt - other_safe
    numerator = total_debt - other_safe
    if numerator <= 0:
        # other_safe 已足以覆盖 debt，ETH 价格降到 0 也不会清算
        liq_price = Decimal("0")
        distance_pct = "inf"
    else:
        liq_price = numerator / (eth_amount * liq_threshold)
        distance = (current_eth_price - liq_price) / current_eth_price * 100
        distance_pct = _fmt(distance, 2)

    return LiquidationLineResponse(
        address=addr,
        current_eth_price_usd=_fmt(current_eth_price),
        liquidation_eth_price_usd=_fmt(liq_price),
        distance_pct=distance_pct,
        health_factor=hf_str,
    )


# ── 对外接口 ──────────────────────────────────────────────────────────────────

async def get_user_position(w3: AsyncWeb3, address: str) -> PositionResponse:
    reserve_tokens, reserve_configs, asset_prices = await _get_common_data(w3)
    sem = asyncio.Semaphore(1)
    pos = await fetch_user_position(
        w3, address, reserve_tokens, reserve_configs, asset_prices, sem
    )
    from fastapi import HTTPException
    if pos is EMPTY_POSITION:
        raise HTTPException(status_code=404, detail=f"地址 {address} 当前在 Aave 无任何仓位（已平仓或从未使用）")
    if pos is None:
        raise HTTPException(status_code=502, detail=f"查询地址 {address} 时 RPC 调用失败，请稍后重试")
    return _format_position(pos)


async def get_liquidation_line(w3: AsyncWeb3, address: str) -> LiquidationLineResponse:
    reserve_tokens, reserve_configs, asset_prices = await _get_common_data(w3)
    sem = asyncio.Semaphore(1)
    pos = await fetch_user_position(
        w3, address, reserve_tokens, reserve_configs, asset_prices, sem
    )
    from fastapi import HTTPException
    if pos is EMPTY_POSITION:
        raise HTTPException(status_code=404, detail=f"地址 {address} 当前在 Aave 无任何仓位（已平仓或从未使用）")
    if pos is None:
        raise HTTPException(status_code=502, detail=f"查询地址 {address} 时 RPC 调用失败，请稍后重试")
    return _calc_liquidation_line(pos)


# ── DB 批量查询（预爬取数据） ──────────────────────────────────────────────────

# 健康系数阈值：DB 中 ∞ 存为 Decimal("1e18")，大于该阈值视为 inf
_INF_HF_THRESHOLD = Decimal("1e15")

# 合法的排序字段白名单（防止 SQL 注入）
_SORT_COLS = {
    "liquidation_price": "liq_price",
    "health_factor": "health_factor",
}
_SORT_DIRS = {"asc": "ASC", "desc": "DESC"}


async def get_sorted_positions(
    pool,
    orderby: str = "liquidation_price",
    order: str = "asc",
    limit: int = 10,
) -> list[PositionResponse]:
    """从数据库读取已爬取的仓位，按指定字段排序后返回。

    Args:
        pool: asyncpg 连接池
        orderby: 排序字段，``liquidation_price`` 或 ``health_factor``
        order: 方向，``asc`` 或 ``desc``
        limit: 最多返回多少条（上限 200）
    """
    order_col = _SORT_COLS.get(orderby, "liq_price")
    order_dir = _SORT_DIRS.get(order, "ASC")

    sql = f"""
WITH eth_col AS (
    SELECT
        user_address,
        (supply_raw::numeric / POWER(10::numeric, decimals)) AS eth_amount,
        supply_usd::numeric                                   AS eth_collateral_usd
    FROM loan.aave_v3_eth_reserve_positions
    WHERE symbol IN ('WETH', 'ETH', 'cbETH', 'wstETH', 'rETH')
      AND use_as_collateral = true
      AND supply_raw > 0
),
computed AS (
    SELECT
        p.user_address                                            AS address,
        COALESCE(e.eth_amount,        0::numeric)                AS eth_collateral_amount,
        COALESCE(e.eth_collateral_usd, 0::numeric)               AS eth_collateral_usd,
        p.total_debt_usd,
        p.health_factor,
        p.ltv,
        p.liq_threshold,
        CASE
            WHEN p.total_debt_usd = 0
              OR COALESCE(e.eth_amount, 0::numeric) = 0
              OR p.liq_threshold = 0
            THEN 0::numeric
            ELSE p.total_debt_usd
                 / (COALESCE(e.eth_amount, 0::numeric) * p.liq_threshold)
        END AS liq_price
    FROM loan.aave_v3_eth_positions p
    LEFT JOIN eth_col e ON p.user_address = e.user_address
)
SELECT * FROM computed
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
                eth_collateral_amount=_fmt(Decimal(str(row["eth_collateral_amount"])), 6),
                eth_collateral_usd=_fmt(Decimal(str(row["eth_collateral_usd"]))),
                total_debt_usd=_fmt(Decimal(str(row["total_debt_usd"]))),
                health_factor=hf_str,
                ltv=_fmt(Decimal(str(row["ltv"])), 4),
                liq_threshold=_fmt(Decimal(str(row["liq_threshold"])), 4),
                liq_price=_fmt(lp) if lp > 0 else "0",
            )
        )
    return results


async def get_eth_price(w3: AsyncWeb3, asset: str, timestamp: int | None = None) -> PriceResponse:
    """获取指定资产的 USD 价格。

    - ``timestamp=None``：从链上 Aave Oracle 实时查询
    - ``timestamp=<unix_ts>``：从 DeFiLlama Coins API 查询历史价格

    Args:
        w3:        AsyncWeb3 实例
        asset:     资产符号，如 ``eth``、``wbtc``；大小写不敏感
        timestamp: Unix 时间戳（秒），None 表示查当前价格
    """
    import time as _time
    import aiohttp
    from datetime import datetime, timezone
    from fastapi import HTTPException

    def _ts_to_utc_str(ts: int) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 预热缓存，确保 reserve_tokens 已加载
    await _get_common_data(w3)

    # "eth" 在 Aave 中以 WETH 表示
    target = asset.upper()
    if target == "ETH":
        target = "WETH"

    reserve_tokens = _cache["reserve_tokens"]
    matching = [rt for rt in reserve_tokens if rt.symbol.upper() == target]
    if not matching:
        raise HTTPException(status_code=404, detail=f"未找到资产 '{asset}'，请确认符号正确")

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
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise HTTPException(
                            status_code=502,
                            detail=f"DeFiLlama 返回 HTTP {resp.status}",
                        )
                    data = await resp.json()
        except aiohttp.ClientError as exc:
            raise HTTPException(status_code=502, detail=f"无法连接 DeFiLlama: {exc}") from exc

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
