"""Service helpers for JustLend scaffold APIs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

import asyncpg
from fastapi import HTTPException

from crawler_shared.tron_rpc import TronRpcClient
from ..constants import JUSTLEND_CHAIN, JUSTLEND_PROTOCOL
from ..db import (
    append_user_position_snapshot,
    fetch_current_user_position,
    JustLendEventPositionSnapshotRow,
    fetch_justlend_tx_effects,
    get_justlend_event_snapshots,
    fetch_justlend_user_tx_history,
    upsert_justlend_event_snapshots,
    upsert_current_user_position,
)
from ..rpc import fetch_market_exchange_rates
from .schemas import (
    JustLendMarketResponse,
    JustLendPositionAssetResponse,
    JustLendPositionResponse,
    JustLendPositionReplayPoint,
    JustLendPositionReplayResponse,
    JustLendScaffoldStatusResponse,
)

logger = logging.getLogger(__name__)
_TRON_MAINNET_PREFIX = b"\x41"
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {char: idx for idx, char in enumerate(_BASE58_ALPHABET)}
_STABLE_SYMBOLS = ("USDT", "USDD", "USDJ", "TUSD", "USDC")
_MAX_HF = Decimal("1e18")
_SUMMARY_TOLERANCE_USD = Decimal("0.01")
_JUSTLEND_REPLAY_METHOD_IDS = {
    "a0712d68",  # mint
    "db006a75",  # redeem
    "852a12e3",  # redeemUnderlying
    "c5ebeaec",  # borrow
    "0e752702",  # repayBorrow
    "2608f818",  # repayBorrowBehalf
    "f5e3c462",  # liquidateBorrow
}
_JUSTLEND_SELF_IMPACT_METHOD_IDS = {
    "a0712d68",
    "db006a75",
    "852a12e3",
    "c5ebeaec",
    "0e752702",
}
_JUSTLEND_METHOD_BRIEF_MAP = {
    "a0712d68": "存入",
    "db006a75": "赎回",
    "852a12e3": "提取",
    "c5ebeaec": "借入",
    "0e752702": "还款",
    "2608f818": "代还",
    "f5e3c462": "清算",
}
_TRON_CONTRACT_TYPE_NAMES = {
    31: "TriggerSmartContract",
}


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


async def get_supported_tron_price_assets(cfg: Any) -> list[dict[str, str]]:
    market_url = f"{cfg.justlend.api_base_url.rstrip('/')}/lend/jtoken"
    market_payload = await _fetch_json(
        market_url, float(cfg.justlend.api_timeout_seconds)
    )
    if market_payload.get("code") != 0:
        raise HTTPException(
            status_code=502, detail="JustLend market API returned error"
        )

    token_list = list(market_payload.get("data", {}).get("tokenList", []))
    seen: set[tuple[str, str]] = set()
    assets: list[dict[str, str]] = []
    for token in token_list:
        asset_address = str(token.get("underlyingAddress") or "").strip()
        symbol = str(token.get("underlyingSymbol") or "").strip().upper()
        if not asset_address or not symbol:
            continue
        key = (symbol, asset_address)
        if key in seen:
            continue
        seen.add(key)
        assets.append(
            {
                "asset": symbol,
                "token_address": asset_address,
                "chain": JUSTLEND_CHAIN,
            }
        )
    assets.sort(key=lambda item: (item["asset"], item["token_address"]))
    return assets


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _fmt_decimal(value: Decimal, scale: int = 8) -> str:
    return format(value.quantize(Decimal(10) ** -scale), "f")


def _fmt_ratio(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")


def _fmt_health(value: Decimal) -> str:
    if value >= _MAX_HF:
        return format(value, "f")
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
    try:
        text = address.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    if text.startswith("T"):
        return text
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


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if hasattr(row, key):
        return getattr(row, key)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _normalize_tx_hash(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value).hex()
    else:
        raw = str(value).strip().lower()
        if raw.startswith("\\x"):
            raw = raw[2:]
    if not raw:
        return None
    return raw


def _normalize_method_id(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    if len(raw) >= 8:
        return raw[:8]
    return None


def _position_method(method_id: str | None) -> bool:
    return method_id in _JUSTLEND_REPLAY_METHOD_IDS


def _is_replay_self_impact_method(method_id: str | None) -> bool:
    return method_id in _JUSTLEND_SELF_IMPACT_METHOD_IDS


def _supports_replay_contract_type(value: Any) -> bool:
    if value is None:
        return True
    try:
        contract_type = int(value)
    except (TypeError, ValueError):
        return False
    return contract_type in _TRON_CONTRACT_TYPE_NAMES


def _extract_market_address_from_contract(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    contract_address = payload.get("contract_address")
    if contract_address is None:
        return None
    try:
        return _tron_bytes_to_base58(_tron_address_to_bytes(str(contract_address)))
    except HTTPException:
        return str(contract_address)


def _extract_market_address_from_parse_input(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    asset = payload.get("asset")
    if asset is None:
        return None
    try:
        return _tron_bytes_to_base58(_tron_address_to_bytes(str(asset)))
    except HTTPException:
        return None


def _fallback_replay_brief(method_id: str | None, market: str | None) -> str:
    action = _JUSTLEND_METHOD_BRIEF_MAP.get(method_id or "", "更新仓位")
    if market:
        return f"{action} {market} 仓位"
    return action


def _method_to_operation_type(method_id: str | None) -> str | None:
    mapping = {
        "a0712d68": "deposit",
        "db006a75": "redeem",
        "852a12e3": "withdraw",
        "c5ebeaec": "borrow",
        "0e752702": "repay",
        "2608f818": "repay_behalf",
        "f5e3c462": "liquidation",
    }
    return mapping.get(method_id or "")


def _extract_amount_and_symbol(text: str) -> tuple[str | None, str | None]:
    cleaned = " ".join(text.split())
    match = re.search(
        r"([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z][A-Za-z0-9._-]{1,15})",
        cleaned,
    )
    if match is None:
        return None, None
    return match.group(1), match.group(2)


def _build_tx_brief(
    *,
    method_id: str | None,
    market: str | None,
    parse_summary: str,
    parse_input: str,
) -> str:
    for raw_text in (parse_summary, parse_input):
        text = raw_text.strip()
        if text:
            amount, symbol = _extract_amount_and_symbol(text)
            action = _JUSTLEND_METHOD_BRIEF_MAP.get(method_id or "", "更新")
            if amount and symbol:
                return f"{action} {amount} {symbol}"
            return text
    return _fallback_replay_brief(method_id, market)


def _format_brief_amount(amount: Decimal) -> str:
    text = format(amount.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


async def _fetch_justlend_market_catalog(
    cfg: Any,
    *,
    tron_rpc: TronRpcClient | None,
    market_addresses: list[str],
) -> dict[str, dict[str, Any]]:
    market_url = f"{cfg.justlend.api_base_url.rstrip('/')}/lend/jtoken"
    market_payload = await _fetch_json(
        market_url, float(cfg.justlend.api_timeout_seconds)
    )
    if market_payload.get("code") != 0:
        raise HTTPException(
            status_code=502, detail="JustLend market API returned error"
        )
    token_list = list(market_payload.get("data", {}).get("tokenList", []))
    trx_price_usd = _infer_trx_price_usd(token_list)
    exchange_rate_map: dict[str, Decimal] = {}
    if tron_rpc is not None and market_addresses:
        try:
            exchange_rate_map = await fetch_market_exchange_rates(
                tron_rpc,
                market_addresses=market_addresses,
            )
        except Exception:
            logger.warning(
                "failed to fetch JustLend exchange rates via RPC", exc_info=True
            )

    catalog: dict[str, dict[str, Any]] = {}
    for token in token_list:
        market_address = str(token.get("address") or "").strip()
        if not market_address:
            continue
        market_bytes = _tron_address_to_bytes(market_address)
        market_hex = market_bytes.hex()
        underlying_address = str(
            token.get("underlyingAddress") or token.get("address") or ""
        ).strip()
        underlying_hex: str | None = None
        if underlying_address:
            try:
                underlying_hex = _tron_address_to_bytes(underlying_address).hex()
            except HTTPException:
                underlying_hex = None
        price_in_trx = _decimal(token.get("underlyingPriceInTrx", "0"))
        entry = {
            "market_address": market_address,
            "market_hex": market_hex,
            "underlying_address": underlying_address,
            "underlying_hex": underlying_hex,
            "underlying_symbol": str(token.get("underlyingSymbol") or "").strip()
            or None,
            "underlying_decimals": int(token.get("underlyingDecimal") or 6),
            "collateral_factor": _decimal(token.get("collateralFactor", "0")),
            "price_in_trx": price_in_trx,
            "price_usd": price_in_trx * trx_price_usd,
            "exchange_rate": exchange_rate_map.get(market_hex),
        }
        catalog[market_hex] = entry
        if underlying_hex and underlying_hex not in catalog:
            catalog[underlying_hex] = entry
    return catalog


def _normalize_replay_txs(tx_rows: list[Any]) -> list[dict[str, Any]]:
    txs: list[dict[str, Any]] = []
    for row in tx_rows:
        tx_hash = _normalize_tx_hash(_row_get(row, "tx_hash"))
        method_id = _normalize_method_id(_row_get(row, "method_id"))
        if (
            tx_hash is None
            or not _position_method(method_id)
            or not _supports_replay_contract_type(_row_get(row, "contract_type"))
        ):
            continue
        block_timestamp = _row_get(row, "block_timestamp")
        if not isinstance(block_timestamp, datetime):
            continue
        if block_timestamp.tzinfo is None:
            block_timestamp = block_timestamp.replace(tzinfo=timezone.utc)
        else:
            block_timestamp = block_timestamp.astimezone(timezone.utc)
        txs.append(
            {
                "tx_hash": tx_hash,
                "method_id": method_id,
                "block_number": int(_row_get(row, "block_number") or 0),
                "block_timestamp": block_timestamp,
                "parse_summary": str(_row_get(row, "parse_summary") or "").strip(),
                "parse_input": str(_row_get(row, "parse_input") or "").strip(),
            }
        )
        txs[-1]["market"] = _extract_market_address_from_contract(
            _row_get(row, "contract")
        ) or _extract_market_address_from_parse_input(txs[-1]["parse_input"])
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tx in txs:
        key = tx["tx_hash"]
        if key in seen:
            continue
        seen.add(key)
        if _is_replay_self_impact_method(tx.get("method_id")):
            deduped.append(tx)
    return deduped


def _parse_tx_delta(
    tx: dict[str, Any],
    market_catalog: dict[str, dict[str, Any]],
) -> tuple[str | None, Decimal, str | None, dict[str, Any] | None]:
    tx_effect = tx.get("_effect") if isinstance(tx.get("_effect"), dict) else None
    if tx_effect is not None:
        market_address = tx_effect.get("market_address")
        underlying_address = tx_effect.get("underlying_address")
        meta = None
        for candidate in (market_address, underlying_address):
            if isinstance(candidate, (bytes, bytearray, memoryview)):
                candidate_value = _tron_bytes_to_base58(bytes(candidate))
            else:
                candidate_value = str(candidate or "").strip()
            if not candidate_value:
                continue
            try:
                candidate_hex = _tron_address_to_bytes(candidate_value).hex()
            except HTTPException:
                continue
            meta = market_catalog.get(candidate_hex)
            if meta is not None:
                return (
                    str(meta["market_hex"]),
                    Decimal(str(tx_effect.get("amount_decimal") or "0")),
                    str(tx_effect.get("operation_type") or "")
                    or _method_to_operation_type(tx.get("method_id")),
                    meta,
                )
        if market_address is not None:
            market_value = (
                _tron_bytes_to_base58(bytes(market_address))
                if isinstance(market_address, (bytes, bytearray, memoryview))
                else str(market_address)
            )
            try:
                market_hex = _tron_address_to_bytes(market_value).hex()
            except HTTPException:
                market_hex = None
        else:
            market_hex = None
        return (
            market_hex,
            Decimal(str(tx_effect.get("amount_decimal") or "0")),
            str(tx_effect.get("operation_type") or "")
            or _method_to_operation_type(tx.get("method_id")),
            None,
        )

    parse_input = tx.get("parse_input") or ""
    if not parse_input:
        return None, Decimal("0"), None, None
    try:
        payload = json.loads(parse_input)
    except json.JSONDecodeError:
        return None, Decimal("0"), None, None
    asset = str(payload.get("asset") or "").strip()
    if not asset:
        return None, Decimal("0"), None, None
    try:
        market_hex = _tron_address_to_bytes(asset).hex()
    except HTTPException:
        return None, Decimal("0"), None, None
    meta = market_catalog.get(market_hex)
    operation_type = _method_to_operation_type(tx.get("method_id"))
    if meta is None:
        return market_hex, Decimal("0"), operation_type, None
    amount_raw = Decimal(str(payload.get("amount") or "0"))
    canonical_market_hex = str(meta["market_hex"])
    if operation_type == "redeem" and not bool(payload.get("redeemUnderlying")):
        exchange_rate = meta.get("exchange_rate")
        if exchange_rate is None:
            amount = Decimal("0")
        else:
            amount = (amount_raw * Decimal(exchange_rate) / Decimal("1e18")) / Decimal(
                "1e8"
            )
    else:
        amount = amount_raw / (Decimal(10) ** int(meta["underlying_decimals"]))
    return canonical_market_hex, amount, operation_type, meta


def _build_tx_brief_from_delta(
    *,
    tx: dict[str, Any],
    amount: Decimal,
    meta: dict[str, Any] | None,
) -> str:
    symbol = str((meta or {}).get("underlying_symbol") or "").strip()
    if amount > 0 and symbol:
        action = _JUSTLEND_METHOD_BRIEF_MAP.get(str(tx.get("method_id") or ""), "更新")
        return f"{action} {_format_brief_amount(amount)} {symbol}"
    return _build_tx_brief(
        method_id=tx.get("method_id"),
        market=tx.get("market"),
        parse_summary=tx.get("parse_summary") or "",
        parse_input=tx.get("parse_input") or "",
    )


def _build_event_snapshot_row(
    *,
    user_address: bytes,
    tx: dict[str, Any],
    balances: dict[str, dict[str, Decimal]],
    market_catalog: dict[str, dict[str, Any]],
) -> JustLendEventPositionSnapshotRow:
    assets_jsonb: list[dict[str, Any]] = []
    total_collateral_usd = Decimal("0")
    total_debt_usd = Decimal("0")
    discounted_collateral_usd = Decimal("0")
    symbol: str | None = None
    market_bytes: bytes | None = None
    tx_meta = tx.get("_meta") if isinstance(tx.get("_meta"), dict) else None
    tx_market_address = (
        str(tx_meta.get("market_address"))
        if tx_meta and tx_meta.get("market_address")
        else str(tx.get("market") or "")
    )
    if tx_market_address:
        try:
            market_bytes = _tron_address_to_bytes(tx_market_address)
        except HTTPException:
            market_bytes = None
    if tx_meta:
        symbol = tx_meta.get("underlying_symbol")
    for market_hex, position in balances.items():
        meta = market_catalog.get(market_hex)
        if meta is None:
            continue
        price_usd = Decimal(str(meta["price_usd"]))
        collateral_factor = Decimal(str(meta["collateral_factor"]))
        supply_amount = max(position["supply"], Decimal("0"))
        borrow_amount = max(position["borrow"], Decimal("0"))
        if supply_amount > 0:
            value_usd = supply_amount * price_usd
            total_collateral_usd += value_usd
            discounted_collateral_usd += value_usd * collateral_factor
            assets_jsonb.append(
                {
                    "asset_address": str(meta["underlying_address"]),
                    "symbol": meta["underlying_symbol"],
                    "side": "collateral",
                    "amount": str(supply_amount),
                    "price_usd": str(price_usd),
                    "value_usd": str(value_usd),
                }
            )
        if borrow_amount > 0:
            value_usd = borrow_amount * price_usd
            total_debt_usd += value_usd
            assets_jsonb.append(
                {
                    "asset_address": str(meta["underlying_address"]),
                    "symbol": meta["underlying_symbol"],
                    "side": "borrow",
                    "amount": str(borrow_amount),
                    "price_usd": str(price_usd),
                    "value_usd": str(value_usd),
                }
            )
        if symbol is None and tx_market_address:
            try:
                if market_hex == _tron_address_to_bytes(tx_market_address).hex():
                    symbol = meta["underlying_symbol"]
            except HTTPException:
                pass
    brief = str(tx.get("_brief") or "").strip() or _build_tx_brief(
        method_id=tx.get("method_id"),
        market=tx.get("market"),
        parse_summary=tx.get("parse_summary") or "",
        parse_input=tx.get("parse_input") or "",
    )
    liquidation_buffer_usd = discounted_collateral_usd - total_debt_usd
    available_borrow_usd = max(liquidation_buffer_usd, Decimal("0"))
    ltv = (
        total_debt_usd / total_collateral_usd
        if total_collateral_usd > 0
        else Decimal("0")
    )
    liquidation_threshold = (
        discounted_collateral_usd / total_collateral_usd
        if total_collateral_usd > 0
        else Decimal("0")
    )
    health_factor = (
        discounted_collateral_usd / total_debt_usd
        if total_debt_usd > 0
        else (_MAX_HF if total_collateral_usd > 0 else Decimal("0"))
    )
    return JustLendEventPositionSnapshotRow(
        user_address=user_address,
        chain=JUSTLEND_CHAIN,
        protocol="trx",
        tx_hash=str(tx["tx_hash"]),
        block_number=int(tx["block_number"]),
        block_timestamp=tx["block_timestamp"],
        market=market_bytes,
        symbol=symbol,
        method_id=tx.get("method_id"),
        operation_type=_method_to_operation_type(tx.get("method_id")),
        has_open_position=(total_collateral_usd > 0 or total_debt_usd > 0),
        is_liquidatable=(total_debt_usd > 0 and health_factor < Decimal("1")),
        total_collateral_usd=total_collateral_usd,
        total_debt_usd=total_debt_usd,
        available_borrow_usd=available_borrow_usd,
        discounted_collateral_usd=discounted_collateral_usd,
        liquidation_buffer_usd=liquidation_buffer_usd,
        health_factor=health_factor,
        ltv=ltv,
        liquidation_threshold=liquidation_threshold,
        assets_jsonb=assets_jsonb,
        extra_jsonb={
            "source": "event_replay_approx",
            "market_count": len(balances),
        },
        brief=brief,
    )


async def _collect_and_cache_replay_misses(
    pool: asyncpg.Pool,
    *,
    cfg: Any,
    tron_rpc: TronRpcClient | None,
    user_address: bytes,
    to_dt: datetime,
    persist_cache: bool = True,
) -> list[JustLendEventPositionSnapshotRow]:
    full_history_rows = await fetch_justlend_user_tx_history(
        pool,
        user_address=user_address,
        from_dt=datetime(1970, 1, 1, tzinfo=timezone.utc),
        to_dt=to_dt,
        only_success=True,
    )
    full_txs = _normalize_replay_txs(full_history_rows)
    if not full_txs:
        return []
    tx_effects = await fetch_justlend_tx_effects(
        pool,
        tx_hashes=[str(tx["tx_hash"]) for tx in full_txs],
    )
    for tx in full_txs:
        tx["_effect"] = tx_effects.get(str(tx["tx_hash"]))
    market_addresses = {str(tx["market"]) for tx in full_txs if tx.get("market")}
    for effect in tx_effects.values():
        for key in ("market_address", "underlying_address"):
            raw = effect.get(key)
            if isinstance(raw, (bytes, bytearray, memoryview)):
                market_addresses.add(_tron_bytes_to_base58(bytes(raw)))
            elif raw:
                market_addresses.add(str(raw))
    market_catalog = await _fetch_justlend_market_catalog(
        cfg,
        tron_rpc=tron_rpc,
        market_addresses=sorted(market_addresses),
    )
    balances: dict[str, dict[str, Decimal]] = {}
    rows: list[JustLendEventPositionSnapshotRow] = []
    for tx in full_txs:
        market_hex, amount, operation_type, meta = _parse_tx_delta(tx, market_catalog)
        tx["_meta"] = meta
        tx["_brief"] = _build_tx_brief_from_delta(tx=tx, amount=amount, meta=meta)
        if market_hex is not None:
            position = balances.setdefault(
                market_hex,
                {"supply": Decimal("0"), "borrow": Decimal("0")},
            )
            if operation_type == "deposit":
                position["supply"] += amount
            elif operation_type in {"withdraw", "redeem"}:
                position["supply"] = max(position["supply"] - amount, Decimal("0"))
            elif operation_type == "borrow":
                position["borrow"] += amount
            elif operation_type in {"repay", "repay_behalf"}:
                position["borrow"] = max(position["borrow"] - amount, Decimal("0"))
        rows.append(
            _build_event_snapshot_row(
                user_address=user_address,
                tx=tx,
                balances=balances,
                market_catalog=market_catalog,
            )
        )
    if persist_cache and rows:
        await upsert_justlend_event_snapshots(pool, rows)
    return rows


def _sum_asset_values(assets: list[Any], side: str) -> Decimal:
    total = Decimal("0")
    for asset in assets:
        if str(asset["side"]) != side:
            continue
        total += Decimal(str(asset["value_usd"]))
    return total


def _cached_position_requires_refresh(position: Any, assets: list[Any]) -> bool:
    if position is None or not assets:
        return False
    total_collateral_usd = Decimal(str(position["total_collateral_usd"]))
    total_debt_usd = Decimal(str(position["total_debt_usd"]))
    asset_collateral_usd = _sum_asset_values(assets, "collateral")
    asset_debt_usd = _sum_asset_values(assets, "borrow")
    return (
        abs(total_collateral_usd - asset_collateral_usd) > _SUMMARY_TOLERANCE_USD
        or abs(total_debt_usd - asset_debt_usd) > _SUMMARY_TOLERANCE_USD
    )


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


def _format_assets(assets: list[Any]) -> list[JustLendPositionAssetResponse]:
    return [
        JustLendPositionAssetResponse(
            asset_address=_tron_bytes_to_base58(bytes(asset["asset_address"])),
            symbol=asset["symbol"],
            side=str(asset["side"]),
            amount=_fmt_health(Decimal(str(asset["amount"]))),
            price_usd=_fmt_decimal(Decimal(str(asset["price_usd"]))),
            value_usd=_fmt_decimal(Decimal(str(asset["value_usd"]))),
        )
        for asset in assets
    ]


def _map_position_asset(asset: Any) -> JustLendPositionAssetResponse:
    asset_address = asset.get("asset_address")
    if isinstance(asset_address, str):
        asset_address_str = asset_address
    elif isinstance(asset_address, (bytes, bytearray, memoryview)):
        asset_address_str = _tron_bytes_to_base58(bytes(asset_address))
    else:
        asset_address_str = str(asset_address or "")
    return JustLendPositionAssetResponse(
        asset_address=asset_address_str,
        symbol=asset.get("symbol"),
        side=str(asset.get("side") or ""),
        amount=_fmt_health(Decimal(str(asset.get("amount") or "0"))),
        price_usd=_fmt_decimal(Decimal(str(asset.get("price_usd") or "0"))),
        value_usd=_fmt_decimal(Decimal(str(asset.get("value_usd") or "0"))),
    )


def _build_replay_brief(snapshot: Any) -> str:
    collateral = _fmt_decimal(Decimal(str(snapshot["total_collateral_usd"])))
    debt = _fmt_decimal(Decimal(str(snapshot["total_debt_usd"])))
    health = _fmt_health(Decimal(str(snapshot["health_factor"])))
    return f"collateral=${collateral}, debt=${debt}, hf={health}"


async def _persist_position_snapshot(
    pool: asyncpg.Pool,
    payload: dict[str, Any],
) -> None:
    await upsert_current_user_position(
        pool,
        user_address=payload["user_address"],
        chain=payload["chain"],
        protocol=payload["protocol"],
        snapshot_at=payload["snapshot_at"],
        block_timestamp=payload["block_timestamp"],
        block_number=payload["block_number"],
        source_cursor=payload["source_cursor"],
        total_collateral_usd=payload["total_collateral_usd"],
        total_debt_usd=payload["total_debt_usd"],
        available_borrow_usd=payload["available_borrow_usd"],
        health_factor=payload["health_factor"],
        ltv=payload["ltv"],
        liquidation_threshold=payload["liquidation_threshold"],
        extra_jsonb=payload["extra_jsonb"],
        assets=payload["assets"],
    )
    await append_user_position_snapshot(
        pool,
        user_address=payload["user_address"],
        chain=payload["chain"],
        protocol=payload["protocol"],
        snapshot_at=payload["snapshot_at"],
        block_timestamp=payload["block_timestamp"],
        block_number=payload["block_number"],
        source_cursor=payload["source_cursor"],
        total_collateral_usd=payload["total_collateral_usd"],
        total_debt_usd=payload["total_debt_usd"],
        available_borrow_usd=payload["available_borrow_usd"],
        health_factor=payload["health_factor"],
        ltv=payload["ltv"],
        liquidation_threshold=payload["liquidation_threshold"],
        extra_jsonb=payload["extra_jsonb"],
        assets=payload["assets"],
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
                        "collateral_factor": str(collateral_factor),
                    },
                }
            )
            discounted_collateral_usd += value_usd * collateral_factor

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
    total_collateral_usd = sum(
        (
            Decimal(str(asset["value_usd"]))
            for asset in assets
            if asset["side"] == "collateral"
        ),
        Decimal("0"),
    )
    total_debt_usd = sum(
        (
            Decimal(str(asset["value_usd"]))
            for asset in assets
            if asset["side"] == "borrow"
        ),
        Decimal("0"),
    )

    liquidation_threshold = (
        discounted_collateral_usd / total_collateral_usd
        if total_collateral_usd > 0
        else Decimal("0")
    )
    ltv = (
        total_debt_usd / total_collateral_usd
        if total_collateral_usd > 0
        else Decimal("0")
    )
    available_borrow_usd = max(discounted_collateral_usd - total_debt_usd, Decimal("0"))
    health_factor = (
        discounted_collateral_usd / total_debt_usd
        if total_debt_usd > 0
        else (_MAX_HF if total_collateral_usd > 0 else Decimal("0"))
    )
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
        "ltv": ltv,
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
    if position is not None and not _cached_position_requires_refresh(position, assets):
        return _format_position(position, assets, data_source="database")

    fetched = await fetch_position_from_justlend_api(
        address,
        api_base_url=cfg.justlend.api_base_url,
        timeout=float(cfg.justlend.api_timeout_seconds),
    )
    await _persist_position_snapshot(pool, fetched)
    position, assets = await fetch_current_user_position(pool, user_address)
    if position is None:
        raise HTTPException(
            status_code=500, detail="failed to persist JustLend snapshot"
        )
    return _format_position(position, assets, data_source="api")


async def get_position_replay(
    pool: asyncpg.Pool,
    cfg: Any,
    tron_rpc: TronRpcClient | None,
    address: str,
    *,
    protocol: str,
    from_ts: int,
    to_ts: int,
    use_cache: bool = True,
    detail: bool = False,
    persist_cache: bool = True,
) -> JustLendPositionReplayResponse:
    if protocol.lower() != "trx":
        raise HTTPException(status_code=400, detail="protocol 仅支持 trx")

    user_address = _tron_address_to_bytes(address)
    from_dt = datetime.fromtimestamp(from_ts, tz=timezone.utc)
    to_dt = datetime.fromtimestamp(to_ts, tz=timezone.utc)

    tx_rows = await fetch_justlend_user_tx_history(
        pool,
        user_address=user_address,
        from_dt=from_dt,
        to_dt=to_dt,
        only_success=True,
    )
    deduped = _normalize_replay_txs(tx_rows)
    if not deduped:
        return JustLendPositionReplayResponse(
            address=_tron_bytes_to_base58(user_address),
            protocol=protocol.lower(),
            from_time=_record_ts(from_dt),
            to_time=_record_ts(to_dt),
            data_source="cache",
            points=[],
            total_points=0,
            total_tx_count=0,
            cache_hit_rate="1.00",
        )

    cached_rows = []
    if use_cache:
        cached_rows = await get_justlend_event_snapshots(
            pool,
            user_address=user_address,
            protocol=protocol.lower(),
            from_ts=from_dt,
            to_ts=to_dt,
            market=None,
        )
    cached_map: dict[tuple[str | None, str], Any] = {}
    for row in cached_rows:
        cached_market = (
            _tron_bytes_to_base58(bytes(_row_get(row, "market")))
            if _row_get(row, "market") is not None
            else None
        )
        cached_tx_hash = _normalize_tx_hash(_row_get(row, "tx_hash"))
        if cached_tx_hash is None:
            continue
        cached_map[(cached_market, cached_tx_hash)] = row

    points: list[JustLendPositionReplayPoint] = []
    misses: list[dict[str, Any]] = []
    for tx in deduped:
        key = (tx["market"], tx["tx_hash"])
        row = cached_map.get(key)
        if row is None and tx["market"] is not None:
            row = cached_map.get((None, tx["tx_hash"]))
        if row is None:
            misses.append(tx)
            continue

        assets = []
        if detail:
            assets = [
                _map_position_asset(item)
                for item in list(_row_get(row, "assets_jsonb") or [])
            ]
        points.append(
            JustLendPositionReplayPoint(
                tx_hash=tx["tx_hash"],
                timestamp=_record_ts(_row_get(row, "block_timestamp")),
                block_number=(
                    int(_row_get(row, "block_number"))
                    if _row_get(row, "block_number") is not None
                    else None
                ),
                market=tx["market"],
                symbol=_row_get(row, "symbol"),
                operation_type=(
                    str(_row_get(row, "operation_type"))
                    if _row_get(row, "operation_type") is not None
                    else _method_to_operation_type(tx.get("method_id"))
                ),
                total_collateral_usd=_fmt_decimal(
                    Decimal(str(_row_get(row, "total_collateral_usd")))
                ),
                total_debt_usd=_fmt_decimal(
                    Decimal(str(_row_get(row, "total_debt_usd")))
                ),
                available_borrow_usd=_fmt_decimal(
                    Decimal(str(_row_get(row, "available_borrow_usd")))
                ),
                discounted_collateral_usd=_fmt_decimal(
                    Decimal(str(_row_get(row, "discounted_collateral_usd")))
                ),
                liquidation_buffer_usd=_fmt_decimal(
                    Decimal(str(_row_get(row, "liquidation_buffer_usd")))
                ),
                health_factor=_fmt_health(Decimal(str(_row_get(row, "health_factor")))),
                ltv=_fmt_ratio(Decimal(str(_row_get(row, "ltv")))),
                liquidation_threshold=_fmt_ratio(
                    Decimal(str(_row_get(row, "liquidation_threshold")))
                ),
                brief=str(_row_get(row, "brief") or "")
                or _build_tx_brief(
                    method_id=tx.get("method_id"),
                    market=tx.get("market"),
                    parse_summary=tx["parse_summary"],
                    parse_input=tx["parse_input"],
                ),
                assets=assets,
            )
        )

    if misses:
        rebuilt_rows = await _collect_and_cache_replay_misses(
            pool,
            cfg=cfg,
            tron_rpc=tron_rpc,
            user_address=user_address,
            to_dt=to_dt,
            persist_cache=persist_cache,
        )
        for row in rebuilt_rows:
            cached_market = (
                _tron_bytes_to_base58(bytes(_row_get(row, "market")))
                if _row_get(row, "market") is not None
                else None
            )
            cached_tx_hash = _normalize_tx_hash(_row_get(row, "tx_hash"))
            if cached_tx_hash is None:
                continue
            cached_map[(cached_market, cached_tx_hash)] = row

        points = []
        unresolved = 0
        for tx in deduped:
            key = (tx["market"], tx["tx_hash"])
            row = cached_map.get(key)
            if row is None and tx["market"] is not None:
                row = cached_map.get((None, tx["tx_hash"]))
            if row is None:
                unresolved += 1
                continue
            assets = []
            if detail:
                assets = [
                    _map_position_asset(item)
                    for item in list(_row_get(row, "assets_jsonb") or [])
                ]
            points.append(
                JustLendPositionReplayPoint(
                    tx_hash=tx["tx_hash"],
                    timestamp=_record_ts(_row_get(row, "block_timestamp")),
                    block_number=(
                        int(_row_get(row, "block_number"))
                        if _row_get(row, "block_number") is not None
                        else None
                    ),
                    market=tx["market"],
                    symbol=_row_get(row, "symbol"),
                    operation_type=(
                        str(_row_get(row, "operation_type"))
                        if _row_get(row, "operation_type") is not None
                        else _method_to_operation_type(tx.get("method_id"))
                    ),
                    total_collateral_usd=_fmt_decimal(
                        Decimal(str(_row_get(row, "total_collateral_usd")))
                    ),
                    total_debt_usd=_fmt_decimal(
                        Decimal(str(_row_get(row, "total_debt_usd")))
                    ),
                    available_borrow_usd=_fmt_decimal(
                        Decimal(str(_row_get(row, "available_borrow_usd")))
                    ),
                    discounted_collateral_usd=_fmt_decimal(
                        Decimal(str(_row_get(row, "discounted_collateral_usd")))
                    ),
                    liquidation_buffer_usd=_fmt_decimal(
                        Decimal(str(_row_get(row, "liquidation_buffer_usd")))
                    ),
                    health_factor=_fmt_health(
                        Decimal(str(_row_get(row, "health_factor")))
                    ),
                    ltv=_fmt_ratio(Decimal(str(_row_get(row, "ltv")))),
                    liquidation_threshold=_fmt_ratio(
                        Decimal(str(_row_get(row, "liquidation_threshold")))
                    ),
                    brief=str(_row_get(row, "brief") or "")
                    or _build_tx_brief(
                        method_id=tx.get("method_id"),
                        market=tx.get("market"),
                        parse_summary=tx["parse_summary"],
                        parse_input=tx["parse_input"],
                    ),
                    assets=assets,
                )
            )
        if unresolved:
            raise HTTPException(
                status_code=501,
                detail=(
                    f"JustLend replay 仍有 {unresolved} 笔交易无法重建，"
                    "请检查交易解析或市场元数据。"
                ),
            )

    data_source = "cache" if not misses else "api"
    if not deduped:
        cache_hit_rate = "1.00"
    elif use_cache and not misses:
        cache_hit_rate = "1.00"
    elif use_cache:
        cache_hit_rate = format(
            Decimal(len(deduped) - len(misses)) / Decimal(len(deduped)),
            ".2f",
        )
    else:
        cache_hit_rate = "0.00"

    return JustLendPositionReplayResponse(
        address=_tron_bytes_to_base58(user_address),
        protocol=protocol.lower(),
        from_time=_record_ts(from_dt),
        to_time=_record_ts(to_dt),
        data_source=data_source,
        points=points,
        total_points=len(points),
        total_tx_count=len(deduped),
        cache_hit_rate=cache_hit_rate,
    )
