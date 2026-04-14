"""FastAPI routes for Morpho."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..database import AsyncpgPool
from .schemas import MorphoPositionResponse
from .service import get_user_position

router = APIRouter(prefix="/api/morpho")


def _w3(request: Request):
    w3 = getattr(request.app.state, "w3", None)
    if w3 is None:
        raise HTTPException(status_code=503, detail="RPC 节点尚未就绪，请稍后重试")
    return w3


@router.get(
    "/position",
    response_model=MorphoPositionResponse,
    summary="Query current Morpho Blue position from RPC",
)
async def position(
    request: Request,
    pool: AsyncpgPool,
    address: str = Query(..., description="EVM user address"),
    market_id: str = Query(..., description="Morpho market id (bytes32 hex)"),
    protocol: str = Query(
        "blue", description='Morpho protocol selector; currently only "blue"'
    ),
) -> MorphoPositionResponse:
    return await get_user_position(
        _w3(request),
        pool=pool,
        address=address,
        market_id=market_id,
        protocol=protocol,
    )
