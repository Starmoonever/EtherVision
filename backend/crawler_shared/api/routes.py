"""Protocol-agnostic API routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from ..database import AsyncpgPool
from .schemas import PriceAssetsResponse, PricePeriodResponse, PriceResponse
from .service import get_price, get_price_period_service, get_supported_price_assets

router = APIRouter(prefix="/api")


def _w3(request: Request):
    w3 = request.app.state.w3
    if w3 is None:
        raise HTTPException(status_code=503, detail="RPC 节点尚未就绪，请稍后重试")
    return w3


def _parse_utc_time(time_str: str) -> int:
    formats = (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    )
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
        detail="date/time 格式无法识别，支持示例：2024-11-14T12:00:00Z、2024-11-14 12:00:00、2024-11-14",
    )


def _require_symbol_or_address(
    *,
    symbol: str | None,
    address: str | None,
) -> tuple[str | None, str | None]:
    normalized_symbol = symbol.strip() if symbol is not None else None
    normalized_address = address.strip() if address is not None else None
    if not normalized_symbol:
        normalized_symbol = None
    if not normalized_address:
        normalized_address = None
    if (normalized_symbol is None) == (normalized_address is None):
        raise HTTPException(
            status_code=400,
            detail="symbol 和 address 必须且只能提供其中一个",
        )
    return normalized_symbol, normalized_address


@router.get(
    "/price/assets",
    response_model=PriceAssetsResponse,
    summary="列出支持价格查询的资产",
)
async def price_assets() -> PriceAssetsResponse:
    return await get_supported_price_assets()


@router.get(
    "/price", response_model=PriceResponse, summary="查询资产价格（当前或历史）"
)
async def asset_price(
    request: Request,
    pool: AsyncpgPool,
    symbol: str | None = Query(None, description="代币符号，如 ETH、WBTC、USDC"),
    address: str | None = Query(None, description="EVM 代币地址，如 0x..."),
    time: str = Query("now", description="now 或 UTC 时间字符串"),
) -> PriceResponse:
    symbol, address = _require_symbol_or_address(symbol=symbol, address=address)
    if time == "now":
        return await get_price(_w3(request), symbol=symbol, address=address, pool=pool)
    return await get_price(
        _w3(request),
        symbol=symbol,
        address=address,
        pool=pool,
        timestamp=_parse_utc_time(time),
    )


@router.get(
    "/price/period", response_model=PricePeriodResponse, summary="查询资产历史价格时序"
)
async def asset_price_period(
    request: Request,
    pool: AsyncpgPool,
    symbol: str | None = Query(None, description="代币符号，如 ETH、WBTC、USDC"),
    address: str | None = Query(None, description="EVM 代币地址，如 0x..."),
    start: str = Query(..., description="起始时间（UTC）"),
    end: str = Query(..., description="结束时间（UTC）"),
    interval: int = Query(60, ge=1, description="采样间隔（分钟），最小 1"),
) -> PricePeriodResponse:
    symbol, address = _require_symbol_or_address(symbol=symbol, address=address)
    start_ts = _parse_utc_time(start)
    end_ts = _parse_utc_time(end)
    if start_ts > end_ts:
        raise HTTPException(status_code=400, detail="start 必须早于或等于 end")
    return await get_price_period_service(
        _w3(request),
        pool,
        symbol=symbol,
        address=address,
        start=start_ts,
        end=end_ts,
        interval=interval,
    )
