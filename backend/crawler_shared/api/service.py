"""Shared service wrappers for protocol-agnostic APIs."""

from __future__ import annotations

from web3 import AsyncWeb3

from .constants import SUPPORTED_PRICE_ASSETS
from .schemas import (
    PriceAssetsResponse,
    PriceAssetSchema,
    PricePeriodResponse,
    PriceResponse,
)


async def get_supported_price_assets() -> PriceAssetsResponse:
    return PriceAssetsResponse(
        assets=[
            PriceAssetSchema(asset=asset, token_address=token_address, chain=chain)
            for asset, token_address, chain in SUPPORTED_PRICE_ASSETS
        ]
    )


async def get_price(
    w3: AsyncWeb3,
    asset: str,
    *,
    pool,
    timestamp: int | None = None,
) -> PriceResponse:
    from aave_crawler.api.service import get_eth_price

    return await get_eth_price(w3, asset, timestamp=timestamp, pool=pool)


async def get_price_period_service(
    w3: AsyncWeb3,
    pool,
    *,
    asset: str,
    start: int,
    end: int,
    interval: int,
) -> PricePeriodResponse:
    from aave_crawler.api.service import get_price_period

    return await get_price_period(
        w3,
        asset,
        start_ts=start,
        end_ts=end,
        interval_minutes=interval,
        pool=pool,
    )
