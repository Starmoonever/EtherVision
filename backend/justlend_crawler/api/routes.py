"""FastAPI routes for the JustLend scaffold."""

from __future__ import annotations

from fastapi import APIRouter, Query

from .schemas import JustLendMarketResponse, JustLendScaffoldStatusResponse
from .service import get_markets, get_scaffold_status, raise_not_implemented

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
    summary="Reserved JustLend user-position endpoint",
)
async def position(
    address: str = Query(..., description="TRON user address"),
    protocol: str = Query("trx", description="JustLend protocol selector"),
):
    _ = (address, protocol)
    raise_not_implemented("position")
