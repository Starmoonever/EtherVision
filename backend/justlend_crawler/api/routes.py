"""FastAPI routes for the JustLend scaffold."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from ..database import AsyncpgPool
from ..config import load_config
from .schemas import (
    JustLendMarketResponse,
    JustLendMarketStatePeriodResponse,
    JustLendMarketStateResponse,
    JustLendPositionResponse,
    JustLendPositionsResponse,
    JustLendPositionReplayResponse,
    JustLendScaffoldStatusResponse,
)
from .service import (
    get_market_state,
    get_market_state_period,
    get_markets,
    get_positions,
    get_position_replay,
    get_scaffold_status,
    get_supported_tx_operation_types,
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
    summary="List JustLend markets",
)
async def markets(pool: AsyncpgPool) -> JustLendMarketResponse:
    return await get_markets(pool)


@router.get(
    "/market/state",
    response_model=JustLendMarketStateResponse,
    summary="Query latest JustLend market state",
)
async def market_state(
    pool: AsyncpgPool,
    market: str = Query(..., description="JustLend 市场地址"),
    date: str | None = Query(None, description="可选 UTC 时间；不传则返回最新状态"),
) -> JustLendMarketStateResponse:
    as_of = (
        None
        if date is None
        else datetime.fromtimestamp(_parse_utc_time(date), tz=timezone.utc)
    )
    return await get_market_state(pool, market=market, date=as_of)


@router.get(
    "/market/state/period",
    response_model=JustLendMarketStatePeriodResponse,
    summary="Query JustLend market state changes over a period",
)
async def market_state_period(
    pool: AsyncpgPool,
    market: str = Query(..., description="JustLend 市场地址"),
    start: str = Query(..., description="起始时间（UTC）"),
    end: str = Query(..., description="结束时间（UTC）"),
) -> JustLendMarketStatePeriodResponse:
    from_ts = _parse_utc_time(start)
    to_ts = _parse_utc_time(end)
    if from_ts > to_ts:
        raise HTTPException(status_code=400, detail="start 必须早于或等于 end")
    return await get_market_state_period(
        pool,
        market=market,
        from_ts=datetime.fromtimestamp(from_ts, tz=timezone.utc),
        to_ts=datetime.fromtimestamp(to_ts, tz=timezone.utc),
    )


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
    "/positions",
    response_model=JustLendPositionsResponse,
    summary="Query current JustLend positions overview",
)
async def positions(
    pool: AsyncpgPool,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=200, description="分页大小，最大 200"),
    sort_by: Literal[
        "health_factor",
        "total_supply_usd",
        "total_collateral_usd",
        "total_borrow_usd",
        "asset_value_usd",
    ] = Query("health_factor", description="排序字段"),
    order: Literal["asc", "desc"] = Query("desc", description="排序方向"),
    side: Literal["all", "collateral", "supply", "borrow"] = Query(
        "all",
        description="资产侧别；按资产排序时必须指定具体 side",
    ),
    asset: str | None = Query(
        None,
        description="TRON 资产地址；sort_by=asset_value_usd 时必填",
    ),
    detail: bool = Query(False, description="是否返回当前页仓位的资产明细"),
    address: str | None = Query(None, description="TRON 用户地址；按单地址过滤"),
) -> JustLendPositionsResponse:
    return await get_positions(
        pool,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        order=order,
        side=side,
        asset=asset,
        detail=detail,
        address=address,
    )


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


@router.get(
    "/tx/ops",
    response_model=list[str],
    summary="List JustLend transaction operation types",
)
async def tx_operation_types() -> list[str]:
    return get_supported_tx_operation_types()
