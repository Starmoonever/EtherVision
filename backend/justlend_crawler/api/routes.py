"""FastAPI routes for the JustLend scaffold."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..database import AsyncpgPool
from ..config import load_config
from .schemas import (
    JustLendMarketResponse,
    JustLendPositionResponse,
    JustLendScaffoldStatusResponse,
)
from .service import get_markets, get_scaffold_status, get_user_position

router = APIRouter(prefix="/api/justlend")


@router.get(
    "/status",
    response_model=JustLendScaffoldStatusResponse,
    summary="Inspect JustLend scaffold status",
)
async def status() -> JustLendScaffoldStatusResponse:
    return get_scaffold_status()


@router.get(
    "/markets",
    response_model=JustLendMarketResponse,
    summary="List JustLend markets reserved by the scaffold",
)
async def markets() -> JustLendMarketResponse:
    return get_markets()


@router.get(
    "/position",
    response_model=JustLendPositionResponse,
    summary="Query current JustLend user position",
)
async def position(
    pool: AsyncpgPool,
    request: Request,
    address: str = Query(..., description="TRON user address"),
    protocol: str = Query("trx", description="JustLend protocol selector"),
) -> JustLendPositionResponse:
    cfg = getattr(request.app.state, "justlend_cfg", None) or load_config()
    return await get_user_position(pool, cfg, address, protocol)
