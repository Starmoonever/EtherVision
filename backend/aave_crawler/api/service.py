"""
业务逻辑层。
- 实时从链上查询用户仓位
- 计算 ETH liq_price
"""

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
    LiqPriceResponse,
    LiquidationSimItem,
    LiquidationSimResponse,
    HistoricalPositionResponse,
    HistoricalReserveDetail,
    PositionResponse,
    PriceResponse,
    PricePeriodItem,
    PricePeriodResponse,
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

    if eth_amount == 0 or liq_threshold == 0:
        return LiqPriceResponse(
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

    return LiqPriceResponse(
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


async def get_liq_price(w3: AsyncWeb3, address: str) -> LiqPriceResponse:
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
    orderby: str = "liq_price",
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
FROM loan.aave_v3_eth_positions p
LEFT JOIN eth_col e ON p.user_address = e.user_address
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
    "liq_price":              "liq_price",
    "eth_collateral_amount":  "eth_collateral_amount",
    "eth_collateral_usd":     "eth_collateral_usd",
    "total_debt_usd":         "total_debt_usd",
}


def _build_simulate_sql(order_col: str, order_dir: str) -> str:
    return f"""
WITH eth_col AS (
    SELECT
        user_address,
        (supply_raw::numeric / POWER(10::numeric, decimals)) AS eth_amount
    FROM loan.aave_v3_eth_reserve_positions
    WHERE symbol IN ('WETH', 'ETH', 'cbETH', 'wstETH', 'rETH')
      AND use_as_collateral = true
      AND supply_raw > 0
)
SELECT
    p.user_address                                                AS address,
    COALESCE(e.eth_amount, 0::numeric)                            AS eth_collateral_amount,
    COALESCE(e.eth_amount, 0::numeric) * $1::numeric              AS eth_collateral_usd,
    p.total_debt_usd,
    p.liq_price
FROM loan.aave_v3_eth_positions p
LEFT JOIN eth_col e ON p.user_address = e.user_address
WHERE p.liq_price > 0
  AND p.liq_price >= $1::numeric
ORDER BY {order_col} {order_dir}
"""


async def simulate_liquidation(
    pool,
    eth_price: Decimal,
    orderby: str = "liq_price",
    order: str = "desc",
    limit: int = 100,
) -> LiquidationSimResponse:
    """模拟当 ETH 价格为 eth_price 时，哪些仓位将被触发清算及汇总统计。

    清算奖励折价说明：
        Aave V3 WETH 清算奖励系数为 1.05（5%），即清算人偿还 1 USD 债务
        可从协议获得价值 1.05 USD 的 ETH 抵押品。
        因此 ``total_liquidation_usd`` = sum( min(debt × 1.05, eth_collateral_usd) )。
    """
    order_col = _SIM_SORT_COLS.get(orderby, "liq_price")
    order_dir = "DESC" if order.lower() == "desc" else "ASC"
    sql = _build_simulate_sql(order_col, order_dir)
    # 全量拉取所有触发清算仓位，以便统计数据覆盖全部；limit 仅限制 positions 列表
    rows = await pool.fetch(sql, float(eth_price))

    total_eth_amount = Decimal("0")
    total_eth_usd = Decimal("0")
    total_liq_usd = Decimal("0")
    all_items: list[LiquidationSimItem] = []

    for row in rows:
        eth_amt = Decimal(str(row["eth_collateral_amount"]))
        eth_usd = Decimal(str(row["eth_collateral_usd"]))
        debt_usd = Decimal(str(row["total_debt_usd"]))
        liq_p = Decimal(str(row["liq_price"]))

        # 清算人实际可获取的抵押品价值：不超过可用抵押品，含 5% 奖励加码
        seized = min(debt_usd * _WETH_LIQ_BONUS, eth_usd)

        total_eth_amount += eth_amt
        total_eth_usd += eth_usd
        total_liq_usd += seized

        all_items.append(LiquidationSimItem(
            address=row["address"],
            liq_price=_fmt(liq_p),
            eth_collateral_amount=_fmt(eth_amt, 6),
            eth_collateral_usd=_fmt(eth_usd),
            total_debt_usd=_fmt(debt_usd),
        ))

    total_count = len(all_items)
    items = all_items[:limit]

    note = (
        f"共 {total_count} 个仓位将在 ETH=${eth_price} 时触发清算"
        f"（本次返回前 {len(items)} 条）；"
        f"清算奖励系数 {_WETH_LIQ_BONUS}（WETH Aave V3 默认），"
        f"total_liquidation_usd = Σ min(债务 × {_WETH_LIQ_BONUS}, ETH抵押品USD)，"
        f"统计基于全部 {total_count} 个仓位"
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


async def get_price_period(
    w3: AsyncWeb3,
    asset: str,
    start_ts: int,
    end_ts: int,
    interval_hours: int,
) -> PricePeriodResponse:
    """查询资产在指定时间段内按固定间隔的历史价格序列（来自 DeFiLlama）。

    Args:
        w3:             AsyncWeb3 实例（用于解析 token_address）
        asset:          资产符号，如 ``eth``、``wbtc``；大小写不敏感
        start_ts:       起始 Unix 时间戳（秒）
        end_ts:         结束 Unix 时间戳（秒，含）
        interval_hours: 采样间隔（小时，>= 1）
    """
    import aiohttp
    from datetime import datetime, timezone
    from fastapi import HTTPException

    def _ts_to_utc_str(ts: int) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if end_ts < start_ts:
        raise HTTPException(status_code=400, detail="end 必须晚于或等于 start")
    if interval_hours < 1:
        raise HTTPException(status_code=400, detail="interval 必须 >= 1 小时")

    # 解析 token_address（复用 _get_common_data 缓存）
    await _get_common_data(w3)
    target = asset.upper()
    if target == "ETH":
        target = "WETH"
    reserve_tokens = _cache["reserve_tokens"]
    matching = [rt for rt in reserve_tokens if rt.symbol.upper() == target]
    if not matching:
        raise HTTPException(status_code=404, detail=f"未找到资产 '{asset}'，请确认符号正确")
    token_address = matching[0].token_address
    coin_key = f"ethereum:{token_address.lower()}"

    # 生成时间戳序列
    step = interval_hours * 3600
    timestamps: list[int] = []
    ts = start_ts
    while ts <= end_ts:
        timestamps.append(ts)
        ts += step
    if not timestamps:
        raise HTTPException(status_code=400, detail="时间范围内未能生成任何采样点，请检查 start/end/interval 参数")

    # 并发查询 DeFiLlama
    async def _fetch_one(
        session: aiohttp.ClientSession, point_ts: int
    ) -> PricePeriodItem:
        url = f"https://coins.llama.fi/prices/historical/{point_ts}/{coin_key}"
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return PricePeriodItem(
                        price_usd="0.00",
                        timestamp=_ts_to_utc_str(point_ts),
                    )
                data = await resp.json()
        except aiohttp.ClientError:
            return PricePeriodItem(
                price_usd="0.00",
                timestamp=_ts_to_utc_str(point_ts),
            )
        entry = data.get("coins", {}).get(coin_key, {})
        price = Decimal(str(entry["price"])) if "price" in entry else Decimal("0")
        actual_ts = int(entry.get("timestamp", point_ts))
        return PricePeriodItem(
            price_usd=_fmt(price, 2),
            timestamp=_ts_to_utc_str(actual_ts),
        )

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as sess:
        items: list[PricePeriodItem] = list(
            await asyncio.gather(*[_fetch_one(sess, t) for t in timestamps])
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
    "USDC", "USDT", "DAI", "GHO", "LUSD", "FRAX",
    "USDE", "CRVUSD", "PYUSD", "SUSD", "TUSD", "BUSD",
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
    token_map: dict[str, str],   # symbol → "ethereum:0x..." (or "coingecko:...")
    timestamp: int,
) -> dict[str, Decimal]:
    """批量从 DeFiLlama 获取多个资产在同一时间点的历史价格。
    返回 symbol → Decimal(price_usd)。
    稳定币直接返回 1，其余并发查询。
    """
    import aiohttp
    from datetime import datetime, timezone

    result: dict[str, Decimal] = {}
    to_fetch: list[tuple[str, str]] = []   # [(symbol, coin_key), ...]

    for sym, coin_key in token_map.items():
        if sym.upper() in _STABLECOINS:
            result[sym] = Decimal("1")
        else:
            to_fetch.append((sym, coin_key))

    if not to_fetch:
        return result

    async def _fetch_one(session: aiohttp.ClientSession, sym: str, coin_key: str) -> tuple[str, Decimal]:
        url = f"https://coins.llama.fi/prices/historical/{timestamp}/{coin_key}"
        try:
            async with session.get(url) as resp:
                data = await resp.json()
                entry = data.get("coins", {}).get(coin_key, {})
                price = Decimal(str(entry["price"])) if "price" in entry else Decimal("0")
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
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    at_dt = datetime.fromtimestamp(at_time_ts, tz=timezone.utc)

    rows = await pool.fetch(_SQL_USER_HISTORY, address.lower(), at_dt)

    if not rows:
        # 无操作记录 → 返回 None，由调用方决定如何回退
        return None

    # 过滤掉供给和债务都为 0 的行
    rows = [r for r in rows if Decimal(str(r["supply_amount"])) > Decimal("1e-6")
            or Decimal(str(r["debt_amount"])) > Decimal("1e-6")]
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
    token_map: dict[str, str] = {}   # symbol → defillama coin_key
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
        debt   = Decimal(str(row["debt_amount"]))
        price  = prices.get(sym, Decimal("1"))  # 未知价格 fallback 为 1

        if sym in eth_syms and supply > 0:
            eth_collateral += supply

        if debt > 0:
            total_debt_usd += debt * price

        if supply > Decimal("1e-6") or debt > Decimal("1e-6"):
            reserves.append(HistoricalReserveDetail(
                symbol=row["token_symbol"],
                token_address=row["token_addr"],
                supply_amount=_fmt(supply, 6),
                debt_amount=_fmt(debt, 6),
            ))

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
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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
    addr_debts: dict[str, list[tuple[str, str, Decimal]]] = defaultdict(list)  # addr → [(sym, ta, debt)]

    seen = set()
    for row in rows:
        addr = row["address"]
        if addr not in addr_eth:
            addr_eth[addr] = Decimal(str(row["eth_amount"]))
        sym = row["token_symbol"]
        ta  = row["token_addr"]
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
            reserves.append(HistoricalReserveDetail(
                symbol=sym,
                token_address=ta,
                supply_amount="0",
                debt_amount=_fmt(debt, 6),
            ))

        liq_price = (
            total_debt_usd / (eth_amt * _DEFAULT_LIQ_THRESHOLD)
            if total_debt_usd > 0 and eth_amt > 0
            else Decimal("0")
        )
        result.append(HistoricalPositionResponse(
            address=addr,
            at_time=_ts_to_utc(at_time_ts),
            eth_collateral_amount=_fmt(eth_amt, 6),
            eth_price_usd=_fmt(eth_price, 2),
            eth_collateral_usd=_fmt(eth_amt * eth_price, 2),
            total_debt_approx_usd=_fmt(total_debt_usd, 2),
            liq_price=_fmt(liq_price, 2) if liq_price > 0 else "0",
            reserves=reserves,
            note="近似值：直接累加操作金额，未计利息；liq_price 使用 WETH liq_threshold=0.825",
        ))

    return result
