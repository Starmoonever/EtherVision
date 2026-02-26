"""FastAPI 路由"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from .schemas import LiquidationLineResponse, PositionResponse, PriceResponse
from .service import (
    get_eth_price,
    get_liquidation_line,
    get_sorted_positions,
    get_user_position,
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


@router.get(
    "/user/position",
    response_model=PositionResponse,
    summary="查询用户 Aave 仓位",
    description="实时从以太主网链上查询指定地址的 Aave V3 仓位数据",
)
async def user_position(
    request: Request,
    address: str = Query(..., description="以太坊钱包地址（支持校验和或小写）"),
) -> PositionResponse:
    return await get_user_position(_w3(request), address)


@router.get(
    "/user/liquidation_line",
    response_model=LiquidationLineResponse,
    summary="查询 ETH liq_price",
    description="计算当 ETH 价格跌至多少时，该用户的 Aave 健康系数将触碰 1.0",
)
async def user_liquidation_line(
    request: Request,
    address: str = Query(..., description="以太坊钱包地址"),
) -> LiquidationLineResponse:
    return await get_liquidation_line(_w3(request), address)


@router.get(
    "/positions",
    response_model=list[PositionResponse],
    summary="批量查询仓位排行",
    description="从数据库中读取已爬取的仓位数据，按 liq_price 或健康系数排序",
)
async def positions(
    request: Request,
    orderby: Literal["liquidation_price", "health_factor"] = Query(
        "liquidation_price",
        description="排序字段：liquidation_price（清算价，越低越危险）或 health_factor",
    ),
    order: Literal["asc", "desc"] = Query(
        "asc",
        description="排序方向：asc=最危险的在前，desc=最安全的在前",
    ),
    limit: int = Query(10, ge=1, le=200, description="返回记录数，最多 200"),
) -> list[PositionResponse]:
    return await get_sorted_positions(
        _pool(request), orderby=orderby, order=order, limit=limit
    )


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

    # 解析 UTC 时间字符串 → Unix 秒级时间戳
    from datetime import datetime, timezone

    _FMTS = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    ts: int | None = None
    for fmt in _FMTS:
        try:
            dt = datetime.strptime(time, fmt).replace(tzinfo=timezone.utc)
            ts = int(dt.timestamp())
            break
        except ValueError:
            continue

    if ts is None:
        raise HTTPException(
            status_code=400,
            detail="time 格式无法识别，支持示例：2024-11-14T12:00:00Z、2024-11-14 12:00:00、2024-11-14",
        )
    return await get_eth_price(_w3(request), asset, timestamp=ts)
