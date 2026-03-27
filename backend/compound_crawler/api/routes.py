"""FastAPI routes for Compound scaffold."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from ..database import AsyncpgPool
from .schemas import (
    CompoundLiquidationSimResponse,
    CompoundMarketConfigPeriodResponse,
    CompoundMarketConfigResponse,
    CompoundPositionReplayResponse,
    MarketsResponse,
    MarketStatePeriodResponse,
    MarketStateResponse,
    UserPositionResponse,
)
from .service import (
    get_market_governance,
    get_market_governance_period,
    get_market_state,
    get_market_state_period,
    get_markets,
    get_position_replay,
    get_positions,
    simulate_liquidation,
    get_v2_market_config,
    get_v2_market_config_period,
    get_v2_protocol_config,
)

router = APIRouter(prefix="/api/compound")
_VERSION_DESC_BOTH = 'protocol version: "v2" | "v3" (both supported)'


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
    "/markets",
    response_model=MarketsResponse,
    summary="List supported Compound markets",
)
async def markets(
    version: Literal["v2", "v3"] = Query("v3", description=_VERSION_DESC_BOTH),
) -> MarketsResponse:
    return get_markets(version)


@router.get(
    "/position",
    response_model=UserPositionResponse,
    summary="Query a single Compound user position",
)
async def position(
    request: Request,
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query("v3", description=_VERSION_DESC_BOTH),
    market: str = Query(..., description="市场地址或名称，也支持 `all`"),
    address: str = Query(..., description="用户地址"),
    date: str | None = Query(None, description="UTC 日期；空表示实时/最新"),
) -> UserPositionResponse:
    return await get_positions(
        pool=pool,
        version=version,
        market=market,
        address=address,
        date=date,
        w3=getattr(request.app.state, "w3", None),
    )


@router.get(
    "/position/replay",
    response_model=CompoundPositionReplayResponse,
    summary="Replay Compound user position by tx history",
)
async def position_replay(
    request: Request,
    pool: AsyncpgPool,
    address: str = Query(..., description="用户地址（0x...）"),
    start: str = Query(..., description="起始时间（UTC）"),
    end: str = Query(..., description="结束时间（UTC）"),
    version: Literal["v2", "v3"] = Query("v3", description=_VERSION_DESC_BOTH),
    use_cache: bool = Query(True, description="是否优先使用缓存"),
    detail: bool = Query(False, description="是否返回资产明细"),
) -> CompoundPositionReplayResponse:
    from_ts = _parse_utc_time(start)
    to_ts = _parse_utc_time(end)
    if from_ts > to_ts:
        raise HTTPException(status_code=400, detail="start 必须早于或等于 end")
    return await get_position_replay(
        pool=pool,
        version=version,
        address=address,
        from_ts=from_ts,
        to_ts=to_ts,
        use_cache=use_cache,
        detail=detail,
        w3=getattr(request.app.state, "w3", None),
    )


@router.get(
    "/liquidate",
    response_model=CompoundLiquidationSimResponse,
    summary="Simulate Compound v3 ETH downside liquidation risk",
)
async def liquidate_simulation(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query("v3", description=_VERSION_DESC_BOTH),
    eth_price: float = Query(..., gt=0, description="模拟的 ETH 价格（USD）"),
    market: str = Query("all", description="市场地址或名称，也支持 `all`"),
    limit: int = Query(100, ge=1, le=1000, description="返回的仓位数量"),
    offset: int = Query(0, ge=0, description="分页偏移量"),
    orderby: Literal[
        "liq_price",
        "eth_sensitive_collateral_usd",
        "total_collateral_usd",
        "total_debt_usd",
    ] = Query("liq_price", description="排序字段"),
    order: Literal["asc", "desc"] = Query("desc", description="排序方向"),
) -> CompoundLiquidationSimResponse:
    return await simulate_liquidation(
        pool,
        version=version,
        eth_price=Decimal(str(eth_price)),
        market=market,
        limit=limit,
        offset=offset,
        orderby=orderby,
        order=order,
    )


@router.get(
    "/market/config",
    response_model=CompoundMarketConfigResponse,
    summary="Query Compound market config (v2/v3 unified)",
)
async def market_config(
    request: Request,
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query("v3", description=_VERSION_DESC_BOTH),
    market: str = Query(..., description='市场地址或名称：`"0x..." | "<SYMBOL>"`'),
    date: str | None = Query(None, description="可选 UTC 小时时间；不传则返回最新配置"),
    detail: bool = Query(
        False,
        description=("v2: 是否展开 protocol_config；v3: 是否展开治理 assets 明细"),
    ),
) -> CompoundMarketConfigResponse:
    if version == "v2":
        market_cfg = await get_v2_market_config(
            pool=pool,
            version=version,
            market=market,
            date=date,
            w3=getattr(request.app.state, "w3", None),
        )
        protocol_cfg = None
        if detail:
            protocol_cfg = await get_v2_protocol_config(
                pool=pool,
                version=version,
                date=date,
            )
        return CompoundMarketConfigResponse(
            version=version,
            market_config=market_cfg,
            protocol_config=protocol_cfg,
        )

    market_cfg_v3 = await get_market_governance(
        pool=pool,
        version=version,
        market=market,
        date=date,
        detail=detail,
    )
    return CompoundMarketConfigResponse(
        version=version,
        market_config=market_cfg_v3,
        protocol_config=None,
    )


@router.get(
    "/market/config/period",
    response_model=CompoundMarketConfigPeriodResponse,
    summary="Query Compound market config changes over a period (v2/v3 unified)",
)
async def market_config_period(
    request: Request,
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query("v3", description=_VERSION_DESC_BOTH),
    market: str = Query(..., description='市场地址或名称：`"0x..." | "<SYMBOL>"`'),
    start: str = Query(..., description="UTC datetime at hour precision (start)"),
    end: str = Query(..., description="UTC datetime at hour precision (end)"),
    latest_only_per_day: bool = Query(False, description="每日仅保留最后一个变更点"),
    detail: bool = Query(
        False,
        description=("v2: 是否展开 protocol_config；v3: 是否展开治理 assets 明细"),
    ),
) -> CompoundMarketConfigPeriodResponse:
    if version == "v2":
        market_period = await get_v2_market_config_period(
            pool=pool,
            version=version,
            market=market,
            start=start,
            end=end,
            latest_only_per_day=latest_only_per_day,
            w3=getattr(request.app.state, "w3", None),
        )
        points: list[CompoundMarketConfigResponse] = []
        for point in market_period.points:
            protocol_cfg = None
            if detail:
                protocol_cfg = await get_v2_protocol_config(
                    pool=pool,
                    version=version,
                    date=point.effective_timestamp,
                )
            points.append(
                CompoundMarketConfigResponse(
                    version=version,
                    market_config=point,
                    protocol_config=protocol_cfg,
                )
            )
        return CompoundMarketConfigPeriodResponse(points=points)

    governance_period = await get_market_governance_period(
        pool=pool,
        version=version,
        market=market,
        start=start,
        end=end,
        latest_only_per_day=latest_only_per_day,
        detail=detail,
    )
    return CompoundMarketConfigPeriodResponse(
        points=[
            CompoundMarketConfigResponse(
                version=version,
                market_config=point,
                protocol_config=None,
            )
            for point in governance_period.points
        ]
    )


@router.get(
    "/market/state/period",
    response_model=MarketStatePeriodResponse,
    summary="Query Compound market state over a period",
)
async def market_state_period(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query("v3", description=_VERSION_DESC_BOTH),
    market: str = Query(..., description="market name or address"),
    start: str = Query(..., description="UTC datetime at hour precision (start)"),
    end: str = Query(..., description="UTC datetime at hour precision (end)"),
    interval: int = Query(24, description="Sampling interval in hours (1-168)"),
    detail: bool = Query(False, description="Whether to expand reserve details"),
) -> MarketStatePeriodResponse:
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
    version: Literal["v2", "v3"] = Query("v3", description=_VERSION_DESC_BOTH),
    market: str = Query(..., description="market name or address"),
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
