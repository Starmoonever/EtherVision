"""FastAPI routes for Compound scaffold."""

from __future__ import annotations
from typing import Literal
from fastapi import APIRouter, Query
from .schemas import (
    MarketStatePeriodResponse,
    MarketStateResponse,
    UserPositionResponse,
)
from .service import get_market_state, get_market_state_period, get_positions
from ..database import AsyncpgPool


router = APIRouter(prefix="/api/compound")


@router.get(
    "/position",
    response_model=UserPositionResponse,
    summary="Query a single Compound user position",
    response_description=(
        "返回单一地址在指定市场或全部市场下的仓位列表；每个元素都包含市场标识、时间戳、清算缓冲、健康因子、ETH 敏感敞口以及逐资产明细。"
    ),
    description=(
        "查询 Compound v3 中单一用户地址的仓位快照。\n\n"
        "- `address` 为必选，只返回该地址的仓位\n"
        "- `market` 可传单个市场地址/名称，或传 `all` 返回所有已支持市场\n"
        "- `date` 推荐直接传 `YYYY-MM-DD`\n"
        "- 如果 `date` 同时包含具体时间，服务会忽略时分秒，只取该 UTC 日期并归一到 `00:00:00Z`\n"
        "- 若 `date` 为空，则直接从链上抓取实时数据，不写库\n"
        "- 若 `date` 不为空，则优先查库；若库中不存在，则链上查询后写入快照表再返回\n"
        "- 返回结果中的 `positions` 为该地址在命中市场下的仓位列表"
    ),
)
async def position(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query(
        "v3",
        description='protocol version: "v2" | "v3" (currently only v3 is supported)',
    ),
    market: str = Query(
        ...,
        description='市场地址或名称，也支持 `all`：`"0x..." | "USDC" | "USDT" | "WETH" | "all"`',
    ),
    address: str = Query(
        ...,
        description="必选用户地址；该端点只返回这个地址的仓位。",
    ),
    date: str | None = Query(
        None,
        description=(
            "可选 UTC 日期，推荐格式 `YYYY-MM-DD`。若同时带有时分秒，将被忽略并自动归一到该日期的 `00:00:00Z`；"
            "不传则返回链上实时数据。"
        ),
    ),
) -> UserPositionResponse:
    return await get_positions(
        pool=pool,
        version=version,
        market=market,
        address=address,
        date=date,
    )


@router.get(
    "/market/state/period",
    response_model=MarketStatePeriodResponse,
    summary="Query Compound market state over a period",
)
async def market_state_period(
    pool: AsyncpgPool,
    version: str = Query(
        "v3",
        description='protocol version: "v2" | "v3" (currently only v3 is supported)',
    ),
    market: str = Query(
        ...,
        description='market name: "USDC" | "USDT" | "WETH" (case-insensitive)',
    ),
    start: str = Query(..., description="UTC datetime at hour precision (start)"),
    end: str = Query(..., description="UTC datetime at hour precision (end)"),
    interval: int = Query(
        24,
        description="Sampling interval in hours (default 24, allowed 1-168)",
    ),
    detail: bool = Query(False, description="Whether to expand reserve details"),
) -> "MarketStatePeriodResponse":
    return await get_market_state_period(
        pool=pool,
        version=version,
        market=market,
        start=start,
        end=end,
        interval=interval,
        detail=detail,
    )


@router.get(
    "/market/state",
    response_model=MarketStateResponse,
    summary="Query Compound market state",
)
async def market_state(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query(
        "v3",
        description='protocol version: "v2" | "v3" (currently only v3 is supported)',
    ),
    market: str = Query(
        ...,
        description='market name: "USDC" | "USDT" | "WETH" (case-insensitive)',
    ),
    date: str = Query(..., description="UTC datetime at hour precision"),
    detail: bool = Query(False, description="Whether to expand reserve details"),
) -> MarketStateResponse:
    return await get_market_state(
        pool=pool,
        version=version,
        market=market,
        date=date,
        detail=detail,
    )
