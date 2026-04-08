"""Service helpers for Morpho APIs."""

from __future__ import annotations

from decimal import Decimal

from .schemas import (
    MorphoPositionAssetResponse,
    MorphoPositionResponse,
    MorphoScaffoldStatusResponse,
)
from ..constants import (
    MORPHO_BLUE_ADDRESS,
    MORPHO_CHAIN,
    MORPHO_DEFAULT_MARKET_TYPE,
    MORPHO_PROTOCOL,
)
from ..rpc import fetch_realtime_position


def get_scaffold_status() -> MorphoScaffoldStatusResponse:
    return MorphoScaffoldStatusResponse(
        module=MORPHO_PROTOCOL,
        status="active",
        chain=MORPHO_CHAIN,
        supported_protocols=[MORPHO_DEFAULT_MARKET_TYPE],
        message=(
            "Morpho Blue realtime position query is available via RPC. "
            "Crawler and watcher remain scaffold-only."
        ),
    )


def _format_ratio(value: Decimal, scale: str = "0.000000000000000001") -> str:
    return format(value.quantize(Decimal(scale)), "f")


def _format_scaled(raw: int, decimals: int) -> str:
    return format(Decimal(raw) / (Decimal(10) ** decimals), "f")


def _format_oracle_price(
    raw: int,
    *,
    loan_decimals: int,
    collateral_decimals: int,
) -> str:
    scale = Decimal(10) ** (36 + loan_decimals - collateral_decimals)
    return format(Decimal(raw) / scale, "f")


async def get_user_position(
    w3,
    *,
    address: str,
    market_id: str,
    protocol: str,
) -> MorphoPositionResponse:
    if protocol != MORPHO_DEFAULT_MARKET_TYPE:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail=f"unsupported morpho protocol: {protocol}",
        )

    position = await fetch_realtime_position(
        w3,
        address=address,
        market_id=market_id,
    )

    return MorphoPositionResponse(
        protocol=MORPHO_PROTOCOL,
        market_type=MORPHO_DEFAULT_MARKET_TYPE,
        chain=MORPHO_CHAIN,
        morpho_address=MORPHO_BLUE_ADDRESS,
        market_id=position.market_id,
        address=position.user_address,
        block_number=position.block_number,
        block_timestamp=position.block_timestamp.isoformat().replace("+00:00", "Z"),
        has_position=position.has_position,
        is_healthy=position.is_healthy,
        loan_token=position.loan_token.address,
        loan_token_symbol=position.loan_token.symbol,
        loan_token_decimals=position.loan_token.decimals,
        collateral_token=position.collateral_token.address,
        collateral_token_symbol=position.collateral_token.symbol,
        collateral_token_decimals=position.collateral_token.decimals,
        oracle=position.oracle,
        irm=position.irm,
        lltv=str(position.lltv),
        lltv_ratio=_format_ratio(Decimal(position.lltv) / Decimal(10**18), "0.000000"),
        supply_shares=str(position.supply_shares),
        borrow_shares=str(position.borrow_shares),
        collateral_assets_raw=str(position.collateral_raw),
        supply_assets=_format_scaled(
            position.supply_assets_raw,
            position.loan_token.decimals,
        ),
        borrow_assets=_format_scaled(
            position.borrow_assets_raw,
            position.loan_token.decimals,
        ),
        collateral_assets=_format_scaled(
            position.collateral_raw,
            position.collateral_token.decimals,
        ),
        collateral_value_in_loan_asset=_format_scaled(
            position.collateral_value_in_loan_asset_raw,
            position.loan_token.decimals,
        ),
        max_borrowable_in_loan_asset=_format_scaled(
            position.max_borrowable_raw,
            position.loan_token.decimals,
        ),
        health_factor=(
            None
            if position.health_factor is None
            else _format_ratio(position.health_factor)
        ),
        price_quote=_format_oracle_price(
            position.price_raw,
            loan_decimals=position.loan_token.decimals,
            collateral_decimals=position.collateral_token.decimals,
        ),
        data_source="rpc",
        assets=[
            MorphoPositionAssetResponse(
                role="loan",
                token_address=position.loan_token.address,
                symbol=position.loan_token.symbol,
                decimals=position.loan_token.decimals,
                amount=_format_scaled(
                    position.supply_assets_raw - position.borrow_assets_raw,
                    position.loan_token.decimals,
                ),
            ),
            MorphoPositionAssetResponse(
                role="collateral",
                token_address=position.collateral_token.address,
                symbol=position.collateral_token.symbol,
                decimals=position.collateral_token.decimals,
                amount=_format_scaled(
                    position.collateral_raw,
                    position.collateral_token.decimals,
                ),
            ),
        ],
    )
