"""FastAPI routes for Morpho."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..database import AsyncpgPool
from .schemas import (
    MorphoExposureSumResponse,
    MorphoPositionReplayResponse,
    MorphoPositionResponse,
)
from .service import get_exposure_sum, get_position_replay, get_user_position

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


@router.get(
    "/position/replay",
    response_model=MorphoPositionReplayResponse,
    summary="Replay Morpho Blue user position by cached snapshots",
)
async def position_replay(
    request: Request,
    pool: AsyncpgPool,
    address: str = Query(..., description="EVM user address"),
    market_id: str = Query(..., description="Morpho market id (bytes32 hex)"),
    start: str = Query(..., description="起始时间（UTC）"),
    end: str = Query(..., description="结束时间（UTC）"),
    protocol: str = Query(
        "blue", description='Morpho protocol selector; currently only "blue"'
    ),
    use_cache: bool = Query(True, description="是否优先使用缓存"),
    detail: bool = Query(False, description="是否返回资产明细"),
) -> MorphoPositionReplayResponse:
    from .service import parse_utc_time

    from_ts = parse_utc_time(start)
    to_ts = parse_utc_time(end)
    if from_ts > to_ts:
        raise HTTPException(status_code=400, detail="start 必须早于或等于 end")

    return await get_position_replay(
        _w3(request),
        pool=pool,
        address=address,
        market_id=market_id,
        protocol=protocol,
        from_ts=from_ts,
        to_ts=to_ts,
        use_cache=use_cache,
        detail=detail,
    )


# morpho exposure sum相关
@router.get(
    "/exposure/sum",
    response_model=MorphoExposureSumResponse,
    summary="Get Morpho exposure sum by position type and asset",
)
async def exposure_sum(
    pool: AsyncpgPool,
    position_type: str = Query(..., description="borrow / collateral / supply"),
    asset: str = Query(..., description="资产符号，如 USDC、WETH"),
) -> MorphoExposureSumResponse:
    return await get_exposure_sum(
        pool=pool,
        position_type=position_type,
        asset=asset,
    )
