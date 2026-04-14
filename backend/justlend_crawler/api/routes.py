"""FastAPI routes for the JustLend scaffold."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from ..database import AsyncpgPool
from ..config import load_config
from .schemas import (
    JustLendMarketResponse,
    JustLendPositionResponse,
    JustLendPositionReplayResponse,
    JustLendScaffoldStatusResponse,
)
from .service import (
    get_markets,
    get_position_replay,
    get_scaffold_status,
    get_user_position,
)

router = APIRouter(prefix="/api/justlend")


def _parse_utc_time(time_str: str) -> int:
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return int(
                datetime.strptime(time_str, fmt)
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
        except ValueError:
            continue
    raise HTTPException(
        status_code=400,
        detail="date/time 格式无法识别，示例：2024-11-14T12:00:00Z、2024-11-14 12:00:00、2024-11-14",
    )


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


@router.get(
    "/position/replay",
    response_model=JustLendPositionReplayResponse,
    summary="Replay JustLend user position by cached snapshots",
)
async def position_replay(
    pool: AsyncpgPool,
    request: Request,
    address: str = Query(..., description="TRON user address"),
    start: str = Query(..., description="起始时间（UTC）"),
    end: str = Query(..., description="结束时间（UTC）"),
    protocol: str = Query("trx", description="JustLend protocol selector"),
    use_cache: bool = Query(True, description="是否优先使用缓存"),
    detail: bool = Query(False, description="是否返回资产明细"),
) -> JustLendPositionReplayResponse:
    from_ts = _parse_utc_time(start)
    to_ts = _parse_utc_time(end)
    if from_ts > to_ts:
        raise HTTPException(status_code=400, detail="start 必须早于或等于 end")
    cfg = getattr(request.app.state, "justlend_cfg", None) or load_config()
    return await get_position_replay(
        pool=pool,
        cfg=cfg,
        tron_rpc=getattr(request.app.state, "tron_rpc", None),
        address=address,
        protocol=protocol,
        from_ts=from_ts,
        to_ts=to_ts,
        use_cache=use_cache,
        detail=detail,
    )
