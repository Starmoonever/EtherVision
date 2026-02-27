"""FastAPI 路由"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from .schemas import (
    HistoricalPositionResponse,
    LiqPriceResponse,
    LiquidationPeriodItem,
    LiquidationSimResponse,
    PositionResponse,
    PriceResponse,
    PricePeriodResponse,
)
from .service import (
    get_eth_price,
    get_liq_price,
    get_price_period,
    get_sorted_positions,
    get_user_position,
    get_user_position_history,
    get_positions_history,
    simulate_liquidation,
    simulate_liquidation_period,
)

router = APIRouter(prefix="/api")


def _w3(request: Request):
    w3 = request.app.state.w3
    if w3 is None:
        raise HTTPException(status_code=503, detail="RPC 节点尚未就绪，请稍后重试")
    return w3


def _pool(request: Request):
    pool = request.app.state.pool
    if pool is None:
        raise HTTPException(status_code=503, detail="数据库连接尚未就绪，请稍后重试")
    return pool


def _parse_utc_time(time_str: str) -> int:
    """UTC 时间字符串 → Unix 秒级时间戳，失败抛 HTTPException。"""
    from datetime import datetime, timezone
    _FMTS = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in _FMTS:
        try:
            return int(datetime.strptime(time_str, fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    raise HTTPException(
        status_code=400,
        detail="date/time 格式无法识别，支持示例：2024-11-14T12:00:00Z、2024-11-14 12:00:00、2024-11-14",
    )


@router.get(
    "/user/position",
    response_model=PositionResponse | HistoricalPositionResponse,
    summary="查询用户 Aave 仓位",
    description=(
        "查询指定地址的 Aave V3 仓位。\n\n"
        "- 省略 `date`：实时从以太主网链上查询，返回 `PositionResponse`\n"
        "- 指定 `date`：从 aave.aave_history 重建历史时间点仓位（含利息估算，价格来自 DeFiLlama），返回 `HistoricalPositionResponse`\n\n"
        "支持格式：`2024-11-14T12:00:00Z` / `2024-11-14 12:00:00` / `2024-11-14`"
    ),
)
async def user_position(
    request: Request,
    address: str = Query(..., description="以太坊錢包地址（支持校验和或小写）"),
    date: str | None = Query(
        None,
        description="历史时间点（UTC），如 2024-01-01；省略则查询实时链上数据",
    ),
) -> PositionResponse | HistoricalPositionResponse:
    if date is None:
        return await get_user_position(_w3(request), address)
    ts = _parse_utc_time(date)
    result = await get_user_position_history(_pool(request), address, ts)
    if result is None:
        # 历史 DB 中无该地址的操作记录，仓位未发生变化，回退到实时链上数据
        return await get_user_position(_w3(request), address)
    return result


@router.get(
    "/user/liq_price",
    response_model=LiqPriceResponse,
    summary="查询 ETH liq_price",
    description="计算当 ETH 价格跌至多少时，该用户的 Aave 健康系数将触碰 1.0",
)
async def user_liq_price(
    request: Request,
    address: str = Query(..., description="以太坊钱包地址"),
) -> LiqPriceResponse:
    return await get_liq_price(_w3(request), address)


@router.get(
    "/positions",
    response_model=list[PositionResponse] | list[HistoricalPositionResponse],
    summary="批量查询仓位排行",
    description=(
        "查询 Aave V3 仓位排行。\n\n"
        "- 省略 `date`：从数据库读取已爬取的实时快照，支持 `orderby` / `order` 排序，最多 200 条，返回 `list[PositionResponse]`\n"
        "- 指定 `date`：从 aave.aave_history 计算历史时间点 top-N 用户（按 ETH 抵押量降序，近似值，最多 100 条），返回 `list[HistoricalPositionResponse]`\n\n"
        "支持格式：`2024-11-14T12:00:00Z` / `2024-11-14 12:00:00` / `2024-11-14`"
    ),
)
async def positions(
    request: Request,
    orderby: Literal["liq_price", "health_factor"] = Query(
        "liq_price",
        description="排序字段（仅实时模式有效）：liq_price 或 health_factor",
    ),
    order: Literal["asc", "desc"] = Query(
        "asc",
        description="排序方向（仅实时模式有效）：asc=升序，desc=降序",
    ),
    limit: int = Query(10, ge=1, le=200, description="返回记录数（实时模式最多 200，历史模式最多 100）"),
    date: str | None = Query(
        None,
        description="历史时间点（UTC），如 2024-01-01；省略则查询数据库实时快照",
    ),
) -> list[PositionResponse] | list[HistoricalPositionResponse]:
    if date is None:
        return await get_sorted_positions(
            _pool(request), orderby=orderby, order=order, limit=limit
        )
    ts = _parse_utc_time(date)
    return await get_positions_history(_pool(request), ts, limit=min(limit, 100))


@router.get(
    "/price",
    response_model=PriceResponse,
    summary="查询资产价格（当前或历史）",
    description=(
        "查询资产 USD 价格。\n\n"
        "- `time=now`（默认）：从链上 Aave Oracle 实时查询当前价格\n"
        "- `time=<UTC 时间字符串>`：从 DeFiLlama 查询历史价格\n\n"
        "支持格式：`2024-11-14T12:00:00Z` / `2024-11-14 12:00:00` / `2024-11-14`"
    ),
)
async def asset_price(
    request: Request,
    asset: str = Query("eth", description="资产名称，如 eth、wbtc、usdc"),
    time: str = Query(
        "now",
        description="now = 实时价格；UTC 时间字符串 = 历史价格，如 2024-11-14T12:00:00Z",
    ),
) -> PriceResponse:
    if time == "now":
        return await get_eth_price(_w3(request), asset)
    ts = _parse_utc_time(time)
    return await get_eth_price(_w3(request), asset, timestamp=ts)


@router.get(
    "/liquidate",
    response_model=LiquidationSimResponse,
    summary="模拟 ETH 价格下跌时的清算情况",
    description=(
        "模拟当 ETH 价格跌至指定值时，有哪些账户会被清算，"
        "以及清算人可获取的抵押品总价值（含 5% 清算奖励折价）。\n\n"
        "数据来源：数据库实时快照（需先运行 `aave-crawler crawl`）。\n\n"
        "**清算折价说明**：Aave V3 WETH 清算奖励系数为 1.05，"
        "即清算人偿还 1 USD 债务可获得 1.05 USD 的 ETH 抵押品。\n"
        "`total_liquidation_usd = Σ min(债务 × 1.05, ETH抵押品USD)`"
    ),
)
async def liquidate_simulation(
    request: Request,
    eth_price: float = Query(
        ...,
        gt=0,
        description="模拟的 ETH 价格（USD），必须大于 0",
    ),
    limit: int = Query(
        100,
        ge=1,
        le=1000,
        description="返回的仓位数量，默认 100，最多 1000",
    ),
    orderby: Literal[
        "liq_price",
        "eth_collateral_amount",
        "eth_collateral_usd",
        "total_debt_usd",
    ] = Query(
        "liq_price",
        description="排序字段：liq_price / eth_collateral_amount / eth_collateral_usd / total_debt_usd",
    ),
    order: Literal["desc", "asc"] = Query(
        "desc",
        description="排序方向：desc=降序（默认），asc=升序",
    ),
) -> LiquidationSimResponse:
    from decimal import Decimal
    return await simulate_liquidation(
        _pool(request),
        Decimal(str(eth_price)),
        orderby=orderby,
        order=order,
        limit=limit,
    )


@router.get(
    "/price/period",
    response_model=PricePeriodResponse,
    summary="查询资产历史价格序列",
    description=(
        "从 DeFiLlama 查询指定资产在 start～end 时间段内，按 interval 分钟间隔的历史 USD 价格序列。\n\n"
        "支持时间格式：`2024-11-14T12:00:00Z` / `2024-11-14 12:00:00` / `2024-11-14`"
    ),
)
async def asset_price_period(
    request: Request,
    asset: str = Query("eth", description="资产名称，如 eth、wbtc、usdc"),
    start: str = Query(..., description="起始 UTC 时间，如 2024-01-01"),
    end: str = Query(..., description="结束 UTC 时间，如 2024-12-31"),
    interval: int = Query(60, ge=1, description="采样间隔（分钟），最小 1"),
) -> PricePeriodResponse:
    start_ts = _parse_utc_time(start)
    end_ts = _parse_utc_time(end)
    return await get_price_period(_w3(request), asset, start_ts=start_ts, end_ts=end_ts, interval_minutes=interval)


@router.get(
    "/liquidate/period",
    response_model=list[LiquidationPeriodItem],
    summary="模拟 ETH 价格在区间内波动时的清算变化",
    description=(
        "分析 ETH 价格在 start～end 区间内，每隔 interval 步长时触发清算的汇总统计。\n\n"
        "返回按价格升序排列的清算快照序列，可观察不同价格点的清算量和可清算抵押品变化趋势。\n\n"
        "**注意**：start 必须 <= end，interval 必须大于 0。"
    ),
)
async def liquidate_period(
    request: Request,
    start: float = Query(..., gt=0, description="起始 ETH 价格（USD），必须大于 0"),
    end: float = Query(..., gt=0, description="结束 ETH 价格（USD），必须 >= start"),
    interval: float = Query(..., gt=0, description="价格步长（USD），必须大于 0"),
) -> list[LiquidationPeriodItem]:
    from decimal import Decimal
    return await simulate_liquidation_period(
        _pool(request),
        start_price=Decimal(str(start)),
        end_price=Decimal(str(end)),
        interval=Decimal(str(interval)),
    )
