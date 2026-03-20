"""FastAPI routes for Compound scaffold."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from .constants import DEFAULT_LIMIT, MAX_LIMIT
from .schemas import MarketStateResponse, PositionResponse
from .service import get_market_state, get_sorted_positions
from ..database import AsyncpgPool

router = APIRouter(prefix="/api/compound")


@router.get(
    "/positions",
    response_model=list[PositionResponse],
    summary="Query Compound positions (scaffold)",
)
async def positions(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Result size"),
) -> list[PositionResponse]:
    return await get_sorted_positions(limit)


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
