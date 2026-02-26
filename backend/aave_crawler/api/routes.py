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
    summary="查询资产当前价格",
    description="从链上 Aave Oracle 实时获取资产的 USD 价格",
)
async def asset_price(
    request: Request,
    asset: str = Query("eth", description="资产名称，如 eth、wbtc、usdc"),
    time: str = Query("now", description="时间参数，目前仅支持 now"),
) -> PriceResponse:
    if time != "now":
        raise HTTPException(status_code=400, detail="time 参数目前仅支持 'now'")
    return await get_eth_price(_w3(request), asset)
