"""
业务逻辑层。
- 实时从链上查询用户仓位
- 计算 ETH 清算价格
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal, ROUND_HALF_UP

from web3 import AsyncWeb3

from ..models import ReservePosition, UserPosition
from ..rpc import (
    fetch_user_position,
    get_all_reserve_tokens,
    get_assets_prices,
    get_reserve_config,
)
from .schemas import (
    AccountSummarySchema,
    LiquidationLineResponse,
    PositionResponse,
    ReservePositionSchema,
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
    if hf_raw >= _MAX_UINT256:
        hf_str = "inf"
    else:
        hf_str = _fmt(_raw_to_dec(hf_raw, 18), 4)

    summary = AccountSummarySchema(
        total_collateral_usd=_fmt(_raw_to_dec(s.total_collateral_base, 8)),
        total_debt_usd=_fmt(_raw_to_dec(s.total_debt_base, 8)),
        available_borrows_usd=_fmt(_raw_to_dec(s.available_borrows_base, 8)),
        health_factor=hf_str,
        ltv=_fmt(Decimal(s.ltv) / Decimal(10000), 4),
        liq_threshold=_fmt(Decimal(s.current_liquidation_threshold) / Decimal(10000), 4),
    )

    reserves: list[ReservePositionSchema] = []
    for r in pos.reserves:
        price = _raw_to_dec(r.price_raw, 8)
        supply = _raw_to_dec(r.supply_raw, r.decimals)
        stable = _raw_to_dec(r.stable_debt_raw, r.decimals)
        variable = _raw_to_dec(r.variable_debt_raw, r.decimals)
        total_debt = stable + variable
        reserves.append(
            ReservePositionSchema(
                symbol=r.symbol,
                token_address=r.token_address,
                price_usd=_fmt(price),
                supply_amount=_fmt(supply, 6),
                supply_usd=_fmt(supply * price),
                stable_debt_amount=_fmt(stable, 6),
                variable_debt_amount=_fmt(variable, 6),
                total_debt_amount=_fmt(total_debt, 6),
                total_debt_usd=_fmt(total_debt * price),
                use_as_collateral=r.usage_as_collateral_enabled,
            )
        )

    return PositionResponse(
        address=pos.user_address,
        block_number=pos.block_number,
        summary=summary,
        reserves=reserves,
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
    if pos is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"无法查询地址 {address} 的仓位，请确认地址有效且有 Aave 仓位")
    return _format_position(pos)


async def get_liquidation_line(w3: AsyncWeb3, address: str) -> LiquidationLineResponse:
    reserve_tokens, reserve_configs, asset_prices = await _get_common_data(w3)
    sem = asyncio.Semaphore(1)
    pos = await fetch_user_position(
        w3, address, reserve_tokens, reserve_configs, asset_prices, sem
    )
    if pos is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"无法查询地址 {address} 的仓位")
    return _calc_liquidation_line(pos)
