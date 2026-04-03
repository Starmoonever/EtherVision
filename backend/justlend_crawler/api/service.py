"""Service helpers for JustLend scaffold APIs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

import asyncpg
from fastapi import HTTPException

from ..constants import JUSTLEND_CHAIN, JUSTLEND_PROTOCOL
from ..db import fetch_current_user_position, upsert_current_user_position
from .schemas import (
    JustLendMarketResponse,
    JustLendPositionAssetResponse,
    JustLendPositionResponse,
    JustLendScaffoldStatusResponse,
)

logger = logging.getLogger(__name__)
_TRON_MAINNET_PREFIX = b"\x41"
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {char: idx for idx, char in enumerate(_BASE58_ALPHABET)}
_STABLE_SYMBOLS = ("USDT", "USDD", "USDJ", "TUSD", "USDC")


def get_scaffold_status() -> JustLendScaffoldStatusResponse:
    return JustLendScaffoldStatusResponse(
        module=JUSTLEND_PROTOCOL,
        status="scaffold",
        chain=JUSTLEND_CHAIN,
        supported_protocols=["trx"],
        message="JustLend backend scaffold is wired into the unified API. Data collection and query logic are pending.",
    )


def get_markets() -> JustLendMarketResponse:
    return JustLendMarketResponse(chain=JUSTLEND_CHAIN, markets=[])


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _fmt_decimal(value: Decimal, scale: int = 8) -> str:
    return format(value.quantize(Decimal(10) ** -scale), "f")


def _fmt_ratio(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")


def _fmt_health(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000000000000000001")), "f")


def _double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def _tron_address_to_bytes(address: str) -> bytes:
    raw = address.strip()
    if raw.startswith("41") and len(raw) == 42:
        return bytes.fromhex(raw)
    if raw.startswith("0x41") and len(raw) == 44:
        return bytes.fromhex(raw[2:])
    num = 0
    try:
        for char in raw:
            num = num * 58 + _BASE58_INDEX[char]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="invalid TRON address") from exc
    decoded = num.to_bytes((num.bit_length() + 7) // 8, "big")
    pad = len(raw) - len(raw.lstrip("1"))
    decoded = (b"\x00" * pad) + decoded
    if len(decoded) < 5:
        raise HTTPException(status_code=400, detail="invalid TRON address")
    payload, checksum = decoded[:-4], decoded[-4:]
    if _double_sha256(payload)[:4] != checksum:
        raise HTTPException(status_code=400, detail="invalid TRON address checksum")
    if not payload.startswith(_TRON_MAINNET_PREFIX):
        raise HTTPException(status_code=400, detail="unsupported TRON address prefix")
    return payload


def _tron_bytes_to_base58(address: bytes) -> str:
    payload = address
    raw = payload + _double_sha256(payload)[:4]
    num = int.from_bytes(raw, "big")
    chars: list[str] = []
    while num > 0:
        num, rem = divmod(num, 58)
        chars.append(_BASE58_ALPHABET[rem])
    encoded = "".join(reversed(chars)) or "1"
    pad = len(raw) - len(raw.lstrip(b"\x00"))
    return ("1" * pad) + encoded


def _record_ts(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    raise TypeError(f"unsupported timestamp type: {type(value)!r}")


def _format_position(
    position: Any,
    assets: list[Any],
    *,
    data_source: str,
) -> JustLendPositionResponse:
    return JustLendPositionResponse(
        protocol=str(position["protocol"]),
        chain=str(position["chain"]),
        address=_tron_bytes_to_base58(bytes(position["user_address"])),
        snapshot_at=_record_ts(position["snapshot_at"]),
        block_timestamp=_record_ts(position["block_timestamp"]),
        total_collateral_usd=_fmt_decimal(
            Decimal(str(position["total_collateral_usd"]))
        ),
        total_debt_usd=_fmt_decimal(Decimal(str(position["total_debt_usd"]))),
        available_borrow_usd=_fmt_decimal(
            Decimal(str(position["available_borrow_usd"]))
        ),
        health_factor=_fmt_health(Decimal(str(position["health_factor"]))),
        ltv=_fmt_ratio(Decimal(str(position["ltv"]))),
        liquidation_threshold=_fmt_ratio(
            Decimal(str(position["liquidation_threshold"]))
        ),
        data_source=data_source,
        assets=[
            JustLendPositionAssetResponse(
                asset_address=_tron_bytes_to_base58(bytes(asset["asset_address"])),
                symbol=asset["symbol"],
                side=str(asset["side"]),
                amount=_fmt_health(Decimal(str(asset["amount"]))),
                price_usd=_fmt_decimal(Decimal(str(asset["price_usd"]))),
                value_usd=_fmt_decimal(Decimal(str(asset["value_usd"]))),
            )
            for asset in assets
        ],
    )


async def _fetch_json(url: str, timeout: float) -> dict[str, Any]:
    def _load() -> dict[str, Any]:
        with urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        return await asyncio.to_thread(_load)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"failed to fetch JustLend API: {exc}",
        ) from exc


def _infer_trx_price_usd(token_list: list[dict[str, Any]]) -> Decimal:
    for token in token_list:
        symbol = str(token.get("underlyingSymbol", "")).upper()
        price_in_trx = _decimal(token.get("underlyingPriceInTrx", "0"))
        if symbol in _STABLE_SYMBOLS and price_in_trx > 0:
            return Decimal("1") / price_in_trx
    raise HTTPException(
        status_code=502,
        detail="failed to infer TRX/USD price from JustLend market data",
    )


async def fetch_position_from_justlend_api(
    address: str,
    *,
    api_base_url: str,
    timeout: float,
) -> dict[str, Any]:
    market_url = f"{api_base_url.rstrip('/')}/lend/jtoken"
    account_url = f"{api_base_url.rstrip('/')}/lend/account?{urlencode({'addresses': address, 'pageSize': 1, 'pageNo': 1})}"
    market_payload, account_payload = await asyncio.gather(
        _fetch_json(market_url, timeout),
        _fetch_json(account_url, timeout),
    )

    if market_payload.get("code") != 0:
        raise HTTPException(
            status_code=502, detail="JustLend market API returned error"
        )
    if account_payload.get("code") != 0:
        raise HTTPException(
            status_code=502, detail="JustLend account API returned error"
        )

    token_list = list(market_payload.get("data", {}).get("tokenList", []))
    accounts = list(account_payload.get("data", {}).get("list", []))
    if not accounts:
        raise HTTPException(status_code=404, detail="JustLend position not found")

    account = accounts[0]
    market_by_jtoken = {
        str(token.get("address")): token for token in token_list if token.get("address")
    }
    trx_price_usd = _infer_trx_price_usd(token_list)
    total_collateral_usd = (
        _decimal(account.get("totalCollateralValueInTrx", "0")) * trx_price_usd
    )
    total_debt_usd = _decimal(account.get("totalBorrowValueInTrx", "0")) * trx_price_usd
    source_assets = list(account.get("tokens", []))
    if not source_assets and total_collateral_usd == 0 and total_debt_usd == 0:
        raise HTTPException(status_code=404, detail="JustLend position not found")

    assets: list[dict[str, Any]] = []
    discounted_collateral_usd = Decimal("0")
    raw_collateral_trx = Decimal("0")
    raw_debt_trx = Decimal("0")

    for item in source_assets:
        market = market_by_jtoken.get(str(item.get("address")), {})
        price_in_trx = _decimal(market.get("underlyingPriceInTrx", "0"))
        price_usd = price_in_trx * trx_price_usd
        collateral_factor = _decimal(market.get("collateralFactor", "0"))
        underlying_address = str(
            market.get("underlyingAddress")
            or item.get("underlyingAddress")
            or item.get("address")
        )
        symbol = str(
            item.get("underlyingSymbol") or market.get("underlyingSymbol") or ""
        )
        decimals = market.get("underlyingDecimal")

        supply_amount = _decimal(item.get("supplyBalanceUnderlying", "0"))
        if supply_amount > 0:
            value_usd = supply_amount * price_usd
            assets.append(
                {
                    "asset_address": _tron_address_to_bytes(underlying_address),
                    "side": "collateral",
                    "symbol": symbol or None,
                    "decimals": int(decimals) if decimals is not None else None,
                    "amount": supply_amount,
                    "price_usd": price_usd,
                    "value_usd": value_usd,
                    "extra_jsonb": {
                        "entered": item.get("entered"),
                        "jtoken_address": item.get("address"),
                    },
                }
            )
            discounted_collateral_usd += value_usd * collateral_factor
            raw_collateral_trx += supply_amount * price_in_trx

        borrow_amount = _decimal(item.get("borrowBalanceUnderlying", "0"))
        if borrow_amount > 0:
            value_usd = borrow_amount * price_usd
            assets.append(
                {
                    "asset_address": _tron_address_to_bytes(underlying_address),
                    "side": "borrow",
                    "symbol": symbol or None,
                    "decimals": int(decimals) if decimals is not None else None,
                    "amount": borrow_amount,
                    "price_usd": price_usd,
                    "value_usd": value_usd,
                    "extra_jsonb": {
                        "entered": item.get("entered"),
                        "jtoken_address": item.get("address"),
                    },
                }
            )
            raw_debt_trx += borrow_amount * price_in_trx

    liquidation_threshold = (
        discounted_collateral_usd / total_collateral_usd
        if total_collateral_usd > 0
        else Decimal("0")
    )
    available_borrow_usd = max(discounted_collateral_usd - total_debt_usd, Decimal("0"))
    health_factor = _decimal(account.get("health", "0"))
    now = datetime.now(timezone.utc)

    return {
        "user_address": _tron_address_to_bytes(address),
        "chain": JUSTLEND_CHAIN,
        "protocol": "trx",
        "snapshot_at": now,
        "block_timestamp": now,
        "block_number": None,
        "source_cursor": None,
        "total_collateral_usd": total_collateral_usd,
        "total_debt_usd": total_debt_usd,
        "available_borrow_usd": available_borrow_usd,
        "health_factor": health_factor,
        "ltv": liquidation_threshold,
        "liquidation_threshold": liquidation_threshold,
        "extra_jsonb": {
            "source": "justlend_api",
            "source_address": account.get("address")
            or account.get("addresses")
            or address,
            "totalCollateralValueInTrx": str(
                account.get("totalCollateralValueInTrx", "0")
            ),
            "totalBorrowValueInTrx": str(account.get("totalBorrowValueInTrx", "0")),
            "trx_price_usd": str(trx_price_usd),
        },
        "assets": assets,
    }


async def get_user_position(
    pool: asyncpg.Pool,
    cfg: Any,
    address: str,
    protocol: str = "trx",
) -> JustLendPositionResponse:
    if protocol.lower() != "trx":
        raise HTTPException(status_code=400, detail="protocol 仅支持 trx")

    user_address = _tron_address_to_bytes(address)
    position, assets = await fetch_current_user_position(pool, user_address)
    if position is not None:
        return _format_position(position, assets, data_source="database")

    fetched = await fetch_position_from_justlend_api(
        address,
        api_base_url=cfg.justlend.api_base_url,
        timeout=float(cfg.justlend.api_timeout_seconds),
    )
    await upsert_current_user_position(
        pool,
        user_address=fetched["user_address"],
        chain=fetched["chain"],
        protocol=fetched["protocol"],
        snapshot_at=fetched["snapshot_at"],
        block_timestamp=fetched["block_timestamp"],
        block_number=fetched["block_number"],
        source_cursor=fetched["source_cursor"],
        total_collateral_usd=fetched["total_collateral_usd"],
        total_debt_usd=fetched["total_debt_usd"],
        available_borrow_usd=fetched["available_borrow_usd"],
        health_factor=fetched["health_factor"],
        ltv=fetched["ltv"],
        liquidation_threshold=fetched["liquidation_threshold"],
        extra_jsonb=fetched["extra_jsonb"],
        assets=fetched["assets"],
    )
    position, assets = await fetch_current_user_position(pool, user_address)
    if position is None:
        raise HTTPException(
            status_code=500, detail="failed to persist JustLend snapshot"
        )
    return _format_position(position, assets, data_source="api")
