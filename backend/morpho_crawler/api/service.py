"""Service helpers for Morpho APIs."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from crawler_shared.api.service import get_price
from crawler_shared.price_history import get_historical_price_usd
from fastapi import HTTPException
from web3 import AsyncWeb3

from ..constants import (
    MORPHO_BLUE_ADDRESS,
    MORPHO_CHAIN,
    MORPHO_DEFAULT_MARKET_TYPE,
    MORPHO_PROTOCOL,
)
from ..database import AsyncpgPool
from ..db import (
    fetch_current_user_positions,
    fetch_position_replay_snapshots,
    upsert_current_user_position,
    upsert_market,
    upsert_position_replay_snapshots,
)
from ..rpc import (
    MorphoReplayEvent,
    MorphoRealtimePosition,
    fetch_position_at_block,
    fetch_realtime_position,
    fetch_user_market_replay_events,
)
from .schemas import (
    MorphoPositionAssetResponse,
    MorphoPositionReplayPointResponse,
    MorphoPositionReplayResponse,
    MorphoPositionResponse,
    MorphoScaffoldStatusResponse,
)

BRIEF_LABELS = {
    "supply": "供给",
    "withdraw": "提取",
    "borrow": "借入",
    "repay": "还款",
    "supply_collateral": "新增抵押",
    "withdraw_collateral": "移除抵押",
    "liquidation": "被清算",
}


def get_scaffold_status() -> MorphoScaffoldStatusResponse:
    return MorphoScaffoldStatusResponse(
        module=MORPHO_PROTOCOL,
        status="active",
        chain=MORPHO_CHAIN,
        supported_protocols=[MORPHO_DEFAULT_MARKET_TYPE],
        message=(
            "Morpho Blue realtime position query is available via RPC. "
            "Replay snapshots are populated lazily on API requests."
        ),
    )


def parse_utc_time(value: str) -> int:
    text = value.strip()
    if not text:
        raise HTTPException(status_code=400, detail="时间不能为空")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid UTC datetime: {value}"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp())


def _record_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _format_brief_amount(amount: Decimal) -> str:
    text = format(amount.quantize(Decimal("0.01")).normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _format_brief_usd(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _normalize_market_id_text(market_id: str) -> str:
    value = market_id.strip().lower()
    if not value.startswith("0x"):
        value = f"0x{value}"
    return value


def _evm_to_db_bytes(address: str) -> bytes:
    try:
        checksum = AsyncWeb3.to_checksum_address(address)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid EVM address") from exc
    return bytes.fromhex(checksum[2:])


def _normalize_evm_address(address: str) -> str:
    try:
        return AsyncWeb3.to_checksum_address(address)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid EVM address") from exc


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
    except UnicodeDecodeError:
        return f"0x{raw.hex()}"
    if decoded.startswith("0x"):
        return AsyncWeb3.to_checksum_address(decoded)
    return decoded


def _parse_extra_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return json.loads(bytes(value).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_assets_json(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            payload = json.loads(bytes(value).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return []
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [item for item in payload if isinstance(item, dict)]
    return []


def _format_health(value: Decimal | None, *, borrow_assets: Decimal) -> str | None:
    if value is None:
        return None
    if borrow_assets <= 0 and value == 0:
        return None
    return _format_ratio(value)


def _build_asset_responses(
    assets: list[dict[str, Any]],
) -> list[MorphoPositionAssetResponse]:
    return [
        MorphoPositionAssetResponse(
            role=str(asset.get("side") or ""),
            token_address=_db_bytes_to_evm(asset.get("asset_address")),
            symbol=asset.get("symbol"),
            decimals=int(asset.get("decimals") or 18),
            amount=str(asset.get("amount") or "0"),
            price_usd=(
                None if asset.get("price_usd") is None else str(asset.get("price_usd"))
            ),
            value_usd=(
                None if asset.get("value_usd") is None else str(asset.get("value_usd"))
            ),
        )
        for asset in assets
    ]


async def _get_asset_price_usd(
    w3: AsyncWeb3,
    *,
    pool: AsyncpgPool,
    token_address: str,
    timestamp: int | None,
    cache: dict[tuple[str, int | None], Decimal | None],
) -> Decimal | None:
    cache_key = (token_address.lower(), timestamp)
    if cache_key in cache:
        return cache[cache_key]
    try:
        if timestamp is not None:
            price, _, _ = await get_historical_price_usd(
                pool,
                token_address=token_address,
                asset_label=token_address,
                requested_ts=timestamp,
            )
            cache[cache_key] = price
            return price
        result = await get_price(
            w3,
            symbol=None,
            address=token_address,
            pool=pool,
            timestamp=None,
        )
    except HTTPException:
        cache[cache_key] = None
        return None
    price = Decimal(str(result.price_usd))
    cache[cache_key] = price
    return price


async def _enrich_position_assets_with_prices(
    w3: AsyncWeb3,
    *,
    pool: AsyncpgPool,
    response: MorphoPositionResponse,
    timestamp: int | None,
    cache: dict[tuple[str, int | None], Decimal | None],
) -> None:
    loan_price_usd = await _get_asset_price_usd(
        w3,
        pool=pool,
        token_address=response.loan_token,
        timestamp=timestamp,
        cache=cache,
    )
    collateral_price_usd = await _get_asset_price_usd(
        w3,
        pool=pool,
        token_address=response.collateral_token,
        timestamp=timestamp,
        cache=cache,
    )
    for asset in response.assets:
        price_usd = (
            collateral_price_usd if asset.role == "collateral" else loan_price_usd
        )
        amount = Decimal(str(asset.amount or "0"))
        asset.price_usd = None if price_usd is None else str(price_usd)
        asset.value_usd = None if price_usd is None else str(amount * price_usd)


def _build_response_from_rpc(
    position: MorphoRealtimePosition,
    *,
    data_source: str,
) -> MorphoPositionResponse:
    collateral_value = _format_scaled(
        position.collateral_value_in_loan_asset_raw,
        position.loan_token.decimals,
    )
    borrow_assets = _format_scaled(
        position.borrow_assets_raw,
        position.loan_token.decimals,
    )
    collateral_assets = _format_scaled(
        position.collateral_raw,
        position.collateral_token.decimals,
    )
    return MorphoPositionResponse(
        protocol=MORPHO_PROTOCOL,
        market_type=MORPHO_DEFAULT_MARKET_TYPE,
        chain=MORPHO_CHAIN,
        morpho_address=MORPHO_BLUE_ADDRESS,
        market_id=position.market_id,
        address=position.user_address,
        block_number=position.block_number,
        block_timestamp=_record_ts(position.block_timestamp),
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
            position.supply_assets_raw, position.loan_token.decimals
        ),
        borrow_assets=borrow_assets,
        collateral_assets=collateral_assets,
        collateral_value_in_loan_asset=collateral_value,
        max_borrowable_in_loan_asset=_format_scaled(
            position.max_borrowable_raw,
            position.loan_token.decimals,
        ),
        health_factor=_format_health(
            position.health_factor,
            borrow_assets=Decimal(borrow_assets),
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
                price_usd=None,
                value_usd=None,
            ),
            MorphoPositionAssetResponse(
                role="collateral",
                token_address=position.collateral_token.address,
                symbol=position.collateral_token.symbol,
                decimals=position.collateral_token.decimals,
                amount=collateral_assets,
                price_usd=None,
                value_usd=None,
            ),
        ],
    )


def _build_response_from_db(
    position_row: Any, asset_rows: list[Any]
) -> MorphoPositionResponse | None:
    extra = _parse_extra_json(position_row.get("extra_jsonb"))
    loan_token = extra.get("loan_token")
    collateral_token = extra.get("collateral_token")
    if not isinstance(loan_token, dict) or not isinstance(collateral_token, dict):
        return None

    block_ts = position_row.get("block_timestamp")
    if block_ts is None:
        return None

    borrow_assets = Decimal(str(extra.get("borrow_assets") or "0"))
    health_factor_raw = position_row.get("health_factor")
    has_position = (
        Decimal(position_row.get("supply_shares") or "0")
        + Decimal(position_row.get("borrow_shares") or "0")
        + Decimal(position_row.get("collateral_amount") or "0")
    ) > 0

    return MorphoPositionResponse(
        protocol=str(position_row.get("protocol") or MORPHO_PROTOCOL),
        market_type=str(position_row.get("market_type") or MORPHO_DEFAULT_MARKET_TYPE),
        chain=str(position_row.get("chain") or MORPHO_CHAIN),
        morpho_address=str(extra.get("morpho_address") or MORPHO_BLUE_ADDRESS),
        market_id=str(position_row.get("market_id")),
        address=_db_bytes_to_evm(position_row.get("user_address")),
        block_number=int(position_row.get("block_number") or 0),
        block_timestamp=_record_ts(block_ts),
        has_position=has_position,
        is_healthy=bool(extra.get("is_healthy", True)),
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
        supply_shares=str(
            extra.get("supply_shares_raw") or position_row.get("supply_shares") or "0"
        ),
        borrow_shares=str(
            extra.get("borrow_shares_raw") or position_row.get("borrow_shares") or "0"
        ),
        collateral_assets_raw=str(
            extra.get("collateral_assets_raw")
            or position_row.get("collateral_amount")
            or "0"
        ),
        supply_assets=str(extra.get("supply_assets") or "0"),
        borrow_assets=str(extra.get("borrow_assets") or "0"),
        collateral_assets=str(extra.get("collateral_assets") or "0"),
        collateral_value_in_loan_asset=str(
            extra.get("collateral_value_in_loan_asset") or "0"
        ),
        max_borrowable_in_loan_asset=str(
            extra.get("max_borrowable_in_loan_asset") or "0"
        ),
        health_factor=_format_health(
            None
            if extra.get("health_factor") is None
            and Decimal(health_factor_raw or "0") == 0
            else Decimal(str(extra.get("health_factor") or health_factor_raw or "0")),
            borrow_assets=borrow_assets,
        ),
        price_quote=str(extra.get("price_quote") or "0"),
        data_source="db",
        assets=_build_asset_responses(
            [
                {
                    "side": asset.get("side"),
                    "asset_address": asset.get("asset_address"),
                    "symbol": asset.get("symbol"),
                    "decimals": asset.get("decimals"),
                    "amount": asset.get("amount"),
                    "price_usd": asset.get("price_usd"),
                    "value_usd": asset.get("value_usd"),
                }
                for asset in asset_rows
            ]
        ),
    )


async def _upsert_market_from_position(
    pool: AsyncpgPool,
    *,
    position: MorphoRealtimePosition,
) -> None:
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
        extra_jsonb={"oracle": position.oracle, "irm": position.irm},
    )


async def _cache_current_position(
    pool: AsyncpgPool,
    *,
    position: MorphoRealtimePosition,
    response: MorphoPositionResponse,
) -> None:
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
            "lltv_ratio": response.lltv_ratio,
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
                "amount": Decimal(response.supply_assets)
                - Decimal(response.borrow_assets),
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


def _build_single_event_brief(
    event: MorphoReplayEvent,
    *,
    loan_symbol: str | None,
    collateral_symbol: str | None,
    loan_decimals: int,
    collateral_decimals: int,
    loan_price_usd: Decimal | None,
    collateral_price_usd: Decimal | None,
) -> str:
    label = BRIEF_LABELS.get(event.operation_type, "更新仓位")
    if event.operation_type in {"supply", "withdraw", "borrow", "repay"}:
        amount = Decimal(event.assets or 0) / (Decimal(10) ** loan_decimals)
        value_suffix = ""
        if loan_price_usd is not None and loan_price_usd > 0:
            value_suffix = f" (价值 {_format_brief_usd(amount * loan_price_usd)} usd)"
        if loan_symbol:
            return f"{label} {_format_brief_amount(amount)} {loan_symbol}{value_suffix}"
        return label
    if event.operation_type in {"supply_collateral", "withdraw_collateral"}:
        amount = Decimal(event.collateral_assets or 0) / (
            Decimal(10) ** collateral_decimals
        )
        value_suffix = ""
        if collateral_price_usd is not None and collateral_price_usd > 0:
            value_suffix = (
                f" (价值 {_format_brief_usd(amount * collateral_price_usd)} usd)"
            )
        if collateral_symbol:
            return f"{label} {_format_brief_amount(amount)} {collateral_symbol}{value_suffix}"
        return label
    if event.operation_type == "liquidation":
        parts: list[str] = []
        if event.seized_assets:
            amount = Decimal(event.seized_assets) / (Decimal(10) ** collateral_decimals)
            if collateral_symbol:
                part = f"扣押 {_format_brief_amount(amount)} {collateral_symbol}"
                if collateral_price_usd is not None and collateral_price_usd > 0:
                    part += f" (价值 {_format_brief_usd(amount * collateral_price_usd)} usd)"
                parts.append(part)
        if event.repaid_assets:
            amount = Decimal(event.repaid_assets) / (Decimal(10) ** loan_decimals)
            if loan_symbol:
                part = f"偿还 {_format_brief_amount(amount)} {loan_symbol}"
                if loan_price_usd is not None and loan_price_usd > 0:
                    part += f" (价值 {_format_brief_usd(amount * loan_price_usd)} usd)"
                parts.append(part)
        if parts:
            return f"{label}，" + "，".join(parts)
        return label
    return label


def _build_group_brief(
    events: list[MorphoReplayEvent],
    *,
    loan_symbol: str | None,
    collateral_symbol: str | None,
    loan_decimals: int,
    collateral_decimals: int,
    loan_price_usd: Decimal | None,
    collateral_price_usd: Decimal | None,
) -> tuple[str | None, str]:
    operations: list[str] = []
    briefs: list[str] = []
    for event in events:
        operations.append(event.operation_type)
        briefs.append(
            _build_single_event_brief(
                event,
                loan_symbol=loan_symbol,
                collateral_symbol=collateral_symbol,
                loan_decimals=loan_decimals,
                collateral_decimals=collateral_decimals,
                loan_price_usd=loan_price_usd,
                collateral_price_usd=collateral_price_usd,
            )
        )
    deduped_briefs: list[str] = []
    for brief in briefs:
        if brief not in deduped_briefs:
            deduped_briefs.append(brief)
    operation_type = operations[0] if len(set(operations)) == 1 else "batch"
    return operation_type, "；".join(deduped_briefs)


def _build_replay_snapshot_row(
    *,
    position: MorphoRealtimePosition,
    response: MorphoPositionResponse,
    tx_hash: str,
    operation_type: str | None,
    brief: str,
) -> dict[str, Any]:
    borrow_assets = Decimal(response.borrow_assets)
    health_factor = (
        Decimal(response.health_factor)
        if response.health_factor is not None
        else Decimal("0")
    )
    assets_jsonb = [
        {
            "side": asset.role,
            "asset_address": asset.token_address,
            "symbol": asset.symbol,
            "decimals": asset.decimals,
            "amount": asset.amount,
            "price_usd": asset.price_usd,
            "value_usd": asset.value_usd,
        }
        for asset in response.assets
    ]
    return {
        "market_id": position.market_id,
        "user_address": _evm_to_db_bytes(position.user_address),
        "chain": MORPHO_CHAIN,
        "protocol": MORPHO_PROTOCOL,
        "market_type": MORPHO_DEFAULT_MARKET_TYPE,
        "tx_hash": tx_hash,
        "block_number": position.block_number,
        "block_timestamp": position.block_timestamp,
        "operation_type": operation_type,
        "has_position": response.has_position,
        "is_healthy": response.is_healthy,
        "collateral_value_in_loan_asset": Decimal(
            response.collateral_value_in_loan_asset
        ),
        "borrow_assets": borrow_assets,
        "health_factor": health_factor,
        "assets_jsonb": assets_jsonb,
        "extra_jsonb": {
            "loan_token": {
                "address": response.loan_token,
                "symbol": response.loan_token_symbol,
                "decimals": response.loan_token_decimals,
            },
            "collateral_token": {
                "address": response.collateral_token,
                "symbol": response.collateral_token_symbol,
                "decimals": response.collateral_token_decimals,
            },
        },
        "brief": brief,
    }


def _map_replay_row_to_point(
    row: Any,
    *,
    detail: bool,
) -> MorphoPositionReplayPointResponse:
    assets = _parse_assets_json(row.get("assets_jsonb"))
    borrow_assets = Decimal(str(row.get("borrow_assets") or "0"))
    health_factor_raw = Decimal(str(row.get("health_factor") or "0"))
    return MorphoPositionReplayPointResponse(
        tx_hash=str(row.get("tx_hash") or ""),
        timestamp=_record_ts(row["block_timestamp"]),
        block_number=int(row.get("block_number") or 0),
        operation_type=row.get("operation_type"),
        brief=str(row.get("brief") or ""),
        has_position=bool(row.get("has_position")),
        is_healthy=bool(row.get("is_healthy")),
        collateral_value_in_loan_asset=str(
            row.get("collateral_value_in_loan_asset") or "0"
        ),
        borrow_assets=str(row.get("borrow_assets") or "0"),
        health_factor=_format_health(health_factor_raw, borrow_assets=borrow_assets),
        assets=_build_asset_responses(assets) if detail else [],
    )


async def get_user_position(
    w3: AsyncWeb3,
    *,
    pool: AsyncpgPool,
    address: str,
    market_id: str,
    protocol: str,
) -> MorphoPositionResponse:
    if protocol != MORPHO_DEFAULT_MARKET_TYPE:
        raise HTTPException(
            status_code=400, detail=f"unsupported morpho protocol: {protocol}"
        )

    normalized_market_id = _normalize_market_id_text(market_id)
    user_key = _evm_to_db_bytes(address)
    price_cache: dict[tuple[str, int | None], Decimal | None] = {}

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
    await _enrich_position_assets_with_prices(
        w3,
        pool=pool,
        response=response,
        timestamp=None,
        cache=price_cache,
    )
    await _upsert_market_from_position(pool, position=position)
    await _cache_current_position(pool, position=position, response=response)
    return response


async def get_position_replay(
    w3: AsyncWeb3,
    *,
    pool: AsyncpgPool,
    address: str,
    market_id: str,
    protocol: str,
    from_ts: int,
    to_ts: int,
    use_cache: bool = True,
    detail: bool = False,
) -> MorphoPositionReplayResponse:
    if protocol != MORPHO_DEFAULT_MARKET_TYPE:
        raise HTTPException(
            status_code=400, detail=f"unsupported morpho protocol: {protocol}"
        )

    normalized_market_id = _normalize_market_id_text(market_id)
    user_key = _evm_to_db_bytes(address)
    from_dt = datetime.fromtimestamp(from_ts, tz=timezone.utc)
    to_dt = datetime.fromtimestamp(to_ts, tz=timezone.utc)
    price_cache: dict[tuple[str, int | None], Decimal | None] = {}

    if use_cache:
        cached_rows = await fetch_position_replay_snapshots(
            pool,
            user_address=user_key,
            market_id=normalized_market_id,
            from_ts=from_dt,
            to_ts=to_dt,
        )
        if cached_rows:
            points = [
                _map_replay_row_to_point(row, detail=detail) for row in cached_rows
            ]
            return MorphoPositionReplayResponse(
                protocol=MORPHO_PROTOCOL,
                market_type=MORPHO_DEFAULT_MARKET_TYPE,
                chain=MORPHO_CHAIN,
                market_id=normalized_market_id,
                address=_normalize_evm_address(address),
                from_time=_record_ts(from_dt),
                to_time=_record_ts(to_dt),
                data_source="cache",
                total_points=len(points),
                total_tx_count=len(points),
                cache_hit_rate="1.00",
                points=points,
            )

    events = await fetch_user_market_replay_events(
        w3,
        address=address,
        market_id=normalized_market_id,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    if not events:
        return MorphoPositionReplayResponse(
            protocol=MORPHO_PROTOCOL,
            market_type=MORPHO_DEFAULT_MARKET_TYPE,
            chain=MORPHO_CHAIN,
            market_id=normalized_market_id,
            address=_normalize_evm_address(address),
            from_time=_record_ts(from_dt),
            to_time=_record_ts(to_dt),
            data_source="rpc",
            total_points=0,
            total_tx_count=0,
            cache_hit_rate="0.00" if use_cache else "0.00",
            points=[],
        )

    grouped: dict[str, list[MorphoReplayEvent]] = defaultdict(list)
    for event in events:
        grouped[event.tx_hash].append(event)

    snapshot_rows: list[dict[str, Any]] = []
    points: list[MorphoPositionReplayPointResponse] = []
    for tx_hash, tx_events in sorted(
        grouped.items(),
        key=lambda item: (item[1][-1].block_number, item[1][-1].log_index, item[0]),
    ):
        tx_events.sort(key=lambda item: item.log_index)
        block_number = tx_events[-1].block_number
        position = await fetch_position_at_block(
            w3,
            address=address,
            market_id=normalized_market_id,
            block_identifier=block_number,
        )
        response = _build_response_from_rpc(position, data_source="rpc")
        await _enrich_position_assets_with_prices(
            w3,
            pool=pool,
            response=response,
            timestamp=int(position.block_timestamp.timestamp()),
            cache=price_cache,
        )
        await _upsert_market_from_position(pool, position=position)
        loan_price_usd = (
            Decimal(response.assets[0].price_usd)
            if response.assets and response.assets[0].price_usd is not None
            else None
        )
        collateral_price_usd = (
            Decimal(response.assets[1].price_usd)
            if len(response.assets) > 1 and response.assets[1].price_usd is not None
            else None
        )
        operation_type, brief = _build_group_brief(
            tx_events,
            loan_symbol=response.loan_token_symbol,
            collateral_symbol=response.collateral_token_symbol,
            loan_decimals=response.loan_token_decimals,
            collateral_decimals=response.collateral_token_decimals,
            loan_price_usd=loan_price_usd,
            collateral_price_usd=collateral_price_usd,
        )
        row = _build_replay_snapshot_row(
            position=position,
            response=response,
            tx_hash=tx_hash,
            operation_type=operation_type,
            brief=brief,
        )
        snapshot_rows.append(row)
        points.append(_map_replay_row_to_point(row, detail=detail))

    await upsert_position_replay_snapshots(pool, rows=snapshot_rows)
    return MorphoPositionReplayResponse(
        protocol=MORPHO_PROTOCOL,
        market_type=MORPHO_DEFAULT_MARKET_TYPE,
        chain=MORPHO_CHAIN,
        market_id=normalized_market_id,
        address=_normalize_evm_address(address),
        from_time=_record_ts(from_dt),
        to_time=_record_ts(to_dt),
        data_source="rpc",
        total_points=len(points),
        total_tx_count=len(grouped),
        cache_hit_rate="0.00",
        points=points,
    )
