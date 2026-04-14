"""Service helpers for Morpho APIs."""

from __future__ import annotations

import json
from decimal import Decimal

from fastapi import HTTPException
from web3 import AsyncWeb3

from ..database import AsyncpgPool
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
from ..db import fetch_current_user_positions, upsert_current_user_position, upsert_market
from ..rpc import MorphoRealtimePosition, fetch_realtime_position


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


def _normalize_market_id_text(market_id: str) -> str:
    value = market_id.strip().lower()
    if not value.startswith("0x"):
        value = f"0x{value}"
    return value


def _evm_to_db_bytes(address: str) -> bytes:
    checksum = AsyncWeb3.to_checksum_address(address)
    return bytes.fromhex(checksum[2:])


def _db_bytes_to_evm(value: bytes | bytearray | memoryview | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raw = bytes(value)
    if len(raw) == 20:
        return AsyncWeb3.to_checksum_address(f"0x{raw.hex()}")
    try:
        decoded = raw.decode("utf-8")
        if decoded.startswith("0x"):
            return AsyncWeb3.to_checksum_address(decoded)
        return decoded
    except UnicodeDecodeError:
        return f"0x{raw.hex()}"


def _build_response_from_rpc(
    position: MorphoRealtimePosition,
    *,
    data_source: str,
) -> MorphoPositionResponse:
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
            None if position.health_factor is None else _format_ratio(position.health_factor)
        ),
        price_quote=_format_oracle_price(
            position.price_raw,
            loan_decimals=position.loan_token.decimals,
            collateral_decimals=position.collateral_token.decimals,
        ),
        data_source=data_source,
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


