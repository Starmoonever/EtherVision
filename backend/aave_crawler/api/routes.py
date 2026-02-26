"""FastAPI 路由"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from .schemas import LiquidationLineResponse, PositionResponse
from .service import get_liquidation_line, get_user_position

router = APIRouter(prefix="/api/user")


def _w3(request: Request):
    w3 = request.app.state.w3
    if w3 is None:
        raise HTTPException(status_code=503, detail="RPC 节点尚未就绪，请稍后重试")
    return w3


@router.get(
    "/position",
    response_model=PositionResponse,
    summary="查询用户 Aave 仓位",
    description="实时从以太主网链上查询指定地址的 Aave V3 仓位数据（抵押品、借贷明细及 USD 估值）",
)
async def user_position(
    request: Request,
    address: str = Query(..., description="以太坊钱包地址（支持校验和或小写）"),
) -> PositionResponse:
    return await get_user_position(_w3(request), address)


@router.get(
    "/liquidation_line",
    response_model=LiquidationLineResponse,
    summary="查询 ETH 清算价格",
    description=(
        "计算当 ETH 价格跌至多少时，该用户的 Aave 健康系数将触碰 1.0（触发清算风险）。"
        "仅适用于以 ETH/WETH 为主要抵押品的用户。"
    ),
)
async def user_liquidation_line(
    request: Request,
    address: str = Query(..., description="以太坊钱包地址"),
) -> LiquidationLineResponse:
    return await get_liquidation_line(_w3(request), address)
