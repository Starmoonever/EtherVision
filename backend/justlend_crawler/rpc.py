"""JustLend RPC business helpers."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from crawler_shared.tron_rpc import TronRpcClient

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {char: idx for idx, char in enumerate(_BASE58_ALPHABET)}
_TRON_MAINNET_PREFIX = b"\x41"
_TRX_ADDRESS_HEX = "41" + "0" * 40
_TRX_DECIMALS = 6
_JTOKEN_DECIMALS = 8
_SCALE_18 = Decimal("1e18")
_MAX_HF = Decimal("1e18")
_STABLE_SYMBOLS = {"USDT", "USDD", "USDJ", "TUSD", "USDC"}
_STABLE_SYMBOL_PRIORITY = ("USDT", "USDC", "USDD", "USDJ", "TUSD")

logger = logging.getLogger(__name__)


def _double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def _tron_address_to_hex(address: str) -> str:
    raw = address.strip()
    if raw.startswith("41") and len(raw) == 42:
        return raw.lower()
    if raw.startswith("0x41") and len(raw) == 44:
        return raw[2:].lower()

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
    return payload.hex()


def _hex_to_tron_base58(address_hex: str) -> str:
    raw = bytes.fromhex(address_hex.lower())
    payload = raw + _double_sha256(raw)[:4]
    num = int.from_bytes(payload, "big")
    chars: list[str] = []
    while num > 0:
        num, rem = divmod(num, 58)
        chars.append(_BASE58_ALPHABET[rem])
    encoded = "".join(reversed(chars)) or "1"
    pad = len(payload) - len(payload.lstrip(b"\x00"))
    return ("1" * pad) + encoded


def _normalize_tron_address(address: str) -> str:
    return _hex_to_tron_base58(_tron_address_to_hex(address))


def _encode_address_word(address: str) -> str:
    return _tron_address_to_hex(_normalize_tron_address(address)).rjust(64, "0")


def _decode_words(raw: str) -> list[str]:
    text = raw.removeprefix("0x")
    if len(text) % 64 != 0:
        raise ValueError("invalid ABI word payload length")
    return [text[index : index + 64] for index in range(0, len(text), 64)]


def _decode_uint256(word: str) -> int:
    return int(word, 16)


def _decode_bool(word: str) -> bool:
    return bool(int(word, 16))


def _decode_address(word: str) -> str:
    return _hex_to_tron_base58("41" + word[-40:])


def _decode_string(raw: str) -> str:
    text = raw.removeprefix("0x")
    offset = int(text[:64], 16) * 2
    length = int(text[offset : offset + 64], 16)
    start = offset + 64
    end = start + length * 2
    return bytes.fromhex(text[start:end]).decode("utf-8")


async def _call_contract_method(
    tron_rpc: TronRpcClient,
    *,
    contract_address: str,
    function_selector: str,
    parameter: str = "",
    owner_address: str | None = None,
    block_number: int | None = None,
) -> str:
    normalized_contract_address = _normalize_tron_address(contract_address)
    normalized_owner_address = _normalize_tron_address(
        owner_address or normalized_contract_address
    )
    payload: dict[str, Any] = {
        "contract_address": _tron_address_to_hex(normalized_contract_address),
        "owner_address": _tron_address_to_hex(normalized_owner_address),
        "function_selector": function_selector,
        "parameter": parameter,
    }
    if block_number is not None:
        payload["block_number"] = block_number
    response = await tron_rpc.post("/wallet/triggerconstantcontract", payload)
    if not response.get("result", {}).get("result"):
        raise HTTPException(
            status_code=502,
            detail=f"TRON RPC call failed: {function_selector}",
        )
    constant_result = response.get("constant_result") or []
    if not constant_result:
        raise HTTPException(
            status_code=502,
            detail=f"TRON RPC returned empty result: {function_selector}",
        )
    raw = str(constant_result[0]).strip()
    if not raw:
        raise HTTPException(
            status_code=502,
            detail=f"TRON RPC returned blank result: {function_selector}",
        )
    return raw


async def _call_uint256(
    tron_rpc: TronRpcClient,
    *,
    contract_address: str,
    function_selector: str,
    parameter: str = "",
    owner_address: str | None = None,
    block_number: int | None = None,
) -> int:
    raw = await _call_contract_method(
        tron_rpc,
        contract_address=contract_address,
        function_selector=function_selector,
        parameter=parameter,
        owner_address=owner_address,
        block_number=block_number,
    )
    try:
        words = _decode_words(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"TRON RPC returned malformed uint256 payload: {function_selector}",
        ) from exc
    if not words:
        raise HTTPException(
            status_code=502,
            detail=f"TRON RPC returned no uint256 words: {function_selector}",
        )
    return _decode_uint256(words[0])


async def _call_address(
    tron_rpc: TronRpcClient,
    *,
    contract_address: str,
    function_selector: str,
    parameter: str = "",
    owner_address: str | None = None,
    block_number: int | None = None,
) -> str:
    raw = await _call_contract_method(
        tron_rpc,
        contract_address=contract_address,
        function_selector=function_selector,
        parameter=parameter,
        owner_address=owner_address,
        block_number=block_number,
    )
    return _decode_address(_decode_words(raw)[0])


async def _call_bool(
    tron_rpc: TronRpcClient,
    *,
    contract_address: str,
    function_selector: str,
    parameter: str = "",
    owner_address: str | None = None,
    block_number: int | None = None,
) -> bool:
    raw = await _call_contract_method(
        tron_rpc,
        contract_address=contract_address,
        function_selector=function_selector,
        parameter=parameter,
        owner_address=owner_address,
        block_number=block_number,
    )
    return _decode_bool(_decode_words(raw)[0])


async def _call_string(
    tron_rpc: TronRpcClient,
    *,
    contract_address: str,
    function_selector: str,
    owner_address: str | None = None,
    block_number: int | None = None,
) -> str:
    raw = await _call_contract_method(
        tron_rpc,
        contract_address=contract_address,
        function_selector=function_selector,
        owner_address=owner_address,
        block_number=block_number,
    )
    return _decode_string(raw)


async def _call_account_snapshot(
    tron_rpc: TronRpcClient,
    *,
    contract_address: str,
    user_address: str,
    block_number: int | None = None,
) -> tuple[int, int, int, int]:
    raw = await _call_contract_method(
        tron_rpc,
        contract_address=contract_address,
        function_selector="getAccountSnapshot(address)",
        parameter=_encode_address_word(user_address),
        owner_address=user_address,
        block_number=block_number,
    )
    words = _decode_words(raw)
    if len(words) < 4:
        raise HTTPException(status_code=502, detail="invalid getAccountSnapshot result")
    return tuple(_decode_uint256(word) for word in words[:4])  # type: ignore[return-value]


async def _call_market_config(
    tron_rpc: TronRpcClient,
    *,
    comptroller_address: str,
    market_address: str,
    block_number: int | None = None,
) -> tuple[bool, Decimal]:
    raw = await _call_contract_method(
        tron_rpc,
        contract_address=comptroller_address,
        function_selector="markets(address)",
        parameter=_encode_address_word(market_address),
        owner_address=comptroller_address,
        block_number=block_number,
    )
    words = _decode_words(raw)
    if len(words) < 2:
        raise HTTPException(status_code=502, detail="invalid markets(address) result")
    return _decode_bool(words[0]), Decimal(_decode_uint256(words[1])) / _SCALE_18


async def _call_token_decimals(
    tron_rpc: TronRpcClient,
    *,
    token_address: str,
    block_number: int | None = None,
) -> int:
    return await _call_uint256(
        tron_rpc,
        contract_address=token_address,
        function_selector="decimals()",
        owner_address=token_address,
        block_number=block_number,
    )


def _decimalize(raw: int, decimals: int) -> Decimal:
    return Decimal(raw) / (Decimal(10) ** decimals)


def _price_in_trx(raw_price: int, underlying_decimals: int) -> Decimal:
    return Decimal(raw_price) / (Decimal(10) ** (33 - underlying_decimals))


def _infer_trx_price_usd_from_positions(
    raw_positions: list[dict[str, Any]],
) -> Decimal | None:
    for stable_symbol in _STABLE_SYMBOL_PRIORITY:
        for item in raw_positions:
            if (
                str(item.get("underlying_symbol") or "").upper() == stable_symbol
                and item["price_in_trx"] > 0
            ):
                return Decimal("1") / item["price_in_trx"]
    for item in raw_positions:
        if (
            str(item.get("underlying_symbol") or "").upper() in _STABLE_SYMBOLS
            and item["price_in_trx"] > 0
        ):
            return Decimal("1") / item["price_in_trx"]
    return None


async def _get_now_block(
    tron_rpc: TronRpcClient,
) -> tuple[int | None, datetime | None]:
    try:
        response = await tron_rpc.post("/wallet/getnowblock", {})
    except Exception:
        logger.debug("failed to fetch TRON latest block", exc_info=True)
        return None, None
    raw_data = response.get("block_header", {}).get("raw_data", {})
    block_number = raw_data.get("number")
    ts_ms = raw_data.get("timestamp")
    try:
        parsed_number = int(block_number) if block_number is not None else None
    except (TypeError, ValueError):
        parsed_number = None
    try:
        parsed_ts = (
            datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
            if ts_ms is not None
            else None
        )
    except (TypeError, ValueError, OSError):
        parsed_ts = None
    return parsed_number, parsed_ts


async def _get_block_by_number(
    tron_rpc: TronRpcClient,
    *,
    block_number: int,
) -> tuple[int | None, datetime | None]:
    try:
        response = await tron_rpc.post("/wallet/getblockbynum", {"num": block_number})
    except Exception:
        logger.debug(
            "failed to fetch TRON block by number=%s", block_number, exc_info=True
        )
        return None, None
    raw_data = response.get("block_header", {}).get("raw_data", {})
    raw_number = raw_data.get("number")
    ts_ms = raw_data.get("timestamp")
    try:
        parsed_number = int(raw_number) if raw_number is not None else None
    except (TypeError, ValueError):
        parsed_number = None
    try:
        parsed_ts = (
            datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
            if ts_ms is not None
            else None
        )
    except (TypeError, ValueError, OSError):
        parsed_ts = None
    return parsed_number, parsed_ts


async def probe_historical_constant_call_support(
    tron_rpc: TronRpcClient,
    *,
    contract_address: str,
) -> bool:
    latest_block, _ = await _get_now_block(tron_rpc)
    if latest_block is None or latest_block < 5:
        return False
    probe_block = latest_block - 5
    try:
        await _call_string(
            tron_rpc,
            contract_address=contract_address,
            function_selector="symbol()",
            owner_address=contract_address,
            block_number=probe_block,
        )
    except Exception:
        return False
    return True


async def find_block_at_or_before_timestamp(
    tron_rpc: TronRpcClient,
    *,
    timestamp: datetime,
) -> tuple[int, datetime]:
    if timestamp.tzinfo is None:
        target_ts = timestamp.replace(tzinfo=timezone.utc)
    else:
        target_ts = timestamp.astimezone(timezone.utc)

    latest_block, latest_ts = await _get_now_block(tron_rpc)
    if latest_block is None or latest_ts is None:
        raise HTTPException(status_code=502, detail="failed to fetch TRON latest block")
    if target_ts > latest_ts:
        return latest_block, latest_ts

    low = 0
    high = latest_block
    best_block = 0
    best_ts = datetime.fromtimestamp(0, tz=timezone.utc)

    while low <= high:
        mid = (low + high) // 2
        mid_block, mid_ts = await _get_block_by_number(tron_rpc, block_number=mid)
        if mid_block is None or mid_ts is None:
            raise HTTPException(
                status_code=502,
                detail=f"failed to fetch TRON block metadata at block={mid}",
            )
        if mid_ts <= target_ts:
            best_block = mid_block
            best_ts = mid_ts
            low = mid + 1
        else:
            high = mid - 1

    return best_block, best_ts


async def _call_optional_uint256(
    tron_rpc: TronRpcClient,
    *,
    contract_address: str,
    function_selector: str,
    parameter: str = "",
    owner_address: str | None = None,
    block_number: int | None = None,
) -> int | None:
    try:
        return await _call_uint256(
            tron_rpc,
            contract_address=contract_address,
            function_selector=function_selector,
            parameter=parameter,
            owner_address=owner_address,
            block_number=block_number,
        )
    except Exception:
        logger.debug(
            "failed optional TRON uint256 call: contract=%s fn=%s",
            contract_address,
            function_selector,
            exc_info=True,
        )
        return None


async def fetch_justlend_market_states_via_rpc(
    tron_rpc: TronRpcClient,
    *,
    market_addresses: list[str],
    block_number: int | None = None,
    snapshot_at: datetime | None = None,
) -> list[dict[str, Any]]:
    normalized_markets = [
        _normalize_tron_address(item) for item in market_addresses if item
    ]
    if not normalized_markets:
        return []

    effective_block_number = block_number
    block_timestamp = snapshot_at
    if effective_block_number is None:
        effective_block_number, block_timestamp = await _get_now_block(tron_rpc)
    elif block_timestamp is None:
        _, block_timestamp = await _get_block_by_number(
            tron_rpc,
            block_number=effective_block_number,
        )
    rows: list[dict[str, Any]] = []
    comptroller_cache: dict[str, dict[str, Any]] = {}

    for market_address in normalized_markets:
        try:
            comptroller_address = await _call_address(
                tron_rpc,
                contract_address=market_address,
                function_selector="comptroller()",
                owner_address=market_address,
                block_number=effective_block_number,
            )
            controller_state = comptroller_cache.get(comptroller_address)
            if controller_state is None:
                oracle_address = await _call_address(
                    tron_rpc,
                    contract_address=comptroller_address,
                    function_selector="oracle()",
                    owner_address=comptroller_address,
                    block_number=effective_block_number,
                )
                controller_state = {"oracle_address": oracle_address}
                comptroller_cache[comptroller_address] = controller_state

            is_listed, collateral_factor = await _call_market_config(
                tron_rpc,
                comptroller_address=comptroller_address,
                market_address=market_address,
                block_number=effective_block_number,
            )
            jtoken_symbol = await _call_string(
                tron_rpc,
                contract_address=market_address,
                function_selector="symbol()",
                owner_address=market_address,
                block_number=effective_block_number,
            )
            jtoken_decimals = await _call_optional_uint256(
                tron_rpc,
                contract_address=market_address,
                function_selector="decimals()",
                owner_address=market_address,
                block_number=effective_block_number,
            )
            try:
                underlying_address = await _call_address(
                    tron_rpc,
                    contract_address=market_address,
                    function_selector="underlying()",
                    owner_address=market_address,
                    block_number=effective_block_number,
                )
                underlying_symbol = await _call_string(
                    tron_rpc,
                    contract_address=underlying_address,
                    function_selector="symbol()",
                    owner_address=market_address,
                    block_number=effective_block_number,
                )
                underlying_decimals = await _call_token_decimals(
                    tron_rpc,
                    token_address=underlying_address,
                    block_number=effective_block_number,
                )
            except HTTPException:
                underlying_address = _hex_to_tron_base58(_TRX_ADDRESS_HEX)
                underlying_symbol = (
                    "TRX" if "TRX" in jtoken_symbol.upper() else jtoken_symbol
                )
                underlying_decimals = _TRX_DECIMALS

            raw_price = await _call_optional_uint256(
                tron_rpc,
                contract_address=controller_state["oracle_address"],
                function_selector="getUnderlyingPrice(address)",
                parameter=_encode_address_word(market_address),
                owner_address=market_address,
                block_number=effective_block_number,
            )
            exchange_rate_raw = await _call_optional_uint256(
                tron_rpc,
                contract_address=market_address,
                function_selector="exchangeRateStored()",
                owner_address=market_address,
                block_number=effective_block_number,
            )
            cash_raw = await _call_optional_uint256(
                tron_rpc,
                contract_address=market_address,
                function_selector="getCash()",
                owner_address=market_address,
                block_number=effective_block_number,
            )
            total_borrows_raw = await _call_optional_uint256(
                tron_rpc,
                contract_address=market_address,
                function_selector="totalBorrows()",
                owner_address=market_address,
                block_number=effective_block_number,
            )
            total_reserves_raw = await _call_optional_uint256(
                tron_rpc,
                contract_address=market_address,
                function_selector="totalReserves()",
                owner_address=market_address,
                block_number=effective_block_number,
            )
            reserve_factor_raw = await _call_optional_uint256(
                tron_rpc,
                contract_address=market_address,
                function_selector="reserveFactorMantissa()",
                owner_address=market_address,
                block_number=effective_block_number,
            )
            borrow_rate_raw = await _call_optional_uint256(
                tron_rpc,
                contract_address=market_address,
                function_selector="borrowRatePerBlock()",
                owner_address=market_address,
                block_number=effective_block_number,
            )
            supply_rate_raw = await _call_optional_uint256(
                tron_rpc,
                contract_address=market_address,
                function_selector="supplyRatePerBlock()",
                owner_address=market_address,
                block_number=effective_block_number,
            )

            cash = (
                _decimalize(cash_raw, underlying_decimals)
                if cash_raw is not None
                else None
            )
            total_borrows = (
                _decimalize(total_borrows_raw, underlying_decimals)
                if total_borrows_raw is not None
                else None
            )
            total_reserves = (
                _decimalize(total_reserves_raw, underlying_decimals)
                if total_reserves_raw is not None
                else None
            )
            total_supply = None
            if (
                cash is not None
                and total_borrows is not None
                and total_reserves is not None
            ):
                total_supply = cash + total_borrows - total_reserves

            utilization = None
            if (
                cash is not None
                and total_borrows is not None
                and (cash + total_borrows) > 0
            ):
                utilization = total_borrows / (cash + total_borrows)

            rows.append(
                {
                    "market_address": market_address,
                    "comptroller_address": comptroller_address,
                    "oracle_address": controller_state["oracle_address"],
                    "symbol": jtoken_symbol,
                    "underlying_address": underlying_address,
                    "underlying_symbol": underlying_symbol,
                    "underlying_decimals": underlying_decimals,
                    "jtoken_decimals": int(jtoken_decimals)
                    if jtoken_decimals is not None
                    else _JTOKEN_DECIMALS,
                    "is_listed": is_listed,
                    "is_entered_supported": True,
                    "collateral_factor": collateral_factor,
                    "reserve_factor": (
                        Decimal(reserve_factor_raw) / _SCALE_18
                        if reserve_factor_raw is not None
                        else None
                    ),
                    "borrow_cap": None,
                    "supply_cap": None,
                    "exchange_rate": (
                        Decimal(exchange_rate_raw) / _SCALE_18
                        if exchange_rate_raw is not None
                        else None
                    ),
                    "cash": cash,
                    "total_borrows": total_borrows,
                    "total_reserves": total_reserves,
                    "total_supply": total_supply,
                    "utilization": utilization,
                    "borrow_rate": (
                        Decimal(borrow_rate_raw) / _SCALE_18
                        if borrow_rate_raw is not None
                        else None
                    ),
                    "supply_rate": (
                        Decimal(supply_rate_raw) / _SCALE_18
                        if supply_rate_raw is not None
                        else None
                    ),
                    "underlying_price_in_trx": (
                        _price_in_trx(raw_price, underlying_decimals)
                        if raw_price is not None
                        else None
                    ),
                    "block_number": effective_block_number,
                    "block_timestamp": block_timestamp,
                }
            )
        except Exception:
            logger.warning(
                "failed to fetch JustLend market state via RPC: market=%s",
                market_address,
                exc_info=True,
            )
            continue

    return rows


async def fetch_justlend_position_via_rpc(
    tron_rpc: TronRpcClient,
    *,
    address: str,
    protocol: str = "trx",
    market_addresses: list[str] | None = None,
) -> dict[str, Any]:
    if protocol.lower() != "trx":
        raise HTTPException(status_code=400, detail="protocol 仅支持 trx")
    normalized_address = _normalize_tron_address(address)
    markets = [
        _normalize_tron_address(item) for item in (market_addresses or []) if item
    ]
    if not markets:
        raise NotImplementedError("JustLend RPC fetch requires configured markets")

    user_address_hex = _tron_address_to_hex(normalized_address)
    comptroller_cache: dict[str, dict[str, Any]] = {}
    oracle_price_cache: dict[tuple[str, str], int] = {}
    token_meta_cache: dict[str, dict[str, Any]] = {}

    raw_positions: list[dict[str, Any]] = []
    for market_address in markets:
        (
            error_code,
            jtoken_balance_raw,
            borrow_balance_raw,
            exchange_rate_raw,
        ) = await _call_account_snapshot(
            tron_rpc,
            contract_address=market_address,
            user_address=normalized_address,
        )
        if error_code != 0:
            raise HTTPException(
                status_code=502,
                detail=f"JustLend RPC getAccountSnapshot failed for {market_address}",
            )
        if jtoken_balance_raw == 0 and borrow_balance_raw == 0:
            continue

        comptroller_address = await _call_address(
            tron_rpc,
            contract_address=market_address,
            function_selector="comptroller()",
            owner_address=normalized_address,
        )
        controller_state = comptroller_cache.get(comptroller_address)
        if controller_state is None:
            oracle_address = await _call_address(
                tron_rpc,
                contract_address=comptroller_address,
                function_selector="oracle()",
                owner_address=normalized_address,
            )
            controller_state = {
                "oracle_address": oracle_address,
            }
            comptroller_cache[comptroller_address] = controller_state

        entered, collateral_factor = await _call_market_config(
            tron_rpc,
            comptroller_address=comptroller_address,
            market_address=market_address,
        )
        price_cache_key = (controller_state["oracle_address"], market_address)
        raw_price = oracle_price_cache.get(price_cache_key)
        if raw_price is None:
            raw_price = await _call_uint256(
                tron_rpc,
                contract_address=controller_state["oracle_address"],
                function_selector="getUnderlyingPrice(address)",
                parameter=_encode_address_word(market_address),
                owner_address=normalized_address,
            )
            oracle_price_cache[price_cache_key] = raw_price

        token_meta = token_meta_cache.get(market_address)
        if token_meta is None:
            jtoken_symbol = await _call_string(
                tron_rpc,
                contract_address=market_address,
                function_selector="symbol()",
                owner_address=normalized_address,
            )
            try:
                underlying_address = await _call_address(
                    tron_rpc,
                    contract_address=market_address,
                    function_selector="underlying()",
                    owner_address=normalized_address,
                )
                underlying_symbol = await _call_string(
                    tron_rpc,
                    contract_address=underlying_address,
                    function_selector="symbol()",
                    owner_address=normalized_address,
                )
                underlying_decimals = await _call_token_decimals(
                    tron_rpc,
                    token_address=underlying_address,
                )
            except HTTPException:
                underlying_address = _hex_to_tron_base58(_TRX_ADDRESS_HEX)
                underlying_symbol = (
                    "TRX" if "TRX" in jtoken_symbol.upper() else jtoken_symbol
                )
                underlying_decimals = _TRX_DECIMALS

            token_meta = {
                "jtoken_symbol": jtoken_symbol,
                "underlying_address": underlying_address,
                "underlying_symbol": underlying_symbol,
                "underlying_decimals": underlying_decimals,
            }
            token_meta_cache[market_address] = token_meta

        supply_amount = (
            Decimal(jtoken_balance_raw) * Decimal(exchange_rate_raw) / _SCALE_18
        ) / (Decimal(10) ** _JTOKEN_DECIMALS)
        borrow_amount = _decimalize(
            borrow_balance_raw, int(token_meta["underlying_decimals"])
        )
        price_trx = _price_in_trx(raw_price, int(token_meta["underlying_decimals"]))

        raw_positions.append(
            {
                "market_address": market_address,
                "entered": entered,
                "collateral_factor": collateral_factor,
                "price_in_trx": price_trx,
                "supply_amount": supply_amount,
                "borrow_amount": borrow_amount,
                "underlying_address": token_meta["underlying_address"],
                "underlying_symbol": token_meta["underlying_symbol"],
                "underlying_decimals": int(token_meta["underlying_decimals"]),
            }
        )

    if not raw_positions:
        raise HTTPException(status_code=404, detail="JustLend position not found")

    trx_price_usd = _infer_trx_price_usd_from_positions(raw_positions)
    if trx_price_usd is None:
        raise HTTPException(
            status_code=502,
            detail="failed to infer TRX/USD price from JustLend RPC market data",
        )

    assets: list[dict[str, Any]] = []
    total_collateral_usd = Decimal("0")
    total_debt_usd = Decimal("0")
    discounted_collateral_usd = Decimal("0")
    for item in raw_positions:
        price_usd = item["price_in_trx"] * trx_price_usd
        if item["supply_amount"] > 0:
            value_usd = item["supply_amount"] * price_usd
            is_collateral = bool(item["entered"])
            if is_collateral:
                total_collateral_usd += value_usd
                discounted_collateral_usd += value_usd * item["collateral_factor"]
            assets.append(
                {
                    "asset_address": bytes.fromhex(
                        _tron_address_to_hex(str(item["underlying_address"]))
                    ),
                    "side": "collateral" if is_collateral else "supply",
                    "symbol": item["underlying_symbol"],
                    "decimals": item["underlying_decimals"],
                    "amount": item["supply_amount"],
                    "price_usd": price_usd,
                    "value_usd": value_usd,
                    "extra_jsonb": {
                        "entered": item["entered"],
                        "jtoken_address": str(item["market_address"]),
                        "collateral_factor": str(item["collateral_factor"]),
                        "price_in_trx": str(item["price_in_trx"]),
                    },
                }
            )
        if item["borrow_amount"] > 0:
            value_usd = item["borrow_amount"] * price_usd
            total_debt_usd += value_usd
            assets.append(
                {
                    "asset_address": bytes.fromhex(
                        _tron_address_to_hex(str(item["underlying_address"]))
                    ),
                    "side": "borrow",
                    "symbol": item["underlying_symbol"],
                    "decimals": item["underlying_decimals"],
                    "amount": item["borrow_amount"],
                    "price_usd": price_usd,
                    "value_usd": value_usd,
                    "extra_jsonb": {
                        "entered": item["entered"],
                        "jtoken_address": str(item["market_address"]),
                        "price_in_trx": str(item["price_in_trx"]),
                    },
                }
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
        "user_address": bytes.fromhex(user_address_hex),
        "chain": "tron",
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
            "source": "justlend_rpc",
            "source_address": normalized_address,
            "trx_price_usd": str(trx_price_usd),
            "market_count": len(raw_positions),
        },
        "assets": assets,
    }


async def fetch_market_exchange_rates(
    tron_rpc: TronRpcClient,
    *,
    market_addresses: list[str],
) -> dict[str, Decimal]:
    rates: dict[str, Decimal] = {}
    for market_address in market_addresses:
        normalized_market_address = _normalize_tron_address(market_address)
        market_hex = _tron_address_to_hex(normalized_market_address)
        try:
            exchange_rate_raw = await _call_uint256(
                tron_rpc,
                contract_address=normalized_market_address,
                function_selector="exchangeRateStored()",
                owner_address=normalized_market_address,
            )
        except HTTPException:
            logger.debug(
                "failed to fetch JustLend exchange rate for market=%s",
                normalized_market_address,
            )
            continue
        except Exception:
            logger.debug(
                "failed to fetch JustLend exchange rate for market=%s",
                normalized_market_address,
                exc_info=True,
            )
            continue
        rates[market_hex] = Decimal(exchange_rate_raw)
    return rates