def _build_response_from_db(position_row, asset_rows) -> MorphoPositionResponse | None:
    extra_raw = position_row.get("extra_jsonb")
    if isinstance(extra_raw, dict):
        extra = extra_raw
    elif isinstance(extra_raw, (str, bytes, bytearray, memoryview)):
        try:
            if isinstance(extra_raw, (bytes, bytearray, memoryview)):
                extra = json.loads(bytes(extra_raw).decode("utf-8"))
            else:
                extra = json.loads(extra_raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            extra = {}
    else:
        extra = {}

    loan_token = extra.get("loan_token")
    collateral_token = extra.get("collateral_token")
    if not isinstance(loan_token, dict) or not isinstance(collateral_token, dict):
        return None

    assets = [
        MorphoPositionAssetResponse(
            role=str(asset.get("side")),
            token_address=_db_bytes_to_evm(asset.get("asset_address")),
            symbol=asset.get("symbol"),
            decimals=int(asset.get("decimals") or 18),
            amount=str(asset.get("amount") or "0"),
        )
        for asset in asset_rows
    ]

    block_ts = position_row.get("block_timestamp")
    if block_ts is None:
        return None

    health_factor_raw = position_row.get("health_factor")
    has_position = (
        Decimal(position_row.get("supply_shares") or "0")
        + Decimal(position_row.get("borrow_shares") or "0")
        + Decimal(position_row.get("collateral_amount") or "0")
    ) > 0
    is_healthy = bool(extra.get("is_healthy", True))

    return MorphoPositionResponse(
        protocol=str(position_row.get("protocol") or MORPHO_PROTOCOL),
        market_type=str(position_row.get("market_type") or MORPHO_DEFAULT_MARKET_TYPE),
        chain=str(position_row.get("chain") or MORPHO_CHAIN),
        morpho_address=str(extra.get("morpho_address") or MORPHO_BLUE_ADDRESS),
        market_id=str(position_row.get("market_id")),
        address=_db_bytes_to_evm(position_row.get("user_address")),
        block_number=int(position_row.get("block_number") or 0),
        block_timestamp=block_ts.isoformat().replace("+00:00", "Z"),
        has_position=has_position,
        is_healthy=is_healthy,
        loan_token=str(loan_token.get("address") or ""),
        loan_token_symbol=loan_token.get("symbol"),
        loan_token_decimals=int(loan_token.get("decimals") or 18),
        collateral_token=str(collateral_token.get("address") or ""),
        collateral_token_symbol=collateral_token.get("symbol"),
        collateral_token_decimals=int(collateral_token.get("decimals") or 18),
        oracle=str(extra.get("oracle") or ""),
        irm=str(extra.get("irm") or ""),
        lltv=str(extra.get("lltv") or "0"),
        lltv_ratio=str(extra.get("lltv_ratio") or "0"),
        supply_shares=str(extra.get("supply_shares_raw") or position_row.get("supply_shares") or "0"),
        borrow_shares=str(extra.get("borrow_shares_raw") or position_row.get("borrow_shares") or "0"),
        collateral_assets_raw=str(
            extra.get("collateral_assets_raw") or position_row.get("collateral_amount") or "0"
        ),
        supply_assets=str(extra.get("supply_assets") or "0"),
        borrow_assets=str(extra.get("borrow_assets") or "0"),
        collateral_assets=str(extra.get("collateral_assets") or "0"),
        collateral_value_in_loan_asset=str(
            extra.get("collateral_value_in_loan_asset") or "0"
        ),
        max_borrowable_in_loan_asset=str(extra.get("max_borrowable_in_loan_asset") or "0"),
        health_factor=(
            None
            if extra.get("health_factor") is None and Decimal(health_factor_raw or "0") == 0
            else str(extra.get("health_factor") or health_factor_raw)
        ),
        price_quote=str(extra.get("price_quote") or "0"),
        data_source="db",
        assets=assets,
    )


async def get_user_position(
    w3,
    *,
    pool: AsyncpgPool,
    address: str,
    market_id: str,
    protocol: str,
) -> MorphoPositionResponse:
    if protocol != MORPHO_DEFAULT_MARKET_TYPE:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported morpho protocol: {protocol}",
        )

    normalized_market_id = _normalize_market_id_text(market_id)
    user_key = _evm_to_db_bytes(address)

    cached_positions, cached_assets = await fetch_current_user_positions(
        pool,
        user_address=user_key,
        market_id=normalized_market_id,
    )
    if cached_positions:
        cached_response = _build_response_from_db(cached_positions[0], cached_assets)
        if cached_response is not None:
            return cached_response

    position = await fetch_realtime_position(
        w3,
        address=address,
        market_id=normalized_market_id,
    )

    response = _build_response_from_rpc(position, data_source="rpc")

    await upsert_market(
        pool,
        market_id=position.market_id,
        chain=MORPHO_CHAIN,
        protocol=MORPHO_PROTOCOL,
        market_type=MORPHO_DEFAULT_MARKET_TYPE,
        loan_token_address=_evm_to_db_bytes(position.loan_token.address),
        collateral_token_address=_evm_to_db_bytes(position.collateral_token.address),
        oracle_address=_evm_to_db_bytes(position.oracle),
        irm_address=_evm_to_db_bytes(position.irm),
        lltv=Decimal(position.lltv) / Decimal(10**18),
        extra_jsonb={
            "oracle": position.oracle,
            "irm": position.irm,
        },
    )
    await upsert_current_user_position(
        pool,
        market_id=position.market_id,
        user_address=_evm_to_db_bytes(position.user_address),
        chain=MORPHO_CHAIN,
        protocol=MORPHO_PROTOCOL,
        market_type=MORPHO_DEFAULT_MARKET_TYPE,
        snapshot_at=position.block_timestamp,
        block_timestamp=position.block_timestamp,
        block_number=position.block_number,
        # DB columns are NUMERIC(40,18), so store scaled values
        supply_shares=Decimal(position.supply_shares) / Decimal(10**18),
        borrow_shares=Decimal(position.borrow_shares) / Decimal(10**18),
        collateral_amount=Decimal(response.collateral_assets),
        collateral_usd=Decimal("0"),
        debt_usd=Decimal("0"),
        health_factor=position.health_factor or Decimal("0"),
        extra_jsonb={
            "morpho_address": position.morpho_address,
            "oracle": position.oracle,
            "irm": position.irm,
            "lltv": str(position.lltv),
            "lltv_ratio": _format_ratio(Decimal(position.lltv) / Decimal(10**18), "0.000000"),
            "loan_token": {
                "address": position.loan_token.address,
                "symbol": position.loan_token.symbol,
                "decimals": position.loan_token.decimals,
            },
            "collateral_token": {
                "address": position.collateral_token.address,
                "symbol": position.collateral_token.symbol,
                "decimals": position.collateral_token.decimals,
            },
            "supply_assets": response.supply_assets,
            "borrow_assets": response.borrow_assets,
            "collateral_assets": response.collateral_assets,
            "collateral_value_in_loan_asset": response.collateral_value_in_loan_asset,
            "max_borrowable_in_loan_asset": response.max_borrowable_in_loan_asset,
            "health_factor": response.health_factor,
            "price_quote": response.price_quote,
            "is_healthy": response.is_healthy,
            "supply_shares_raw": str(position.supply_shares),
            "borrow_shares_raw": str(position.borrow_shares),
            "collateral_assets_raw": str(position.collateral_raw),
        },
        assets=[
            {
                "asset_address": _evm_to_db_bytes(position.loan_token.address),
                "side": "loan",
                "symbol": position.loan_token.symbol,
                "decimals": position.loan_token.decimals,
                "amount": Decimal(response.supply_assets) - Decimal(response.borrow_assets),
                "price_usd": Decimal("0"),
                "value_usd": Decimal("0"),
                "extra_jsonb": {},
            },
            {
                "asset_address": _evm_to_db_bytes(position.collateral_token.address),
                "side": "collateral",
                "symbol": position.collateral_token.symbol,
                "decimals": position.collateral_token.decimals,
                "amount": Decimal(response.collateral_assets),
                "price_usd": Decimal("0"),
                "value_usd": Decimal("0"),
                "extra_jsonb": {},
            },
        ],
    )
    return response
