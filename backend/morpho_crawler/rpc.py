"""Realtime Morpho Blue RPC helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal, cast

from eth_abi.abi import decode
from eth_typing import ChecksumAddress
from fastapi import HTTPException
from web3 import AsyncWeb3
from web3.types import BlockData, BlockIdentifier, FilterParams

from .constants import MORPHO_BLUE_ADDRESS

WAD = 10**18
ORACLE_PRICE_SCALE = 10**36
VIRTUAL_SHARES = 10**6
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

MORPHO_ABI: list[dict[str, Any]] = [
    {
        "inputs": [{"internalType": "bytes32", "name": "id", "type": "bytes32"}],
        "name": "idToMarketParams",
        "outputs": [
            {"internalType": "address", "name": "loanToken", "type": "address"},
            {
                "internalType": "address",
                "name": "collateralToken",
                "type": "address",
            },
            {"internalType": "address", "name": "oracle", "type": "address"},
            {"internalType": "address", "name": "irm", "type": "address"},
            {"internalType": "uint256", "name": "lltv", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "id", "type": "bytes32"}],
        "name": "market",
        "outputs": [
            {
                "components": [
                    {
                        "internalType": "uint128",
                        "name": "totalSupplyAssets",
                        "type": "uint128",
                    },
                    {
                        "internalType": "uint128",
                        "name": "totalSupplyShares",
                        "type": "uint128",
                    },
                    {
                        "internalType": "uint128",
                        "name": "totalBorrowAssets",
                        "type": "uint128",
                    },
                    {
                        "internalType": "uint128",
                        "name": "totalBorrowShares",
                        "type": "uint128",
                    },
                    {
                        "internalType": "uint128",
                        "name": "lastUpdate",
                        "type": "uint128",
                    },
                    {"internalType": "uint128", "name": "fee", "type": "uint128"},
                ],
                "internalType": "struct Market",
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "id", "type": "bytes32"},
            {"internalType": "address", "name": "user", "type": "address"},
        ],
        "name": "position",
        "outputs": [
            {
                "components": [
                    {
                        "internalType": "uint256",
                        "name": "supplyShares",
                        "type": "uint256",
                    },
                    {
                        "internalType": "uint128",
                        "name": "borrowShares",
                        "type": "uint128",
                    },
                    {
                        "internalType": "uint128",
                        "name": "collateral",
                        "type": "uint128",
                    },
                ],
                "internalType": "struct Position",
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

ORACLE_ABI: list[dict[str, Any]] = [
    {
        "inputs": [],
        "name": "price",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]

IRM_ABI: list[dict[str, Any]] = [
    {
        "inputs": [
            {
                "components": [
                    {
                        "internalType": "address",
                        "name": "loanToken",
                        "type": "address",
                    },
                    {
                        "internalType": "address",
                        "name": "collateralToken",
                        "type": "address",
                    },
                    {"internalType": "address", "name": "oracle", "type": "address"},
                    {"internalType": "address", "name": "irm", "type": "address"},
                    {"internalType": "uint256", "name": "lltv", "type": "uint256"},
                ],
                "internalType": "struct MarketParams",
                "name": "marketParams",
                "type": "tuple",
            },
            {
                "components": [
                    {
                        "internalType": "uint128",
                        "name": "totalSupplyAssets",
                        "type": "uint128",
                    },
                    {
                        "internalType": "uint128",
                        "name": "totalSupplyShares",
                        "type": "uint128",
                    },
                    {
                        "internalType": "uint128",
                        "name": "totalBorrowAssets",
                        "type": "uint128",
                    },
                    {
                        "internalType": "uint128",
                        "name": "totalBorrowShares",
                        "type": "uint128",
                    },
                    {
                        "internalType": "uint128",
                        "name": "lastUpdate",
                        "type": "uint128",
                    },
                    {"internalType": "uint128", "name": "fee", "type": "uint128"},
                ],
                "internalType": "struct Market",
                "name": "market",
                "type": "tuple",
            },
        ],
        "name": "borrowRateView",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]

ERC20_ABI: list[dict[str, Any]] = [
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]

MORPHO_REPLAY_EVENT_TYPES: dict[str, list[str]] = {
    "supply": ["uint256", "uint256"],
    "withdraw": ["address", "uint256", "uint256"],
    "borrow": ["address", "uint256", "uint256"],
    "repay": ["uint256", "uint256"],
    "supply_collateral": ["uint256"],
    "withdraw_collateral": ["address", "uint256"],
    "liquidation": ["uint256", "uint256", "uint256", "uint256", "uint256"],
}

MORPHO_REPLAY_EVENT_SIGNATURES: dict[str, str] = {
    "supply": "Supply(bytes32,address,address,uint256,uint256)",
    "withdraw": "Withdraw(bytes32,address,address,address,uint256,uint256)",
    "borrow": "Borrow(bytes32,address,address,address,uint256,uint256)",
    "repay": "Repay(bytes32,address,address,uint256,uint256)",
    "supply_collateral": "SupplyCollateral(bytes32,address,address,uint256)",
    "withdraw_collateral": "WithdrawCollateral(bytes32,address,address,address,uint256)",
    "liquidation": "Liquidate(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)",
}


@dataclass
class TokenMetadata:
    address: str
    symbol: str | None
    decimals: int


@dataclass
class MorphoRealtimePosition:
    morpho_address: str
    market_id: str
    user_address: str
    block_number: int
    block_timestamp: datetime
    loan_token: TokenMetadata
    collateral_token: TokenMetadata
    oracle: str
    irm: str
    lltv: int
    supply_shares: int
    borrow_shares: int
    collateral_raw: int
    supply_assets_raw: int
    borrow_assets_raw: int
    collateral_value_in_loan_asset_raw: int
    max_borrowable_raw: int
    health_factor: Decimal | None
    is_healthy: bool
    has_position: bool
    price_raw: int


@dataclass
class MorphoReplayEvent:
    tx_hash: str
    log_index: int
    block_number: int
    block_timestamp: datetime
    operation_type: str
    assets: int | None = None
    shares: int | None = None
    collateral_assets: int | None = None
    repaid_assets: int | None = None
    seized_assets: int | None = None


def _normalize_address(address: str) -> ChecksumAddress:
    try:
        return AsyncWeb3.to_checksum_address(address)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid EVM address") from exc


def _normalize_market_id(market_id: str) -> bytes:
    normalized = market_id.strip().lower()
    if normalized.startswith("0x"):
        normalized = normalized[2:]
    if len(normalized) != 64:
        raise HTTPException(status_code=400, detail="invalid market_id length")
    try:
        return bytes.fromhex(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid market_id") from exc


def _to_checksum(address: str) -> ChecksumAddress:
    return AsyncWeb3.to_checksum_address(address)


def _mul_div_down(x: int, y: int, d: int) -> int:
    return (x * y) // d


def _mul_div_up(x: int, y: int, d: int) -> int:
    return (x * y + (d - 1)) // d


def _w_taylor_compounded(x: int, n: int) -> int:
    first_term = x * n
    second_term = _mul_div_down(first_term, first_term, 2 * WAD)
    third_term = _mul_div_down(second_term, first_term, 3 * WAD)
    return first_term + second_term + third_term


def _to_assets_down(shares: int, total_assets: int, total_shares: int) -> int:
    return _mul_div_down(shares, total_assets + 1, total_shares + VIRTUAL_SHARES)


def _to_assets_up(shares: int, total_assets: int, total_shares: int) -> int:
    return _mul_div_up(shares, total_assets + 1, total_shares + VIRTUAL_SHARES)


def _to_shares_down(assets: int, total_assets: int, total_shares: int) -> int:
    return _mul_div_down(assets, total_shares + VIRTUAL_SHARES, total_assets + 1)


def _format_scaled(amount: int, decimals: int) -> str:
    return format(Decimal(amount) / (Decimal(10) ** decimals), "f")


# api/morpho/market/state相关：供 fetch_market_state 格式化比率类字段
def _format_decimal_fixed(value: Decimal, places: int) -> str:
    quant = Decimal(10) ** (-places)
    return format(value.quantize(quant), "f")


async def _fetch_token_metadata(w3: AsyncWeb3, token_address: str) -> TokenMetadata:
    token_address_checksum = _to_checksum(token_address)
    token = w3.eth.contract(address=token_address_checksum, abi=ERC20_ABI)
    try:
        decimals, symbol = await asyncio.gather(
            token.functions.decimals().call(),
            token.functions.symbol().call(),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"failed to fetch token metadata: {token_address}",
        ) from exc
    return TokenMetadata(
        address=token_address_checksum, symbol=symbol, decimals=int(decimals)
    )


# api/morpho/market/state相关：GET /api/morpho/market/state 链上读取与载荷拼装
async def fetch_market_state(
    w3: AsyncWeb3,
    *,
    market_id: str,
    block_identifier: BlockIdentifier = cast(BlockIdentifier, "latest"),
) -> dict[str, Any]:
    morpho_address = _to_checksum(MORPHO_BLUE_ADDRESS)
    morpho = w3.eth.contract(address=morpho_address, abi=MORPHO_ABI)
    market_id_bytes = _normalize_market_id(market_id)
    market_id_hex = f"0x{market_id_bytes.hex()}"

    try:
        market_params, market_data = await asyncio.gather(
            morpho.functions.idToMarketParams(market_id_bytes).call(
                block_identifier=block_identifier
            ),
            morpho.functions.market(market_id_bytes).call(
                block_identifier=block_identifier
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="failed to fetch Morpho market state",
        ) from exc

    loan_token_address = _to_checksum(market_params[0])
    collateral_token_address = _to_checksum(market_params[1])
    oracle_address = _to_checksum(market_params[2])
    irm_address = _to_checksum(market_params[3])
    lltv_raw = int(market_params[4])
    if loan_token_address == ZERO_ADDRESS or collateral_token_address == ZERO_ADDRESS:
        raise HTTPException(status_code=404, detail="morpho market not found")

    loan_token, collateral_token = await asyncio.gather(
        _fetch_token_metadata(w3, loan_token_address),
        _fetch_token_metadata(w3, collateral_token_address),
    )

    total_supply_assets = int(market_data[0])
    total_supply_shares = int(market_data[1])
    total_borrow_assets = int(market_data[2])
    total_borrow_shares = int(market_data[3])
    last_update = int(market_data[4])
    fee = int(market_data[5])

    supply_dec = Decimal(total_supply_assets)
    borrow_dec = Decimal(total_borrow_assets)
    lltv_ratio = Decimal(lltv_raw) / Decimal(WAD)

    utilization = Decimal("0")
    if total_supply_assets > 0:
        utilization = borrow_dec / supply_dec
    available_liquidity = total_supply_assets - total_borrow_assets

    borrow_capacity_usage_rough = Decimal("0")
    if total_supply_assets > 0 and lltv_ratio > 0:
        borrow_capacity_usage_rough = borrow_dec / (supply_dec * lltv_ratio)

    return {
        "marketId": market_id_hex,
        "loanToken": {
            "address": loan_token.address,
            "symbol": loan_token.symbol,
            "decimals": loan_token.decimals,
        },
        "collateralToken": {
            "address": collateral_token.address,
            "symbol": collateral_token.symbol,
            "decimals": collateral_token.decimals,
        },
        "oracle": oracle_address,
        "irm": irm_address,
        "lltv": {
            "raw": str(lltv_raw),
            "ratio": _format_decimal_fixed(lltv_ratio, 6),
        },
        "totalSupplyAssets": str(total_supply_assets),
        "totalSupplyShares": str(total_supply_shares),
        "totalBorrowAssets": str(total_borrow_assets),
        "totalBorrowShares": str(total_borrow_shares),
        "lastUpdate": last_update,
        "fee": str(fee),
        "utilization": {
            "formula": "totalBorrowAssets / totalSupplyAssets",
            "value": _format_decimal_fixed(utilization, 8),
        },
        "availableLiquidity": {
            "formula": "totalSupplyAssets - totalBorrowAssets",
            "value": str(available_liquidity),
            "note": None,
        },
        "borrowCapacityUsageRough": {
            "formula": "totalBorrowAssets / (totalSupplyAssets * lltv)",
            "value": _format_decimal_fixed(borrow_capacity_usage_rough, 8),
            "note": "市场层粗略估算，严格口径需用户仓位级数据",
        },
        "marketScaleTvlLike": {
            "formula": "totalSupplyAssets",
            "value": str(total_supply_assets),
            "note": None,
        },
        "debtScaleDebtLike": {
            "formula": "totalBorrowAssets",
            "value": str(total_borrow_assets),
            "note": None,
        },
    }


async def fetch_realtime_position(
    w3: AsyncWeb3,
    *,
    address: str,
    market_id: str,
) -> MorphoRealtimePosition:
    return await fetch_position_at_block(
        w3,
        address=address,
        market_id=market_id,
        block_identifier=cast(BlockIdentifier, "latest"),
    )


async def fetch_position_at_block(
    w3: AsyncWeb3,
    *,
    address: str,
    market_id: str,
    block_identifier: BlockIdentifier,
) -> MorphoRealtimePosition:
    morpho_address = _to_checksum(MORPHO_BLUE_ADDRESS)
    morpho = w3.eth.contract(address=morpho_address, abi=MORPHO_ABI)
    user_address = _normalize_address(address)
    market_id_bytes = _normalize_market_id(market_id)
    market_id_hex = f"0x{market_id_bytes.hex()}"

    latest_block = await w3.eth.get_block(block_identifier)
    block_number = _require_block_number(latest_block)
    raw_block_timestamp = _require_block_timestamp(latest_block)
    block_timestamp = datetime.fromtimestamp(
        int(raw_block_timestamp),
        tz=timezone.utc,
    )

    try:
        market_params, market_data, position_data = await asyncio.gather(
            morpho.functions.idToMarketParams(market_id_bytes).call(
                block_identifier=block_number
            ),
            morpho.functions.market(market_id_bytes).call(
                block_identifier=block_number
            ),
            morpho.functions.position(market_id_bytes, user_address).call(
                block_identifier=block_number
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="failed to fetch Morpho market or position",
        ) from exc

    loan_token_address = _to_checksum(market_params[0])
    collateral_token_address = _to_checksum(market_params[1])
    oracle_address = _to_checksum(market_params[2])
    irm_address = _to_checksum(market_params[3])
    lltv = int(market_params[4])
    if loan_token_address == ZERO_ADDRESS or collateral_token_address == ZERO_ADDRESS:
        raise HTTPException(status_code=404, detail="morpho market not found")

    loan_token, collateral_token = await asyncio.gather(
        _fetch_token_metadata(w3, loan_token_address),
        _fetch_token_metadata(w3, collateral_token_address),
    )

    total_supply_assets = int(market_data[0])
    total_supply_shares = int(market_data[1])
    total_borrow_assets = int(market_data[2])
    total_borrow_shares = int(market_data[3])
    last_update = int(market_data[4])
    fee = int(market_data[5])

    supply_shares = int(position_data[0])
    borrow_shares = int(position_data[1])
    collateral_raw = int(position_data[2])

    oracle = w3.eth.contract(address=_to_checksum(oracle_address), abi=ORACLE_ABI)
    try:
        price_raw = int(
            await oracle.functions.price().call(block_identifier=block_number)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="failed to fetch Morpho oracle price"
        ) from exc

    if (
        total_borrow_assets > 0
        and irm_address != ZERO_ADDRESS
        and block_timestamp.timestamp() > last_update
    ):
        irm = w3.eth.contract(address=_to_checksum(irm_address), abi=IRM_ABI)
        market_params_tuple = (
            loan_token_address,
            collateral_token_address,
            oracle_address,
            irm_address,
            lltv,
        )
        market_tuple = (
            total_supply_assets,
            total_supply_shares,
            total_borrow_assets,
            total_borrow_shares,
            last_update,
            fee,
        )
        try:
            borrow_rate = int(
                await irm.functions.borrowRateView(
                    market_params_tuple,
                    market_tuple,
                ).call(block_identifier=block_number)
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail="failed to fetch Morpho borrow rate"
            ) from exc

        elapsed = int(block_timestamp.timestamp()) - last_update
        if elapsed > 0 and borrow_rate > 0:
            interest = _mul_div_down(
                total_borrow_assets,
                _w_taylor_compounded(borrow_rate, elapsed),
                WAD,
            )
            total_borrow_assets += interest
            total_supply_assets += interest
            if fee > 0:
                fee_amount = _mul_div_down(interest, fee, WAD)
                fee_shares = _to_shares_down(
                    fee_amount,
                    total_supply_assets - fee_amount,
                    total_supply_shares,
                )
                total_supply_shares += fee_shares

    supply_assets_raw = _to_assets_down(
        supply_shares,
        total_supply_assets,
        total_supply_shares,
    )
    borrow_assets_raw = _to_assets_up(
        borrow_shares,
        total_borrow_assets,
        total_borrow_shares,
    )

    collateral_value_in_loan_asset_raw = _mul_div_down(
        collateral_raw,
        price_raw,
        ORACLE_PRICE_SCALE,
    )
    max_borrowable_raw = _mul_div_down(
        collateral_value_in_loan_asset_raw,
        lltv,
        WAD,
    )
    health_factor = None
    if borrow_assets_raw > 0:
        health_factor = Decimal(max_borrowable_raw) / Decimal(borrow_assets_raw)
    is_healthy = borrow_assets_raw == 0 or max_borrowable_raw >= borrow_assets_raw
    has_position = (supply_shares + borrow_shares + collateral_raw) > 0

    return MorphoRealtimePosition(
        morpho_address=_to_checksum(MORPHO_BLUE_ADDRESS),
        market_id=market_id_hex,
        user_address=user_address,
        block_number=block_number,
        block_timestamp=block_timestamp,
        loan_token=loan_token,
        collateral_token=collateral_token,
        oracle=oracle_address,
        irm=irm_address,
        lltv=lltv,
        supply_shares=supply_shares,
        borrow_shares=borrow_shares,
        collateral_raw=collateral_raw,
        supply_assets_raw=supply_assets_raw,
        borrow_assets_raw=borrow_assets_raw,
        collateral_value_in_loan_asset_raw=collateral_value_in_loan_asset_raw,
        max_borrowable_raw=max_borrowable_raw,
        health_factor=health_factor,
        is_healthy=is_healthy,
        has_position=has_position,
        price_raw=price_raw,
    )


def _pad_topic_address(address: str) -> str:
    return "0x" + "0" * 24 + _normalize_address(address)[2:].lower()


def _decode_log_data(log_data: Any, data_types: list[str]) -> tuple[Any, ...]:
    if isinstance(log_data, str):
        payload = bytes.fromhex(log_data.removeprefix("0x"))
    else:
        payload = bytes(log_data)
    return decode(data_types, payload)


def _require_block_number(block: BlockData) -> int:
    value = block.get("number")
    if value is None:
        raise HTTPException(status_code=502, detail="failed to fetch block number")
    return int(value)


def _require_block_timestamp(block: BlockData) -> int:
    value = block.get("timestamp")
    if value is None:
        raise HTTPException(status_code=502, detail="failed to fetch block timestamp")
    return int(value)


async def _resolve_block_from_timestamp(
    w3: AsyncWeb3,
    *,
    timestamp: int,
    latest_block_number: int,
    latest_block_ts: int,
    mode: Literal["ge", "le"],
) -> int:
    if timestamp <= 0:
        return 0
    earliest_block = await w3.eth.get_block(0)
    earliest_ts = _require_block_timestamp(earliest_block)
    if timestamp <= earliest_ts:
        return 0
    if timestamp >= latest_block_ts:
        return latest_block_number

    lo = 0
    hi = latest_block_number
    answer = latest_block_number if mode == "ge" else 0
    while lo <= hi:
        mid = (lo + hi) // 2
        mid_block = await w3.eth.get_block(mid)
        mid_ts = _require_block_timestamp(mid_block)
        if mode == "ge":
            if mid_ts >= timestamp:
                answer = mid
                hi = mid - 1
            else:
                lo = mid + 1
        else:
            if mid_ts <= timestamp:
                answer = mid
                lo = mid + 1
            else:
                hi = mid - 1
    return answer


async def fetch_user_market_replay_events(
    w3: AsyncWeb3,
    *,
    address: str,
    market_id: str,
    from_ts: int,
    to_ts: int,
) -> list[MorphoReplayEvent]:
    latest_block = await w3.eth.get_block(cast(BlockIdentifier, "latest"))
    latest_block_number = _require_block_number(latest_block)
    latest_block_ts = _require_block_timestamp(latest_block)
    from_block = await _resolve_block_from_timestamp(
        w3,
        timestamp=from_ts,
        latest_block_number=latest_block_number,
        latest_block_ts=latest_block_ts,
        mode="ge",
    )
    to_block = await _resolve_block_from_timestamp(
        w3,
        timestamp=to_ts,
        latest_block_number=latest_block_number,
        latest_block_ts=latest_block_ts,
        mode="le",
    )
    if from_block > to_block:
        return []

    topic_zero = [
        AsyncWeb3.to_hex(AsyncWeb3.keccak(text=signature))
        for signature in MORPHO_REPLAY_EVENT_SIGNATURES.values()
    ]
    user_topic = _pad_topic_address(address)
    market_topic = f"0x{_normalize_market_id(market_id).hex()}"
    filter_params = cast(
        FilterParams,
        {
            "address": _to_checksum(MORPHO_BLUE_ADDRESS),
            "fromBlock": from_block,
            "toBlock": to_block,
            "topics": [topic_zero, market_topic, None, user_topic],
        },
    )
    raw_logs = await w3.eth.get_logs(filter_params)
    if not raw_logs:
        return []

    signature_map = {
        AsyncWeb3.to_hex(AsyncWeb3.keccak(text=signature)): operation_type
        for operation_type, signature in MORPHO_REPLAY_EVENT_SIGNATURES.items()
    }
    block_ts_cache: dict[int, datetime] = {}
    rows: list[MorphoReplayEvent] = []
    for raw_log in raw_logs:
        topic0 = AsyncWeb3.to_hex(raw_log["topics"][0])
        operation_type = signature_map.get(topic0)
        if operation_type is None:
            continue
        block_number = int(raw_log["blockNumber"])
        if block_number not in block_ts_cache:
            block = await w3.eth.get_block(block_number)
            block_ts_cache[block_number] = datetime.fromtimestamp(
                _require_block_timestamp(block), tz=timezone.utc
            )
        decoded = _decode_log_data(
            raw_log["data"], MORPHO_REPLAY_EVENT_TYPES[operation_type]
        )
        row = MorphoReplayEvent(
            tx_hash=raw_log["transactionHash"].hex(),
            log_index=int(raw_log["logIndex"]),
            block_number=block_number,
            block_timestamp=block_ts_cache[block_number],
            operation_type=operation_type,
        )
        if operation_type in {"supply", "withdraw", "borrow"}:
            row.assets = int(decoded[-2])
            row.shares = int(decoded[-1])
        elif operation_type == "repay":
            row.assets = int(decoded[0])
            row.shares = int(decoded[1])
        elif operation_type in {"supply_collateral", "withdraw_collateral"}:
            row.collateral_assets = int(decoded[-1])
        elif operation_type == "liquidation":
            row.repaid_assets = int(decoded[0])
            row.shares = int(decoded[1])
            row.seized_assets = int(decoded[2])
        rows.append(row)
    rows.sort(key=lambda item: (item.block_number, item.log_index, item.tx_hash))
    return rows
