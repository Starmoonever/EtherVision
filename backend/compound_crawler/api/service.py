"""Business service layer for Compound API."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from web3 import AsyncWeb3

from ..config import load_config
from ..constants import (
    COMPOUND_V2_MARKET_NAMES,
    COMPOUND_V3_MARKET_NAMES,
    CTOKEN_V2_ABI,
    COMPTROLLER_V2_ABI,
)
from ..crawler import _build_web3, close_web3
from ..db import (
    CompoundCurrentPositionRow,
    CompoundEventPositionSnapshotRow,
    fetch_compound_v3_current_positions,
    fetch_compound_user_tx_history,
    get_compound_event_snapshots,
    market_table_name,
    reserve_table_name,
    upsert_compound_event_snapshots,
)
from ..user_position_snapshots import (
    _collect_user_snapshots_batch,
    _load_market_context,
    collect_market_user_snapshots,
)
from ..crawler import (
    COMET_FACTOR_SCALE,
    ETH_USD_PRICE_FEED,
    WETH_MAINNET,
    _is_contract_deployed_at_block,
    _price_from_feed_direct,
    _token_metadata,
    _v2_underlying_price_usd,
)
from .schemas import (
    CompoundLiquidationSimItem,
    CompoundLiquidationSimResponse,
    CompoundPositionReplayPoint,
    CompoundPositionReplayResponse,
    MarketItemResponse,
    MarketsResponse,
    GovernanceAssetResponse,
    MarketGovernanceResponse,
    MarketGovernancePeriodResponse,
    V2MarketConfigResponse,
    V2MarketConfigPeriodResponse,
    V2ProtocolConfigResponse,
    V2ProtocolConfigPeriodResponse,
    MarketStatePeriodResponse,
    MarketStateReserveResponse,
    MarketStateResponse,
    PositionAssetResponse,
    PositionResponse,
    UserPositionResponse,
)

_SECONDS_PER_YEAR = Decimal("31536000")
_USER_POSITION_TABLES = {
    "v2": "compound_v2_user_position_snapshots",
    "v3": "compound_v3_user_position_snapshots",
}
_GOVERNANCE_TABLE = "compound_v3_market_config_versions"
_GOVERNANCE_ASSET_TABLE = "compound_v3_market_config_assets"
_V2_MARKET_CONFIG_TABLE = "compound_v2_market_config_versions"
_V2_PROTOCOL_CONFIG_TABLE = "compound_v2_protocol_config_versions"
_REPLAY_BATCH_SIZE = 100
_REPLAY_RPC_CONCURRENCY = 8
_MAX_HEALTH_FACTOR = Decimal("1e18")
_ETH_CORRELATED_SYMBOLS = {"ETH", "WETH", "WSTETH", "RETH", "CBETH"}
_COMPOUND_LIQ_SORT_COLS = {
    "liq_price": "liq_price",
    "eth_sensitive_collateral_usd": "eth_sensitive_collateral_usd",
    "total_collateral_usd": "total_collateral_usd",
    "total_debt_usd": "total_debt_usd",
}
_REPLAY_POSITION_METHOD_IDS: dict[str, set[str]] = {
    "v2": {
        "a0712d68",  # mint(uint256)
        "db006a75",  # redeem(uint256)
        "852a12e3",  # redeemUnderlying(uint256)
        "c5ebeaec",  # borrow(uint256)
        "0e752702",  # repayBorrow(uint256)
        "2608f818",  # repayBorrowBehalf(address,uint256)
        "f5e3c462",  # liquidateBorrow(address,uint256,address)
    },
    "v3": {
        "f3fef3a3",
        "c3b35a7e",
        "f2b9fdb8",
        "4232cd63",
        "c3cecfd2",
    },
}
_REPLAY_SELF_IMPACT_METHOD_IDS: dict[str, set[str]] = {
    "v2": {
        "a0712d68",  # mint(uint256)
        "db006a75",  # redeem(uint256)
        "852a12e3",  # redeemUnderlying(uint256)
        "c5ebeaec",  # borrow(uint256)
        "0e752702",  # repayBorrow(uint256)
    },
    "v3": {
        "f3fef3a3",  # supply
        "f2b9fdb8",  # withdraw
    },
}
_CTOKEN_V2_USER_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "borrowBalanceStored",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "borrowBalanceCurrent",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "exchangeRateStored",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "exchangeRateCurrent",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]
_COMPTROLLER_V2_USER_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "getAssetsIn",
        "outputs": [{"internalType": "address[]", "name": "", "type": "address[]"}],
        "stateMutability": "view",
        "type": "function",
    }
]
_COMPTROLLER_V2_MARKETS_LEGACY_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "cToken", "type": "address"}],
        "name": "markets",
        "outputs": [
            {"internalType": "bool", "name": "isListed", "type": "bool"},
            {
                "internalType": "uint256",
                "name": "collateralFactorMantissa",
                "type": "uint256",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    }
]
_REPLAY_METHOD_BRIEF_MAP: dict[str, dict[str, str]] = {
    "v2": {
        "a0712d68": "存入",
        "db006a75": "赎回",
        "852a12e3": "赎回",
        "c5ebeaec": "借入",
        "0e752702": "还款",
        "2608f818": "代还",
        "f5e3c462": "清算",
    },
    "v3": {
        "f3fef3a3": "存入",
        "c3b35a7e": "代存",
        "f2b9fdb8": "提取",
        "4232cd63": "买入抵押品",
        "c3cecfd2": "吸收清算",
    },
}

logger = logging.getLogger(__name__)


def get_markets(version: str) -> MarketsResponse:
    version = version.lower()
    if version not in ("v2", "v3"):
        raise HTTPException(status_code=400, detail="version 仅支持 v2 或 v3")

    addresses = _available_market_addresses(version)
    market_name_map = _market_name_map(version)

    markets = [
        MarketItemResponse(
            address=address,
            symbol=market_name_map.get(address, address),
        )
        for address in addresses
    ]
    markets.sort(key=lambda item: (item.symbol.lower(), item.address.lower()))
    return MarketsResponse(version=version, markets=markets)


def _bytea_to_address(value: bytes | bytearray | memoryview) -> str:
    return "0x" + bytes(value).hex()


def _timestamp_to_utc_string(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def get_market_state_period(
    pool,
    version: str,
    market: str,
    start: str,
    end: str,
    interval: int = 24,
    detail: bool = False,
) -> MarketStatePeriodResponse:
    version = version.lower()
    if version not in ("v2", "v3"):
        raise HTTPException(status_code=400, detail="version 仅支持 v2 或 v3")
    if interval < 1 or interval > 168:
        raise HTTPException(status_code=400, detail="interval 必须为 1~168 小时")

    start_dt = _parse_hour_utc(start)
    end_dt = _parse_hour_utc(end)
    if start_dt > end_dt:
        raise HTTPException(status_code=400, detail="start 必须小于等于 end")

    market_address = _market_to_address(version, market)
    market_bytes = _address_to_bytes(market_address)
    market_table = market_table_name(version)
    reserve_table = reserve_table_name(version)

    points: list[datetime] = []
    cursor = start_dt
    delta = timedelta(hours=interval)
    while cursor <= end_dt:
        points.append(cursor)
        cursor += delta

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                "timestamp",
                market,
                symbol,
                total_supply,
                total_borrow,
                collateral_usd,
                utilization,
                borrow_rate,
                supply_rate,
                price_usd,
                supply_usd,
                borrow_usd
            FROM loan.{market_table}
            WHERE "timestamp" = ANY($1::timestamptz[])
              AND market = $2
            ORDER BY "timestamp"
            """,
            points,
            market_bytes,
        )
        row_map = {
            row["timestamp"].replace(minute=0, second=0, microsecond=0): row
            for row in rows
        }

        reserves_map: dict[datetime, list[MarketStateReserveResponse]] = {}
        if detail:
            price_in_base_select = (
                "price_in_base" if version == "v3" else "NULL::numeric AS price_in_base"
            )
            reserve_rows = await conn.fetch(
                f"""
                SELECT
                    "timestamp",
                    reserve,
                    symbol,
                    decimals,
                    total_supply,
                    total_borrow,
                    utilization,
                    borrow_rate,
                    supply_rate,
                    {price_in_base_select},
                    price_usd,
                    supply_usd,
                    borrow_usd
                FROM loan.{reserve_table}
                WHERE "timestamp" = ANY($1::timestamptz[])
                  AND market = $2
                ORDER BY "timestamp", symbol NULLS LAST, reserve
                """,
                points,
                market_bytes,
            )
            for row in reserve_rows:
                ts = row["timestamp"].replace(minute=0, second=0, microsecond=0)
                reserves_map.setdefault(ts, []).append(_map_market_reserve_row(row))

    result: list[MarketStateResponse] = []
    for ts in points:
        row = row_map.get(ts)
        if row is None:
            continue
        result.append(
            MarketStateResponse(
                version=version,
                market=_bytea_to_address(row["market"]),
                symbol=row["symbol"],
                timestamp=_timestamp_to_utc_string(row["timestamp"]),
                total_supply=_fmt(row["total_supply"]),
                total_borrow=_fmt(row["total_borrow"]),
                collateral_usd=_fmt(row["collateral_usd"]),
                utilization=_fmt(row["utilization"]),
                borrow_apr=_annualize_rate(row["borrow_rate"]),
                supply_apr=_annualize_rate(row["supply_rate"]),
                price_usd=_fmt(row["price_usd"]),
                supply_usd=_fmt(row["supply_usd"]),
                borrow_usd=_fmt(row["borrow_usd"]),
                reserves=reserves_map.get(ts) if detail else None,
            )
        )
    return MarketStatePeriodResponse(points=result)


async def get_positions(
    pool,
    version: str,
    market: str,
    address: str,
    date: str | None = None,
    w3: Any | None = None,
) -> UserPositionResponse:
    version = version.lower()
    if version not in ("v2", "v3"):
        raise HTTPException(status_code=400, detail="version 仅支持 v2 或 v3")

    market_addresses = _markets_to_addresses(version, market)
    market_bytes_list = [_address_to_bytes(item) for item in market_addresses]
    user_address_bytes = _parse_user_address(address)
    position_table = _user_position_table(version)

    if date is None and version == "v3":
        positions: list[PositionResponse] = []
        for market_address in market_addresses:
            collected = await collect_market_user_snapshots(
                load_config(),
                pool,
                market=market_address,
                point_ts=None,
                persist=False,
                user_addresses=[user_address_bytes],
                w3=w3,
            )
            positions.extend(_map_and_sort_positions(collected.snapshots))
        return UserPositionResponse(
            version=version,
            address=_bytea_to_address(user_address_bytes),
            positions=_sort_positions(positions),
        )

    if date is None:
        rows = await _fetch_latest_position_rows(
            pool,
            position_table=position_table,
            market_bytes_list=market_bytes_list,
            user_address=user_address_bytes,
        )
        return UserPositionResponse(
            version=version,
            address=_bytea_to_address(user_address_bytes),
            positions=_map_and_sort_positions(rows),
        )

    point_ts = _parse_midnight_utc(date)
    rows = await _fetch_position_rows(
        pool,
        position_table=position_table,
        point_ts=point_ts,
        market_bytes_list=market_bytes_list,
        user_address=user_address_bytes,
    )
    positions = _map_and_sort_positions(rows)

    if version == "v2":
        return UserPositionResponse(
            version=version,
            address=_bytea_to_address(user_address_bytes),
            positions=_sort_positions(positions),
        )

    existing_markets = {position.market.lower() for position in positions}

    for market_address in market_addresses:
        if market_address.lower() in existing_markets:
            continue
        collected = await collect_market_user_snapshots(
            load_config(),
            pool,
            market=market_address,
            point_ts=point_ts,
            persist=True,
            user_addresses=[user_address_bytes],
            w3=w3,
        )
        positions.extend(_map_and_sort_positions(collected.snapshots))

    return UserPositionResponse(
        version=version,
        address=_bytea_to_address(user_address_bytes),
        positions=_sort_positions(positions),
    )


def _normalize_tx_hash(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return None
        return text if text.startswith("0x") else f"0x{text}"
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if not raw:
            return None
        return "0x" + raw.hex()
    return None


def _normalize_method_id(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return None
        if text.startswith("0x"):
            text = text[2:]
        return text[:8] if len(text) >= 8 else None
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value).hex().lower()
        return raw[:8] if raw else None
    return None


def _normalize_market_bytes(value: Any) -> bytes | None:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        return raw if len(raw) == 20 else None
    if isinstance(value, str):
        text = value.strip().lower()
        if text.startswith("0x") and len(text) == 42:
            try:
                return bytes.fromhex(text[2:])
            except ValueError:
                return None
    return None


def _position_method(protocol: str, method_id: str | None) -> bool:
    if method_id is None:
        return False
    return method_id in _REPLAY_POSITION_METHOD_IDS.get(protocol, set())


def _market_symbol(protocol: str, market: bytes) -> str:
    addr = "0x" + market.hex()
    if protocol == "v2":
        return COMPOUND_V2_MARKET_NAMES.get(addr, addr)
    return COMPOUND_V3_MARKET_NAMES.get(addr, addr)


def _format_compound_brief(
    protocol: str,
    action: str,
    symbol: str,
    *,
    amount: Decimal | None = None,
) -> str:
    base = (
        f"{action} {amount:.6f} {symbol}"
        if amount is not None
        else f"{action} {symbol}"
    )
    if protocol == "v3":
        return f"{base} @{symbol}"
    return base


def _fallback_replay_brief(protocol: str, method_id: str | None, market: bytes) -> str:
    action = _REPLAY_METHOD_BRIEF_MAP.get(protocol, {}).get(method_id or "", "仓位操作")
    return _format_compound_brief(protocol, action, _market_symbol(protocol, market))


def _is_replay_self_impact_method(protocol: str, method_id: str | None) -> bool:
    if method_id is None:
        return False
    return method_id in _REPLAY_SELF_IMPACT_METHOD_IDS.get(protocol, set())


async def _load_v2_accrued_balances(
    ctoken_user: Any,
    *,
    user_checksum: str,
    block_number: int,
) -> tuple[int, int, int]:
    balance_raw = int(
        await ctoken_user.functions.balanceOf(user_checksum).call(
            block_identifier=block_number
        )
    )

    try:
        borrow_raw, exchange_rate_raw = await asyncio.gather(
            ctoken_user.functions.borrowBalanceCurrent(user_checksum).call(
                block_identifier=block_number
            ),
            ctoken_user.functions.exchangeRateCurrent().call(
                block_identifier=block_number
            ),
        )
    except Exception:
        borrow_raw, exchange_rate_raw = await asyncio.gather(
            ctoken_user.functions.borrowBalanceStored(user_checksum).call(
                block_identifier=block_number
            ),
            ctoken_user.functions.exchangeRateStored().call(
                block_identifier=block_number
            ),
        )

    return balance_raw, int(borrow_raw), int(exchange_rate_raw)


async def _load_compound_replay_briefs(
    pool,
    *,
    protocol: str,
    user_address: bytes,
    tx_hashes: list[bytes],
) -> dict[str, str]:
    if not tx_hashes:
        return {}
    version_int = 3 if protocol == "v3" else 2
    brief_map: dict[str, str] = {}
    async with pool.acquire() as conn:
        mint_rows = await conn.fetch(
            """
            SELECT tx_hash, market_address, underlying_amount_decimal, input_amount_decimal
            FROM compound.compound_mint
            WHERE version = $1
              AND tx_hash = ANY($2::bytea[])
              AND minter = $3
            """,
            version_int,
            tx_hashes,
            user_address,
        )
        for row in mint_rows:
            txh = "0x" + bytes(row["tx_hash"]).hex()
            symbol = _market_symbol(protocol, bytes(row["market_address"]))
            amount = row["underlying_amount_decimal"] or row["input_amount_decimal"]
            brief_map[txh] = _format_compound_brief(
                protocol, "存入", symbol, amount=amount
            )

        redeem_rows = await conn.fetch(
            """
            SELECT tx_hash, market_address, underlying_amount_decimal, input_amount_decimal
            FROM compound.compound_redeem
            WHERE version = $1
              AND tx_hash = ANY($2::bytea[])
              AND redeemer = $3
            """,
            version_int,
            tx_hashes,
            user_address,
        )
        for row in redeem_rows:
            txh = "0x" + bytes(row["tx_hash"]).hex()
            symbol = _market_symbol(protocol, bytes(row["market_address"]))
            amount = row["underlying_amount_decimal"] or row["input_amount_decimal"]
            brief_map[txh] = _format_compound_brief(
                protocol, "提取", symbol, amount=amount
            )

        borrow_rows = await conn.fetch(
            """
            SELECT tx_hash, market_address, underlying_amount_decimal, input_amount_decimal
            FROM compound.compound_borrow
            WHERE version = $1
              AND tx_hash = ANY($2::bytea[])
              AND borrower = $3
            """,
            version_int,
            tx_hashes,
            user_address,
        )
        for row in borrow_rows:
            txh = "0x" + bytes(row["tx_hash"]).hex()
            symbol = _market_symbol(protocol, bytes(row["market_address"]))
            amount = row["underlying_amount_decimal"] or row["input_amount_decimal"]
            brief_map[txh] = _format_compound_brief(
                protocol, "借入", symbol, amount=amount
            )

        repay_rows = await conn.fetch(
            """
            SELECT tx_hash, market_address, underlying_amount_decimal, input_amount_decimal
            FROM compound.compound_repay
            WHERE version = $1
              AND tx_hash = ANY($2::bytea[])
              AND (payer = $3 OR borrower = $3)
            """,
            version_int,
            tx_hashes,
            user_address,
        )
        for row in repay_rows:
            txh = "0x" + bytes(row["tx_hash"]).hex()
            symbol = _market_symbol(protocol, bytes(row["market_address"]))
            amount = row["underlying_amount_decimal"] or row["input_amount_decimal"]
            brief_map[txh] = _format_compound_brief(
                protocol, "还款", symbol, amount=amount
            )
    return brief_map


def _chunked[T](items: list[T], size: int) -> list[list[T]]:
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


async def _collect_v2_replay_snapshot_row(
    w3: Any,
    *,
    user_address: bytes,
    event_market: bytes,
    block_number: int,
    point_ts: datetime,
    metadata_cache: dict[str, tuple[str | None, int | None]],
    deployment_cache: dict[str, dict[str, int]] | None = None,
    feed_price_cache: dict[tuple[str, int], Decimal] | None = None,
) -> CompoundEventPositionSnapshotRow:
    user_checksum = AsyncWeb3.to_checksum_address("0x" + user_address.hex())
    event_market_address = "0x" + event_market.hex()
    market_addresses = list(
        dict.fromkeys([event_market_address, *COMPOUND_V2_MARKET_NAMES.keys()])
    )
    active_deployment_cache: dict[str, dict[str, int]] = (
        deployment_cache if deployment_cache is not None else {}
    )
    deployed_markets: list[str] = []
    for market in market_addresses:
        if await _is_contract_deployed_at_block(
            w3,
            market,
            block_number,
            active_deployment_cache,
        ):
            deployed_markets.append(market)

    if not deployed_markets:
        raise RuntimeError(f"no deployed v2 markets at block={block_number}")

    first_ctoken = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(deployed_markets[0]),
        abi=CTOKEN_V2_ABI,
    )
    comptroller_address = await first_ctoken.functions.comptroller().call(
        block_identifier=block_number
    )
    comptroller = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(str(comptroller_address)),
        abi=COMPTROLLER_V2_ABI + _COMPTROLLER_V2_USER_ABI,
    )
    legacy_comptroller = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(str(comptroller_address)),
        abi=_COMPTROLLER_V2_MARKETS_LEGACY_ABI,
    )
    assets_in = await comptroller.functions.getAssetsIn(user_checksum).call(
        block_identifier=block_number
    )
    collateral_markets = {str(addr).lower() for addr in assets_in}
    feed_key = (ETH_USD_PRICE_FEED.lower(), block_number)
    if feed_price_cache is not None and feed_key in feed_price_cache:
        eth_price_usd_from_feed = feed_price_cache[feed_key]
    else:
        eth_price_usd_from_feed = await _price_from_feed_direct(
            w3,
            ETH_USD_PRICE_FEED,
            block_number,
        )
        if feed_price_cache is not None:
            feed_price_cache[feed_key] = eth_price_usd_from_feed

    market_rows: list[dict[str, Any]] = []
    for market in deployed_markets:
        market_checksum = AsyncWeb3.to_checksum_address(market)
        ctoken_user = w3.eth.contract(address=market_checksum, abi=_CTOKEN_V2_USER_ABI)
        ctoken_meta = w3.eth.contract(address=market_checksum, abi=CTOKEN_V2_ABI)
        symbol = COMPOUND_V2_MARKET_NAMES.get(market, market)

        try:
            underlying = await ctoken_meta.functions.underlying().call(
                block_identifier=block_number
            )
            underlying_symbol, underlying_dec_meta = await _token_metadata(
                w3,
                str(underlying),
                block_number,
                metadata_cache,
            )
            underlying_decimals = int(underlying_dec_meta or 18)
            underlying_address = str(underlying)
        except Exception:
            underlying_address = WETH_MAINNET
            underlying_symbol = "ETH"
            underlying_decimals = 18

        try:
            price_usd = await _v2_underlying_price_usd(
                w3,
                ctoken_address=market,
                comptroller_address=str(comptroller_address),
                underlying_decimals=underlying_decimals,
                block_number=block_number,
                eth_price_usd=eth_price_usd_from_feed,
            )
        except Exception:
            if underlying_address.lower() == WETH_MAINNET.lower():
                price_usd = eth_price_usd_from_feed
            else:
                price_usd = Decimal("0")

        balance_raw, borrow_raw, exchange_rate_raw = await _load_v2_accrued_balances(
            ctoken_user,
            user_checksum=user_checksum,
            block_number=block_number,
        )
        try:
            markets_tuple = await comptroller.functions.markets(market_checksum).call(
                block_identifier=block_number
            )
            collateral_factor_raw = int(markets_tuple[1])
        except Exception:
            legacy_tuple = await legacy_comptroller.functions.markets(
                market_checksum
            ).call(block_identifier=block_number)
            collateral_factor_raw = int(legacy_tuple[1])

        underlying_scale = Decimal(10) ** underlying_decimals
        supply_underlying = (
            Decimal(int(balance_raw))
            * Decimal(int(exchange_rate_raw))
            / COMET_FACTOR_SCALE
            / underlying_scale
        )
        borrow_underlying = Decimal(int(borrow_raw)) / underlying_scale
        collateral_factor = Decimal(collateral_factor_raw) / COMET_FACTOR_SCALE
        market_rows.append(
            {
                "market": market.lower(),
                "symbol": symbol,
                "underlying": underlying_address.lower(),
                "underlying_symbol": underlying_symbol or symbol,
                "supply": supply_underlying,
                "borrow": borrow_underlying,
                "price_usd": price_usd,
                "collateral_factor": collateral_factor,
                "is_collateral": market.lower() in collateral_markets,
            }
        )

    eth_price_usd = Decimal("0")
    for row in market_rows:
        if (
            row["underlying_symbol"]
            and str(row["underlying_symbol"]).upper() in _ETH_CORRELATED_SYMBOLS
        ):
            eth_price_usd = row["price_usd"]
            break
    if eth_price_usd <= 0:
        eth_price_usd = eth_price_usd_from_feed

    total_collateral_usd = Decimal("0")
    discounted_collateral_usd = Decimal("0")
    total_debt_usd = Decimal("0")
    eth_sensitive_collateral_usd = Decimal("0")
    eth_sensitive_discounted_collateral_usd = Decimal("0")
    eth_sensitive_debt_usd = Decimal("0")
    non_eth_collateral_usd = Decimal("0")
    non_eth_discounted_collateral_usd = Decimal("0")
    non_eth_debt_usd = Decimal("0")
    assets_jsonb: list[dict[str, Any]] = []
    event_market_lc = event_market_address.lower()

    for row in market_rows:
        supply_usd = row["supply"] * row["price_usd"]
        borrow_usd = row["borrow"] * row["price_usd"]
        discounted_usd = (
            supply_usd * row["collateral_factor"]
            if row["is_collateral"]
            else Decimal("0")
        )
        is_eth_corr = str(row["underlying_symbol"]).upper() in _ETH_CORRELATED_SYMBOLS
        if row["is_collateral"]:
            total_collateral_usd += supply_usd
            discounted_collateral_usd += discounted_usd
            if is_eth_corr:
                eth_sensitive_collateral_usd += supply_usd
                eth_sensitive_discounted_collateral_usd += discounted_usd
            else:
                non_eth_collateral_usd += supply_usd
                non_eth_discounted_collateral_usd += discounted_usd
        total_debt_usd += borrow_usd
        if is_eth_corr:
            eth_sensitive_debt_usd += borrow_usd
        else:
            non_eth_debt_usd += borrow_usd

        if row["supply"] > 0:
            assets_jsonb.append(
                {
                    "asset": row["underlying"],
                    "symbol": row["underlying_symbol"],
                    "side": (
                        "base_supply"
                        if row["market"] == event_market_lc
                        else "collateral"
                    ),
                    "amount": str(row["supply"]),
                    "price_in_base": None,
                    "price_usd": str(row["price_usd"]),
                    "value_usd": str(supply_usd),
                    "discounted_value_usd": str(discounted_usd),
                    "borrow_collateral_factor": None,
                    "liquidate_collateral_factor": None,
                    "liquidation_factor": None,
                    "beta_to_eth": "1" if is_eth_corr else "0",
                    "is_eth_correlated": is_eth_corr,
                    "is_basis_risk_asset": False,
                }
            )
        if row["borrow"] > 0:
            assets_jsonb.append(
                {
                    "asset": row["underlying"],
                    "symbol": row["underlying_symbol"],
                    "side": "base_borrow",
                    "amount": str(row["borrow"]),
                    "price_in_base": None,
                    "price_usd": str(row["price_usd"]),
                    "value_usd": str(borrow_usd),
                    "discounted_value_usd": "0",
                    "borrow_collateral_factor": None,
                    "liquidate_collateral_factor": None,
                    "liquidation_factor": None,
                    "beta_to_eth": "1" if is_eth_corr else "0",
                    "is_eth_correlated": is_eth_corr,
                    "is_basis_risk_asset": False,
                }
            )

    liquidation_buffer_usd = discounted_collateral_usd - total_debt_usd
    health_factor = (
        _MAX_HEALTH_FACTOR
        if total_debt_usd <= 0
        else discounted_collateral_usd / total_debt_usd
    )
    net_eth_exposure_usd = eth_sensitive_collateral_usd - eth_sensitive_debt_usd
    has_open_position = total_collateral_usd > 0 or total_debt_usd > 0
    is_liquidatable = total_debt_usd > 0 and liquidation_buffer_usd < 0

    eth_down_liq_price_usd: Decimal | None = None
    eth_up_liq_price_usd: Decimal | None = None
    eth_liq_mode = "neutral"
    denom = eth_sensitive_discounted_collateral_usd - eth_sensitive_debt_usd
    numer = non_eth_debt_usd - non_eth_discounted_collateral_usd
    if eth_price_usd > 0 and denom != 0:
        ratio = numer / denom
        liq_price = eth_price_usd * ratio
        if liq_price > 0:
            if ratio < 1:
                eth_down_liq_price_usd = liq_price
                eth_liq_mode = "down"
            elif ratio > 1:
                eth_up_liq_price_usd = liq_price
                eth_liq_mode = "up"

    dominant_risk = "neutral"
    if eth_liq_mode == "down":
        dominant_risk = "eth_down"
    elif eth_liq_mode == "up":
        dominant_risk = "eth_up"

    event_market_row = next(
        (row for row in market_rows if row["market"] == event_market_lc),
        None,
    )
    if event_market_row is None:
        event_market_row = {
            "market": event_market_lc,
            "symbol": COMPOUND_V2_MARKET_NAMES.get(event_market_lc, event_market_lc),
            "underlying": WETH_MAINNET.lower(),
            "underlying_symbol": "WETH",
            "price_usd": eth_price_usd,
        }

    return CompoundEventPositionSnapshotRow(
        user_address=user_address,
        protocol="v2",
        market=event_market,
        symbol=event_market_row["symbol"],
        block_number=block_number,
        tx_hash="",
        block_timestamp=point_ts,
        has_open_position=has_open_position,
        is_liquidatable=is_liquidatable,
        base_token=bytes.fromhex(event_market_row["underlying"][2:]),
        base_symbol=event_market_row["underlying_symbol"],
        base_price_usd=event_market_row["price_usd"],
        eth_price_usd=eth_price_usd,
        total_collateral_usd=total_collateral_usd,
        total_debt_usd=total_debt_usd,
        discounted_collateral_usd=discounted_collateral_usd,
        liquidation_buffer_usd=liquidation_buffer_usd,
        health_factor=health_factor,
        eth_sensitive_collateral_usd=eth_sensitive_collateral_usd,
        eth_sensitive_debt_usd=eth_sensitive_debt_usd,
        net_eth_exposure_usd=net_eth_exposure_usd,
        non_eth_collateral_usd=non_eth_collateral_usd,
        non_eth_debt_usd=non_eth_debt_usd,
        basis_risk_collateral_usd=Decimal("0"),
        eth_down_liq_price_usd=eth_down_liq_price_usd,
        eth_up_liq_price_usd=eth_up_liq_price_usd,
        eth_liq_mode=eth_liq_mode,
        dominant_risk=dominant_risk,
        assets_jsonb=assets_jsonb,
        brief="",
    )


async def _collect_and_cache_replay_misses(
    pool,
    *,
    version: str,
    user_address: bytes,
    misses: list[dict[str, Any]],
    w3: Any | None,
) -> None:
    if not misses:
        return

    tx_hash_bytes = [
        bytes.fromhex(tx["tx_hash"][2:])
        for tx in misses
        if isinstance(tx["tx_hash"], str)
    ]
    brief_map = await _load_compound_replay_briefs(
        pool,
        protocol=version,
        user_address=user_address,
        tx_hashes=tx_hash_bytes,
    )

    own_w3 = False
    active_w3 = w3
    if active_w3 is None:
        active_w3 = await _build_web3(load_config())
        own_w3 = True
    metadata_cache: dict[str, tuple[str | None, int | None]] = {}
    sem = asyncio.Semaphore(_REPLAY_RPC_CONCURRENCY)

    grouped: dict[tuple[bytes, int], list[dict[str, Any]]] = defaultdict(list)
    for tx in misses:
        grouped[(tx["market"], tx["block_number"])].append(tx)

    pending_rows: list[CompoundEventPositionSnapshotRow] = []
    try:
        for group_batch in _chunked(list(grouped.items()), _REPLAY_BATCH_SIZE):
            tasks: list[asyncio.Task[list[CompoundEventPositionSnapshotRow]]] = []
            for (market_bytes, block_number), tx_group in group_batch:

                async def _one_group(
                    market_bytes: bytes = market_bytes,
                    block_number: int = block_number,
                    tx_group: list[dict[str, Any]] = tx_group,
                ) -> list[CompoundEventPositionSnapshotRow]:
                    async with sem:
                        if version == "v3":
                            market_address = "0x" + market_bytes.hex()
                            market_ctx = await _load_market_context(
                                active_w3,
                                market_address=market_address,
                                block_number=block_number,
                                metadata_cache=metadata_cache,
                            )
                            snapshots = await _collect_user_snapshots_batch(
                                active_w3,
                                market_ctx=market_ctx,
                                user_addresses=[user_address],
                                point_ts=tx_group[0]["block_timestamp"],
                                block_number=block_number,
                            )
                            if not snapshots:
                                return []
                            snapshot_row, _ = snapshots[0]
                        else:
                            snapshot_row = await _collect_v2_replay_snapshot_row(
                                active_w3,
                                user_address=user_address,
                                event_market=market_bytes,
                                block_number=block_number,
                                point_ts=tx_group[0]["block_timestamp"],
                                metadata_cache=metadata_cache,
                            )
                    out: list[CompoundEventPositionSnapshotRow] = []
                    for tx in tx_group:
                        out.append(
                            CompoundEventPositionSnapshotRow(
                                user_address=snapshot_row.user_address,
                                protocol=version,
                                market=snapshot_row.market,
                                symbol=snapshot_row.symbol,
                                block_number=snapshot_row.block_number,
                                tx_hash=tx["tx_hash"],
                                block_timestamp=tx["block_timestamp"],
                                has_open_position=snapshot_row.has_open_position,
                                is_liquidatable=snapshot_row.is_liquidatable,
                                base_token=snapshot_row.base_token,
                                base_symbol=snapshot_row.base_symbol,
                                base_price_usd=snapshot_row.base_price_usd,
                                eth_price_usd=snapshot_row.eth_price_usd,
                                total_collateral_usd=snapshot_row.total_collateral_usd,
                                total_debt_usd=snapshot_row.total_debt_usd,
                                discounted_collateral_usd=snapshot_row.discounted_collateral_usd,
                                liquidation_buffer_usd=snapshot_row.liquidation_buffer_usd,
                                health_factor=snapshot_row.health_factor,
                                eth_sensitive_collateral_usd=snapshot_row.eth_sensitive_collateral_usd,
                                eth_sensitive_debt_usd=snapshot_row.eth_sensitive_debt_usd,
                                net_eth_exposure_usd=snapshot_row.net_eth_exposure_usd,
                                non_eth_collateral_usd=snapshot_row.non_eth_collateral_usd,
                                non_eth_debt_usd=snapshot_row.non_eth_debt_usd,
                                basis_risk_collateral_usd=snapshot_row.basis_risk_collateral_usd,
                                eth_down_liq_price_usd=snapshot_row.eth_down_liq_price_usd,
                                eth_up_liq_price_usd=snapshot_row.eth_up_liq_price_usd,
                                eth_liq_mode=snapshot_row.eth_liq_mode,
                                dominant_risk=snapshot_row.dominant_risk,
                                assets_jsonb=snapshot_row.assets_jsonb,
                                brief=brief_map.get(
                                    tx["tx_hash"],
                                    _fallback_replay_brief(
                                        version,
                                        tx.get("method_id"),
                                        snapshot_row.market,
                                    ),
                                ),
                            )
                        )
                    return out

                tasks.append(asyncio.create_task(_one_group()))
            for task in asyncio.as_completed(tasks):
                pending_rows.extend(await task)
                if len(pending_rows) >= _REPLAY_BATCH_SIZE:
                    await upsert_compound_event_snapshots(pool, pending_rows)
                    pending_rows = []
        if pending_rows:
            await upsert_compound_event_snapshots(pool, pending_rows)
    finally:
        if own_w3:
            await close_web3(active_w3)


async def get_position_replay(
    pool,
    version: str,
    address: str,
    from_ts: int,
    to_ts: int,
    use_cache: bool = True,
    detail: bool = False,
    w3: Any | None = None,
) -> CompoundPositionReplayResponse:
    version = version.lower()
    if version not in ("v2", "v3"):
        raise HTTPException(status_code=400, detail="version 仅支持 v2 或 v3")
    user_address = _parse_user_address(address)
    from_dt = datetime.fromtimestamp(from_ts, tz=timezone.utc)
    to_dt = datetime.fromtimestamp(to_ts, tz=timezone.utc)

    tx_rows = await fetch_compound_user_tx_history(
        pool,
        user_address=user_address,
        protocol=version,
        from_dt=from_dt,
        to_dt=to_dt,
        market=None,
        only_success=True,
        user_column="from_address",
    )
    txs: list[dict[str, Any]] = []
    for row in tx_rows:
        market = _normalize_market_bytes(_row_get(row, "market"))
        tx_hash = _normalize_tx_hash(_row_get(row, "tx_hash"))
        method_id = _normalize_method_id(_row_get(row, "method_id"))
        if (
            market is None
            or tx_hash is None
            or not _position_method(version, method_id)
        ):
            continue
        block_number = int(_row_get(row, "block_number"))
        block_timestamp = _row_get(row, "block_timestamp")
        if not isinstance(block_timestamp, datetime):
            continue
        if block_timestamp.tzinfo is None:
            block_timestamp = block_timestamp.replace(tzinfo=timezone.utc)
        else:
            block_timestamp = block_timestamp.astimezone(timezone.utc)
        txs.append(
            {
                "market": market,
                "tx_hash": tx_hash,
                "method_id": method_id,
                "block_number": block_number,
                "block_timestamp": block_timestamp,
            }
        )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[bytes, str]] = set()
    for tx in txs:
        key = (tx["market"], tx["tx_hash"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tx)

    deduped = [
        tx
        for tx in deduped
        if _is_replay_self_impact_method(version, tx.get("method_id"))
    ]
    if not deduped:
        return CompoundPositionReplayResponse(
            address=_bytea_to_address(user_address),
            version=version,
            from_time=_timestamp_to_utc_string(from_dt),
            to_time=_timestamp_to_utc_string(to_dt),
            data_source="cache",
            points=[],
            total_points=0,
            total_tx_count=0,
            cache_hit_rate="1.00",
        )

    market_set = {tx["market"] for tx in deduped}
    cached_map: dict[tuple[bytes, str], Any] = {}
    if use_cache:
        for market in market_set:
            rows = await get_compound_event_snapshots(
                pool,
                user_address=user_address,
                protocol=version,
                market=market,
                from_ts=from_dt,
                to_ts=to_dt,
            )
            for row in rows:
                tx_hash = _normalize_tx_hash(_row_get(row, "tx_hash"))
                if tx_hash is None:
                    continue
                cached_map[(market, tx_hash)] = row

    misses = [tx for tx in deduped if (tx["market"], tx["tx_hash"]) not in cached_map]
    if misses:
        await _collect_and_cache_replay_misses(
            pool,
            version=version,
            user_address=user_address,
            misses=misses,
            w3=w3,
        )
        for market in {tx["market"] for tx in misses}:
            rows = await get_compound_event_snapshots(
                pool,
                user_address=user_address,
                protocol=version,
                market=market,
                from_ts=from_dt,
                to_ts=to_dt,
            )
            for row in rows:
                tx_hash = _normalize_tx_hash(_row_get(row, "tx_hash"))
                if tx_hash is None:
                    continue
                cached_map[(market, tx_hash)] = row

    points: list[CompoundPositionReplayPoint] = []
    served_from_cache = 0
    for tx in deduped:
        key = (tx["market"], tx["tx_hash"])
        row = cached_map.get(key)
        if row is None:
            continue
        served_from_cache += 1
        assets = []
        if detail:
            assets = [
                _map_position_asset(item)
                for item in _load_assets_payload(_row_get(row, "assets_jsonb"))
            ]
        points.append(
            CompoundPositionReplayPoint(
                tx_hash=tx["tx_hash"],
                block_number=int(_row_get(row, "block_number")),
                timestamp=_timestamp_to_utc_string(_row_get(row, "block_timestamp")),
                market=_bytea_to_address(tx["market"]),
                symbol=_row_get(row, "symbol"),
                eth_price_usd=_fmt(_row_get(row, "eth_price_usd")),
                total_collateral_usd=_fmt(_row_get(row, "total_collateral_usd")),
                total_debt_usd=_fmt(_row_get(row, "total_debt_usd")),
                discounted_collateral_usd=_fmt(
                    _row_get(row, "discounted_collateral_usd")
                ),
                liquidation_buffer_usd=_fmt(_row_get(row, "liquidation_buffer_usd")),
                health_factor=_fmt(_row_get(row, "health_factor")),
                is_liquidatable=bool(_row_get(row, "is_liquidatable")),
                eth_down_liq_price_usd=_fmt_optional(
                    _row_get(row, "eth_down_liq_price_usd")
                ),
                eth_up_liq_price_usd=_fmt_optional(
                    _row_get(row, "eth_up_liq_price_usd")
                ),
                eth_liq_mode=str(_row_get(row, "eth_liq_mode")),
                dominant_risk=str(_row_get(row, "dominant_risk")),
                brief=str(_row_get(row, "brief") or ""),
                assets=assets,
            )
        )

    total_tx = len(deduped)
    cache_hit_rate = (
        _fmt(Decimal(served_from_cache) / Decimal(total_tx)) if total_tx > 0 else "1.00"
    )
    if served_from_cache == total_tx:
        data_source = "cache"
    elif served_from_cache == 0:
        data_source = "rpc"
    else:
        data_source = "mixed"

    return CompoundPositionReplayResponse(
        address=_bytea_to_address(user_address),
        version=version,
        from_time=_timestamp_to_utc_string(from_dt),
        to_time=_timestamp_to_utc_string(to_dt),
        data_source=data_source,
        points=points,
        total_points=len(points),
        total_tx_count=total_tx,
        cache_hit_rate=cache_hit_rate,
    )


async def get_market_governance(
    pool,
    version: str,
    market: str,
    date: str | None = None,
    detail: bool = False,
) -> MarketGovernanceResponse:
    if version != "v3":
        raise HTTPException(status_code=400, detail="当前仅支持 version=v3")

    market_address = _market_to_address("v3", market)
    market_bytes = _address_to_bytes(market_address)
    point_ts = _parse_hour_utc(date) if date is not None else None

    async with pool.acquire() as conn:
        if point_ts is None:
            row = await conn.fetchrow(
                f"""
                SELECT *
                FROM loan.{_GOVERNANCE_TABLE}
                WHERE market = $1
                ORDER BY effective_timestamp DESC, block_number DESC
                LIMIT 1
                """,
                market_bytes,
            )
        else:
            row = await conn.fetchrow(
                f"""
                SELECT *
                FROM loan.{_GOVERNANCE_TABLE}
                WHERE market = $1
                  AND effective_timestamp <= $2
                ORDER BY effective_timestamp DESC, block_number DESC
                LIMIT 1
                """,
                market_bytes,
                point_ts,
            )

        if row is None:
            raise HTTPException(status_code=404, detail="未找到该市场的治理参数")

        asset_rows: list[Any] = []
        if detail:
            asset_rows = await conn.fetch(
                f"""
                SELECT *
                FROM loan.{_GOVERNANCE_ASSET_TABLE}
                WHERE market = $1
                  AND config_hash = $2
                ORDER BY symbol NULLS LAST, asset
                """,
                market_bytes,
                row["config_hash"],
            )

    return _map_market_governance_row(row, asset_rows, detail=detail)


async def get_market_governance_period(
    pool,
    version: str,
    market: str,
    start: str,
    end: str,
    latest_only_per_day: bool = False,
    detail: bool = False,
) -> MarketGovernancePeriodResponse:
    if version != "v3":
        raise HTTPException(status_code=400, detail="当前仅支持 version=v3")

    start_dt = _parse_hour_utc(start)
    end_dt = _parse_hour_utc(end)
    if start_dt > end_dt:
        raise HTTPException(status_code=400, detail="start 必须小于等于 end")

    market_address = _market_to_address("v3", market)
    market_bytes = _address_to_bytes(market_address)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT *
            FROM loan.{_GOVERNANCE_TABLE}
            WHERE market = $1
              AND effective_timestamp >= $2
              AND effective_timestamp <= $3
            ORDER BY effective_timestamp, block_number, config_hash
            """,
            market_bytes,
            start_dt,
            end_dt,
        )
        if not rows:
            return MarketGovernancePeriodResponse(points=[])

        selected_rows = list(rows)
        if latest_only_per_day:
            rows_by_day: dict[date, Any] = {}
            for row in selected_rows:
                ts = _row_get(row, "effective_timestamp")
                day = ts.astimezone(timezone.utc).date()
                rows_by_day[day] = row
            selected_rows = [rows_by_day[day] for day in sorted(rows_by_day)]

        asset_rows: list[Any] = []
        if detail:
            config_hashes = [str(row["config_hash"]) for row in selected_rows]
            asset_rows = await conn.fetch(
                f"""
                SELECT *
                FROM loan.{_GOVERNANCE_ASSET_TABLE}
                WHERE market = $1
                  AND config_hash = ANY($2::text[])
                ORDER BY config_hash, symbol NULLS LAST, asset
                """,
                market_bytes,
                config_hashes,
            )

    asset_rows_by_hash: dict[str, list[Any]] = {}
    for asset_row in asset_rows:
        asset_rows_by_hash.setdefault(str(asset_row["config_hash"]), []).append(
            asset_row
        )

    return MarketGovernancePeriodResponse(
        points=[
            _map_market_governance_row(
                row,
                asset_rows_by_hash.get(str(row["config_hash"]), []),
                detail=detail,
            )
            for row in selected_rows
        ]
    )


async def get_v2_market_config(
    pool,
    version: str,
    market: str,
    date: str | None = None,
    w3: Any | None = None,
) -> V2MarketConfigResponse:
    if version != "v2":
        raise HTTPException(status_code=400, detail="当前仅支持 version=v2")
    market_address = _market_to_address("v2", market)
    market_bytes = _address_to_bytes(market_address)
    point_ts = _parse_hour_utc(date) if date is not None else None
    async with pool.acquire() as conn:
        if point_ts is None:
            row = await conn.fetchrow(
                f"""
                SELECT *
                FROM loan.{_V2_MARKET_CONFIG_TABLE}
                WHERE market = $1
                ORDER BY effective_timestamp DESC, block_number DESC
                LIMIT 1
                """,
                market_bytes,
            )
        else:
            row = await conn.fetchrow(
                f"""
                SELECT *
                FROM loan.{_V2_MARKET_CONFIG_TABLE}
                WHERE market = $1
                  AND effective_timestamp <= $2
                ORDER BY effective_timestamp DESC, block_number DESC
                LIMIT 1
                """,
                market_bytes,
                point_ts,
            )
        row = await _enrich_v2_market_config_row(conn, row, w3=w3)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到该市场的 v2 配置")
    return _map_v2_market_config_row(row)


async def get_v2_market_config_period(
    pool,
    version: str,
    market: str,
    start: str,
    end: str,
    latest_only_per_day: bool = False,
    w3: Any | None = None,
) -> V2MarketConfigPeriodResponse:
    if version != "v2":
        raise HTTPException(status_code=400, detail="当前仅支持 version=v2")
    start_dt = _parse_hour_utc(start)
    end_dt = _parse_hour_utc(end)
    if start_dt > end_dt:
        raise HTTPException(status_code=400, detail="start 必须小于等于 end")
    market_address = _market_to_address("v2", market)
    market_bytes = _address_to_bytes(market_address)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT *
            FROM loan.{_V2_MARKET_CONFIG_TABLE}
            WHERE market = $1
              AND effective_timestamp >= $2
              AND effective_timestamp <= $3
            ORDER BY effective_timestamp, block_number, config_hash
            """,
            market_bytes,
            start_dt,
            end_dt,
        )
        rows = [await _enrich_v2_market_config_row(conn, row, w3=w3) for row in rows]
    if not rows:
        return V2MarketConfigPeriodResponse(points=[])
    selected_rows = list(rows)
    if latest_only_per_day:
        rows_by_day: dict[date, Any] = {}
        for row in selected_rows:
            ts = _row_get(row, "effective_timestamp")
            day = ts.astimezone(timezone.utc).date()
            rows_by_day[day] = row
        selected_rows = [rows_by_day[day] for day in sorted(rows_by_day)]
    return V2MarketConfigPeriodResponse(
        points=[_map_v2_market_config_row(row) for row in selected_rows]
    )


async def get_v2_protocol_config(
    pool,
    version: str,
    date: str | None = None,
) -> V2ProtocolConfigResponse:
    if version != "v2":
        raise HTTPException(status_code=400, detail="当前仅支持 version=v2")
    point_ts = _parse_hour_utc(date) if date is not None else None
    async with pool.acquire() as conn:
        if point_ts is None:
            row = await conn.fetchrow(
                f"""
                SELECT *
                FROM loan.{_V2_PROTOCOL_CONFIG_TABLE}
                ORDER BY effective_timestamp DESC, block_number DESC
                LIMIT 1
                """
            )
        else:
            row = await conn.fetchrow(
                f"""
                SELECT *
                FROM loan.{_V2_PROTOCOL_CONFIG_TABLE}
                WHERE effective_timestamp <= $1
                ORDER BY effective_timestamp DESC, block_number DESC
                LIMIT 1
                """,
                point_ts,
            )
    if row is None:
        raise HTTPException(status_code=404, detail="未找到 v2 协议配置")
    return _map_v2_protocol_config_row(row)


async def get_v2_protocol_config_period(
    pool,
    version: str,
    start: str,
    end: str,
    latest_only_per_day: bool = False,
) -> V2ProtocolConfigPeriodResponse:
    if version != "v2":
        raise HTTPException(status_code=400, detail="当前仅支持 version=v2")
    start_dt = _parse_hour_utc(start)
    end_dt = _parse_hour_utc(end)
    if start_dt > end_dt:
        raise HTTPException(status_code=400, detail="start 必须小于等于 end")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT *
            FROM loan.{_V2_PROTOCOL_CONFIG_TABLE}
            WHERE effective_timestamp >= $1
              AND effective_timestamp <= $2
            ORDER BY effective_timestamp, block_number, config_hash
            """,
            start_dt,
            end_dt,
        )
    if not rows:
        return V2ProtocolConfigPeriodResponse(points=[])
    selected_rows = list(rows)
    if latest_only_per_day:
        rows_by_day: dict[date, Any] = {}
        for row in selected_rows:
            ts = _row_get(row, "effective_timestamp")
            day = ts.astimezone(timezone.utc).date()
            rows_by_day[day] = row
        selected_rows = [rows_by_day[day] for day in sorted(rows_by_day)]
    return V2ProtocolConfigPeriodResponse(
        points=[_map_v2_protocol_config_row(row) for row in selected_rows]
    )


async def get_sorted_positions(limit: int) -> list[PositionResponse]:
    _ = limit
    return []


def _parse_hour_utc(date_str: str) -> datetime:
    fmts = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if dt.minute != 0 or dt.second != 0 or dt.microsecond != 0:
            raise HTTPException(
                status_code=400,
                detail="date 需精确到小时（分钟和秒必须为 00）",
            )
        return dt
    raise HTTPException(
        status_code=400,
        detail="date 格式无法识别，示例：2026-03-19T12:00:00Z",
    )


def _parse_midnight_utc(date_str: str) -> datetime:
    fmts = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    raise HTTPException(
        status_code=400,
        detail="date 格式无法识别，示例：2026-03-21 或 2026-03-21T12:34:56Z",
    )


def _fmt(value: Decimal | float | int | str | None) -> str:
    if value is None:
        return "0"
    return str(value)


def _fmt_optional(value: Decimal | float | int | str | None) -> str | None:
    if value is None:
        return None
    return str(value)


async def _enrich_v2_market_config_row(
    conn: Any, row: Any, *, w3: Any | None = None
) -> Any:
    if row is None:
        return None
    raw_config = _row_get(row, "raw_config_jsonb", {})
    raw_config_dict = dict(raw_config) if isinstance(raw_config, dict) else {}
    updated = False
    ctoken_decimals = _row_get(row, "ctoken_decimals")
    underlying_decimals = _row_get(row, "underlying_decimals")

    scale: Decimal | None = None
    if ctoken_decimals is not None and underlying_decimals is not None:
        try:
            scale = Decimal(10) ** max(
                0,
                18 + int(underlying_decimals) - int(ctoken_decimals),
            )
        except Exception:
            scale = None

    if not raw_config_dict.get("protocol_config_hash"):
        market_effective_ts = _row_get(row, "effective_timestamp")
        if isinstance(market_effective_ts, datetime):
            protocol_row = await conn.fetchrow(
                f"""
                SELECT config_hash
                FROM loan.{_V2_PROTOCOL_CONFIG_TABLE}
                WHERE effective_timestamp <= $1
                ORDER BY effective_timestamp DESC, block_number DESC
                LIMIT 1
                """,
                market_effective_ts,
            )
            if protocol_row is not None and protocol_row["config_hash"] is not None:
                raw_config_dict["protocol_config_hash"] = str(
                    protocol_row["config_hash"]
                )
                updated = True

    # 先用表字段兜底，避免旧行 raw_config_jsonb 不完整导致返回缺失。
    if raw_config_dict.get("exchange_rate") is None:
        exchange_rate_col = _row_get(row, "exchange_rate")
        if exchange_rate_col is not None:
            raw_config_dict["exchange_rate"] = _fmt_optional(exchange_rate_col)
            updated = True

    exchange_rate_raw = raw_config_dict.get("exchange_rate_raw")
    if exchange_rate_raw is None and scale is not None:
        exchange_rate_value = raw_config_dict.get("exchange_rate")
        if exchange_rate_value is not None:
            try:
                raw_config_dict["exchange_rate_raw"] = str(
                    int(Decimal(str(exchange_rate_value)) * scale)
                )
                exchange_rate_raw = raw_config_dict["exchange_rate_raw"]
                updated = True
            except Exception:
                exchange_rate_raw = None

    if exchange_rate_raw is None and w3 is not None:
        market_bytes = _row_get(row, "market")
        block_number = _row_get(row, "block_number")
        if isinstance(market_bytes, (bytes, bytearray)) and isinstance(
            block_number, int
        ):
            try:
                market_address = _bytea_to_address(bytes(market_bytes))
                ctoken = w3.eth.contract(
                    address=AsyncWeb3.to_checksum_address(market_address),
                    abi=CTOKEN_V2_ABI,
                )
                exchange_rate_raw = await ctoken.functions.exchangeRateStored().call(
                    block_identifier=block_number
                )
                raw_config_dict["exchange_rate_raw"] = str(int(exchange_rate_raw))
                updated = True
            except Exception:
                exchange_rate_raw = None

    if raw_config_dict.get("exchange_rate") is None:
        if exchange_rate_raw is not None and scale is not None:
            try:
                raw = Decimal(str(exchange_rate_raw))
                raw_config_dict["exchange_rate"] = str(raw / scale)
                updated = True
            except Exception:
                pass

    if not updated:
        return row

    row_dict = dict(row)
    row_dict["raw_config_jsonb"] = raw_config_dict
    return row_dict


def _annualize_rate(value: Decimal | float | int | None) -> str:
    if value is None:
        return "0"
    return _fmt(Decimal(str(value)) * _SECONDS_PER_YEAR)


def _markets_to_addresses(version: str, market: str) -> list[str]:
    normalized = market.strip().lower()
    if normalized == "all":
        return _available_market_addresses(version)
    return [_market_to_address(version, market)]


def _market_to_address(version: str, market: str | None = None) -> str:
    # Backward compatibility for internal/tests that call _market_to_address(market)
    # and expect v3 defaults.
    if market is None:
        market = version
        version = "v3"
    normalized = market.strip().lower()
    if normalized.startswith("0x") and len(normalized) == 42:
        return normalized

    market_name_map = _market_name_map(version)
    for address, name in market_name_map.items():
        if name.lower() == normalized:
            return address

    raise HTTPException(
        status_code=400,
        detail=f"market 仅支持已配置的 Compound {version} 市场地址或符号，或 all",
    )


def _address_to_bytes(address: str) -> bytes:
    addr = address.strip().lower()
    if addr.startswith("0x"):
        addr = addr[2:]
    return bytes.fromhex(addr)


def _parse_user_address(address: str) -> bytes:
    normalized = address.strip().lower()
    if not normalized.startswith("0x") or len(normalized) != 42:
        raise HTTPException(status_code=400, detail="address 必须为合法的 0x 地址")
    try:
        return _address_to_bytes(normalized)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="address 必须为合法的 0x 地址"
        ) from exc


def _load_assets_payload(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return decoded if isinstance(decoded, list) else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _bytea_to_optional_address(value: Any) -> str | None:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _bytea_to_address(value)
    return None


def _map_position_asset(payload: dict[str, Any]) -> PositionAssetResponse:
    return PositionAssetResponse(
        asset=str(payload.get("asset", "")),
        symbol=payload.get("symbol"),
        side=str(payload.get("side", "")),
        amount=_fmt(payload.get("amount")),
        price_in_base=_fmt_optional(payload.get("price_in_base")),
        price_usd=_fmt(payload.get("price_usd")),
        value_usd=_fmt(payload.get("value_usd")),
        discounted_value_usd=_fmt(payload.get("discounted_value_usd")),
        borrow_collateral_factor=_fmt_optional(payload.get("borrow_collateral_factor")),
        liquidate_collateral_factor=_fmt_optional(
            payload.get("liquidate_collateral_factor")
        ),
        liquidation_factor=_fmt_optional(payload.get("liquidation_factor")),
        beta_to_eth=_fmt(payload.get("beta_to_eth")),
        is_eth_correlated=bool(payload.get("is_eth_correlated", False)),
        is_basis_risk_asset=bool(payload.get("is_basis_risk_asset", False)),
    )


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        return getattr(row, key, default)


def _require_bytes(value: Any, field_name: str) -> bytes | bytearray | memoryview:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return value
    raise ValueError(f"{field_name} is missing")


def _require_int(value: Any, field_name: str) -> int:
    if value is None:
        raise ValueError(f"{field_name} is missing")
    return int(value)


def _map_position_row(row: Any) -> PositionResponse:
    assets = [
        _map_position_asset(item)
        for item in _load_assets_payload(_row_get(row, "assets_jsonb"))
    ]
    return PositionResponse(
        market=_bytea_to_address(_require_bytes(_row_get(row, "market"), "market")),
        symbol=_row_get(row, "symbol"),
        timestamp=_timestamp_to_utc_string(_row_get(row, "timestamp")),
        block_number=_require_int(_row_get(row, "block_number"), "block_number"),
        has_open_position=bool(_row_get(row, "has_open_position", True)),
        is_liquidatable=bool(_row_get(row, "is_liquidatable", False)),
        base_token=_bytea_to_address(
            _require_bytes(_row_get(row, "base_token"), "base_token")
        ),
        base_symbol=_row_get(row, "base_symbol"),
        base_price_usd=_fmt(_row_get(row, "base_price_usd")),
        eth_price_usd=_fmt(_row_get(row, "eth_price_usd")),
        total_collateral_usd=_fmt(_row_get(row, "total_collateral_usd")),
        total_debt_usd=_fmt(_row_get(row, "total_debt_usd")),
        discounted_collateral_usd=_fmt(_row_get(row, "discounted_collateral_usd")),
        liquidation_buffer_usd=_fmt(_row_get(row, "liquidation_buffer_usd")),
        health_factor=_fmt(_row_get(row, "health_factor")),
        eth_sensitive_collateral_usd=_fmt(
            _row_get(row, "eth_sensitive_collateral_usd")
        ),
        eth_sensitive_debt_usd=_fmt(_row_get(row, "eth_sensitive_debt_usd")),
        net_eth_exposure_usd=_fmt(_row_get(row, "net_eth_exposure_usd")),
        non_eth_collateral_usd=_fmt(_row_get(row, "non_eth_collateral_usd")),
        non_eth_debt_usd=_fmt(_row_get(row, "non_eth_debt_usd")),
        basis_risk_collateral_usd=_fmt(_row_get(row, "basis_risk_collateral_usd")),
        eth_down_liq_price_usd=_fmt_optional(_row_get(row, "eth_down_liq_price_usd")),
        eth_up_liq_price_usd=_fmt_optional(_row_get(row, "eth_up_liq_price_usd")),
        eth_liq_mode=str(_row_get(row, "eth_liq_mode")),
        dominant_risk=str(_row_get(row, "dominant_risk")),
        assets=assets,
    )


def _map_and_sort_positions(rows: list[Any]) -> list[PositionResponse]:
    positions = [_map_position_row(row) for row in rows]
    return _sort_positions(positions)


def _sort_positions(positions: list[PositionResponse]) -> list[PositionResponse]:
    positions.sort(
        key=lambda row: (
            Decimal(row.liquidation_buffer_usd),
            -Decimal(row.total_debt_usd),
            row.market,
        )
    )
    return positions


def _simulated_eth_sensitive_collateral_usd(
    row: CompoundCurrentPositionRow,
    *,
    eth_price: Decimal,
) -> Decimal:
    current_eth_price = Decimal(str(row.eth_price_usd))
    current_sensitive_usd = Decimal(str(row.eth_sensitive_collateral_usd))
    if current_eth_price <= 0:
        return current_sensitive_usd
    simulated = current_sensitive_usd * eth_price / current_eth_price
    return simulated if simulated > 0 else Decimal("0")


async def simulate_liquidation(
    pool,
    *,
    version: str,
    eth_price: Decimal,
    market: str = "all",
    orderby: str = "liq_price",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> CompoundLiquidationSimResponse:
    version = version.lower()
    eth_price = Decimal(str(eth_price))
    if version != "v3":
        raise HTTPException(
            status_code=400,
            detail="compound/liquidate 当前仅支持 v3",
        )

    market_filter = (
        None
        if market.strip().lower() == "all"
        else _address_to_bytes(_market_to_address(version, market))
    )
    rows = await fetch_compound_v3_current_positions(pool, market=market_filter)

    items: list[
        tuple[CompoundLiquidationSimItem, Decimal, Decimal, Decimal, Decimal]
    ] = []
    total_sensitive_collateral_usd = Decimal("0")
    total_liquidation_usd = Decimal("0")

    for row in rows:
        if not row.has_open_position or row.is_liquidatable:
            continue

        total_debt_usd = Decimal(str(row.total_debt_usd))
        liq_price = row.eth_down_liq_price_usd
        if total_debt_usd <= 0 or liq_price is None:
            continue

        liq_price_dec = Decimal(str(liq_price))
        if liq_price_dec <= 0 or liq_price_dec < eth_price:
            continue

        eth_sensitive_collateral_usd = Decimal(str(row.eth_sensitive_collateral_usd))
        simulated_sensitive_usd = _simulated_eth_sensitive_collateral_usd(
            row,
            eth_price=eth_price,
        )
        liquidation_usd = min(total_debt_usd, simulated_sensitive_usd)

        total_sensitive_collateral_usd += eth_sensitive_collateral_usd
        total_liquidation_usd += liquidation_usd
        items.append(
            (
                CompoundLiquidationSimItem(
                    address=_bytea_to_address(row.user_address),
                    market=_bytea_to_address(row.market),
                    symbol=row.symbol,
                    liq_price=_fmt(liq_price_dec),
                    eth_sensitive_collateral_usd=_fmt(eth_sensitive_collateral_usd),
                    total_collateral_usd=_fmt(row.total_collateral_usd),
                    total_debt_usd=_fmt(total_debt_usd),
                ),
                liq_price_dec,
                eth_sensitive_collateral_usd,
                Decimal(str(row.total_collateral_usd)),
                total_debt_usd,
            )
        )

    sort_key = _COMPOUND_LIQ_SORT_COLS.get(orderby, "liq_price")
    reverse = order.lower() == "desc"
    key_map = {
        "liq_price": lambda item: item[1],
        "eth_sensitive_collateral_usd": lambda item: item[2],
        "total_collateral_usd": lambda item: item[3],
        "total_debt_usd": lambda item: item[4],
    }
    items.sort(key=key_map[sort_key], reverse=reverse)

    total_count = len(items)
    page_start = min(offset, total_count)
    paged_items = [item[0] for item in items[page_start : page_start + limit]]
    page_note = (
        f"；本次返回第 {page_start + 1} - {page_start + len(paged_items)} 条"
        if total_count > 0
        else "；本次返回 0 条"
    )
    note = (
        f"共 {total_count} 个 Compound v3 仓位将在 ETH=${eth_price} 时触发下跌清算"
        f"{page_note}；"
        "仅统计 eth_down_liq_price_usd > 0 且当前尚未进入 is_liquidatable 的仓位；"
        "total_liquidation_usd 采用 min(总债务USD, 模拟价格下 ETH 敏感抵押USD) 估算。"
    )

    return CompoundLiquidationSimResponse(
        version=version,
        simulated_eth_price=_fmt(eth_price),
        positions=paged_items,
        positions_cnt=str(total_count),
        total_eth_sensitive_collateral_usd=_fmt(total_sensitive_collateral_usd),
        total_liquidation_usd=_fmt(total_liquidation_usd),
        note=note,
    )


def _map_market_reserve_row(row: Any) -> MarketStateReserveResponse:
    return MarketStateReserveResponse(
        reserve=_bytea_to_address(row["reserve"]),
        symbol=row["symbol"],
        decimals=row["decimals"],
        total_supply=_fmt(row["total_supply"]),
        total_borrow=_fmt(row["total_borrow"]),
        utilization=_fmt(row["utilization"]),
        borrow_apr=_annualize_rate(row["borrow_rate"]),
        supply_apr=_annualize_rate(row["supply_rate"]),
        price_in_base=(
            _fmt(_row_get(row, "price_in_base"))
            if _row_get(row, "price_in_base") is not None
            else None
        ),
        price_usd=_fmt(row["price_usd"]),
        supply_usd=_fmt(row["supply_usd"]),
        borrow_usd=_fmt(row["borrow_usd"]),
    )


def _map_governance_asset_row(row: Any) -> GovernanceAssetResponse:
    return GovernanceAssetResponse(
        asset=_bytea_to_address(row["asset"]),
        symbol=row["symbol"],
        price_feed=_bytea_to_optional_address(row["price_feed"]),
        decimals=row["decimals"],
        borrow_collateral_factor=_fmt(row["borrow_collateral_factor"]),
        liquidate_collateral_factor=_fmt(row["liquidate_collateral_factor"]),
        liquidation_factor=_fmt(row["liquidation_factor"]),
        supply_cap=_fmt(row["supply_cap"]),
    )


def _map_market_governance_row(
    row: Any, asset_rows: list[Any], *, detail: bool
) -> MarketGovernanceResponse:
    raw_config = _row_get(row, "raw_config_jsonb", {})
    raw_config_dict = raw_config if isinstance(raw_config, dict) else {}
    return MarketGovernanceResponse(
        version="v3",
        market=_bytea_to_address(_require_bytes(_row_get(row, "market"), "market")),
        symbol=_row_get(row, "symbol"),
        effective_timestamp=_timestamp_to_utc_string(
            _row_get(row, "effective_timestamp")
        ),
        block_number=_require_int(_row_get(row, "block_number"), "block_number"),
        config_hash=str(_row_get(row, "config_hash")),
        source=str(raw_config_dict.get("source", "unknown")),
        governor=_bytea_to_optional_address(_row_get(row, "governor")),
        pause_guardian=_bytea_to_optional_address(_row_get(row, "pause_guardian")),
        base_token=_bytea_to_address(
            _require_bytes(_row_get(row, "base_token"), "base_token")
        ),
        base_symbol=_row_get(row, "base_token_symbol"),
        base_token_price_feed=_bytea_to_optional_address(
            _row_get(row, "base_token_price_feed")
        ),
        extension_delegate=_bytea_to_optional_address(
            _row_get(row, "extension_delegate")
        ),
        base_scale=_fmt(_row_get(row, "base_scale")),
        base_decimals=int(_row_get(row, "base_decimals")),
        supply_kink=_fmt(_row_get(row, "supply_kink")),
        borrow_kink=_fmt(_row_get(row, "borrow_kink")),
        supply_per_second_interest_rate_slope_low=_fmt(
            raw_config_dict.get("supply_per_second_interest_rate_slope_low")
        ),
        supply_per_second_interest_rate_slope_high=_fmt(
            raw_config_dict.get("supply_per_second_interest_rate_slope_high")
        ),
        supply_per_second_interest_rate_base=_fmt(
            raw_config_dict.get("supply_per_second_interest_rate_base")
        ),
        supply_per_year_interest_rate_slope_low=_fmt(
            _row_get(row, "supply_per_year_interest_rate_slope_low")
        ),
        supply_per_year_interest_rate_slope_high=_fmt(
            _row_get(row, "supply_per_year_interest_rate_slope_high")
        ),
        supply_per_year_interest_rate_base=_fmt(
            _row_get(row, "supply_per_year_interest_rate_base")
        ),
        borrow_per_second_interest_rate_slope_low=_fmt(
            raw_config_dict.get("borrow_per_second_interest_rate_slope_low")
        ),
        borrow_per_second_interest_rate_slope_high=_fmt(
            raw_config_dict.get("borrow_per_second_interest_rate_slope_high")
        ),
        borrow_per_second_interest_rate_base=_fmt(
            raw_config_dict.get("borrow_per_second_interest_rate_base")
        ),
        borrow_per_year_interest_rate_slope_low=_fmt(
            _row_get(row, "borrow_per_year_interest_rate_slope_low")
        ),
        borrow_per_year_interest_rate_slope_high=_fmt(
            _row_get(row, "borrow_per_year_interest_rate_slope_high")
        ),
        borrow_per_year_interest_rate_base=_fmt(
            _row_get(row, "borrow_per_year_interest_rate_base")
        ),
        store_front_price_factor=_fmt(_row_get(row, "store_front_price_factor")),
        tracking_index_scale=_fmt(_row_get(row, "tracking_index_scale")),
        base_tracking_supply_speed=_fmt(_row_get(row, "base_tracking_supply_speed")),
        base_tracking_borrow_speed=_fmt(_row_get(row, "base_tracking_borrow_speed")),
        base_min_for_rewards=_fmt(_row_get(row, "base_min_for_rewards")),
        base_borrow_min=_fmt(_row_get(row, "base_borrow_min")),
        target_reserves=_fmt(_row_get(row, "target_reserves")),
        assets=(
            [_map_governance_asset_row(item) for item in asset_rows] if detail else None
        ),
    )


def _map_v2_market_config_row(row: Any) -> V2MarketConfigResponse:
    raw_config = _row_get(row, "raw_config_jsonb", {})
    raw_config_dict = raw_config if isinstance(raw_config, dict) else {}
    collateral_factor = raw_config_dict.get("collateral_factor")
    if collateral_factor is None:
        collateral_factor = _row_get(row, "collateral_factor")
    reserve_factor = raw_config_dict.get("reserve_factor")
    if reserve_factor is None:
        reserve_factor = _row_get(row, "reserve_factor")
    borrow_cap = raw_config_dict.get("borrow_cap")
    if borrow_cap is None:
        borrow_cap = _row_get(row, "borrow_cap")
    supply_cap = raw_config_dict.get("supply_cap")
    if supply_cap is None:
        supply_cap = _row_get(row, "supply_cap")
    is_listed = raw_config_dict.get("is_listed")
    if is_listed is None:
        is_listed = _row_get(row, "is_listed")
    is_comped = raw_config_dict.get("is_comped")
    if is_comped is None:
        is_comped = _row_get(row, "is_comped")
    is_deprecated = raw_config_dict.get("is_deprecated")
    if is_deprecated is None:
        is_deprecated = _row_get(row, "is_deprecated")

    return V2MarketConfigResponse(
        version="v2",
        market=_bytea_to_address(_require_bytes(_row_get(row, "market"), "market")),
        symbol=_row_get(row, "symbol"),
        effective_timestamp=_timestamp_to_utc_string(
            _row_get(row, "effective_timestamp")
        ),
        block_number=_require_int(_row_get(row, "block_number"), "block_number"),
        config_hash=str(_row_get(row, "config_hash")),
        comptroller=_bytea_to_optional_address(_row_get(row, "comptroller")),
        interest_rate_model=_bytea_to_optional_address(
            _row_get(row, "interest_rate_model")
        ),
        underlying=_bytea_to_optional_address(_row_get(row, "underlying")),
        underlying_symbol=_row_get(row, "underlying_symbol"),
        ctoken_decimals=_row_get(row, "ctoken_decimals"),
        underlying_decimals=_row_get(row, "underlying_decimals"),
        collateral_factor=_fmt_optional(collateral_factor),
        reserve_factor=_fmt_optional(reserve_factor),
        liquidation_threshold=_fmt_optional(_row_get(row, "liquidation_threshold")),
        borrow_cap=_fmt_optional(borrow_cap),
        supply_cap=_fmt_optional(supply_cap),
        is_listed=bool(is_listed),
        is_comped=bool(is_comped),
        is_deprecated=bool(is_deprecated),
        comp_supply_speed_raw=(
            str(raw_config_dict.get("comp_supply_speed_raw"))
            if raw_config_dict.get("comp_supply_speed_raw") is not None
            else None
        ),
        comp_borrow_speed_raw=(
            str(raw_config_dict.get("comp_borrow_speed_raw"))
            if raw_config_dict.get("comp_borrow_speed_raw") is not None
            else None
        ),
        exchange_rate_raw=(
            str(raw_config_dict.get("exchange_rate_raw"))
            if raw_config_dict.get("exchange_rate_raw") is not None
            else None
        ),
        exchange_rate=(
            _fmt_optional(raw_config_dict.get("exchange_rate"))
            if raw_config_dict.get("exchange_rate") is not None
            else None
        ),
        protocol_config_hash=(
            str(raw_config_dict.get("protocol_config_hash"))
            if raw_config_dict.get("protocol_config_hash")
            else None
        ),
        mint_paused=(
            bool(raw_config_dict.get("mint_paused"))
            if "mint_paused" in raw_config_dict
            else None
        ),
        borrow_paused=(
            bool(raw_config_dict.get("borrow_paused"))
            if "borrow_paused" in raw_config_dict
            else None
        ),
    )


def _map_v2_protocol_config_row(row: Any) -> V2ProtocolConfigResponse:
    return V2ProtocolConfigResponse(
        version="v2",
        effective_timestamp=_timestamp_to_utc_string(
            _row_get(row, "effective_timestamp")
        ),
        block_number=_require_int(_row_get(row, "block_number"), "block_number"),
        config_hash=str(_row_get(row, "config_hash")),
        comptroller=_bytea_to_address(
            _require_bytes(_row_get(row, "comptroller"), "comptroller")
        ),
        price_oracle=_bytea_to_optional_address(_row_get(row, "price_oracle")),
        close_factor=_fmt_optional(_row_get(row, "close_factor")),
        liquidation_incentive=_fmt_optional(_row_get(row, "liquidation_incentive")),
        pause_guardian=_bytea_to_optional_address(_row_get(row, "pause_guardian")),
        transfer_paused=bool(_row_get(row, "transfer_paused")),
        seize_paused=bool(_row_get(row, "seize_paused")),
        mint_paused=bool(_row_get(row, "mint_paused")),
        borrow_paused=bool(_row_get(row, "borrow_paused")),
    )


async def _fetch_position_rows(
    pool,
    *,
    position_table: str,
    point_ts: datetime,
    market_bytes_list: list[bytes],
    user_address: bytes,
) -> list[Any]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                "timestamp",
                block_number,
                market,
                symbol,
                user_address,
                has_open_position,
                is_liquidatable,
                base_token,
                base_symbol,
                base_price_usd,
                eth_price_usd,
                total_collateral_usd,
                total_debt_usd,
                discounted_collateral_usd,
                liquidation_buffer_usd,
                health_factor,
                eth_sensitive_collateral_usd,
                eth_sensitive_debt_usd,
                net_eth_exposure_usd,
                non_eth_collateral_usd,
                non_eth_debt_usd,
                basis_risk_collateral_usd,
                eth_down_liq_price_usd,
                eth_up_liq_price_usd,
                eth_liq_mode,
                dominant_risk,
                assets_jsonb
            FROM loan.{position_table}
            WHERE "timestamp" = $1
              AND market = ANY($2::bytea[])
              AND user_address = $3
              AND has_open_position = TRUE
            ORDER BY is_liquidatable DESC, liquidation_buffer_usd ASC,
                     total_debt_usd DESC, market
            """,
            point_ts,
            market_bytes_list,
            user_address,
        )
    return list(rows)


async def _fetch_latest_position_rows(
    pool,
    *,
    position_table: str,
    market_bytes_list: list[bytes],
    user_address: bytes,
) -> list[Any]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT DISTINCT ON (market)
                "timestamp",
                block_number,
                market,
                symbol,
                user_address,
                has_open_position,
                is_liquidatable,
                base_token,
                base_symbol,
                base_price_usd,
                eth_price_usd,
                total_collateral_usd,
                total_debt_usd,
                discounted_collateral_usd,
                liquidation_buffer_usd,
                health_factor,
                eth_sensitive_collateral_usd,
                eth_sensitive_debt_usd,
                net_eth_exposure_usd,
                non_eth_collateral_usd,
                non_eth_debt_usd,
                basis_risk_collateral_usd,
                eth_down_liq_price_usd,
                eth_up_liq_price_usd,
                eth_liq_mode,
                dominant_risk,
                assets_jsonb
            FROM loan.{position_table}
            WHERE market = ANY($1::bytea[])
              AND user_address = $2
              AND has_open_position = TRUE
            ORDER BY market, "timestamp" DESC, block_number DESC
            """,
            market_bytes_list,
            user_address,
        )
    return list(rows)


def _user_position_table(version: str) -> str:
    table = _USER_POSITION_TABLES.get(version.lower())
    if table is None:
        raise HTTPException(status_code=400, detail="version 仅支持 v2 或 v3")
    return table


async def get_market_state(
    pool,
    version: str,
    market: str,
    date: str,
    detail: bool,
) -> MarketStateResponse:
    version = version.lower()
    if version not in ("v2", "v3"):
        raise HTTPException(status_code=400, detail="version 仅支持 v2 或 v3")

    point_ts = _parse_hour_utc(date)
    market_address = _market_to_address(version, market)
    market_bytes = _address_to_bytes(market_address)

    market_table = market_table_name(version)
    reserve_table = reserve_table_name(version)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT
                "timestamp",
                market,
                symbol,
                total_supply,
                total_borrow,
                collateral_usd,
                utilization,
                borrow_rate,
                supply_rate,
                price_usd,
                supply_usd,
                borrow_usd
            FROM loan.{market_table}
            WHERE "timestamp" = $1
              AND market = $2
            LIMIT 1
            """,
            point_ts,
            market_bytes,
        )

        if row is None:
            raise HTTPException(status_code=404, detail="未找到该时刻的 market state")

        reserves: list[MarketStateReserveResponse] | None = None
        if detail:
            price_in_base_select = (
                "price_in_base" if version == "v3" else "NULL::numeric AS price_in_base"
            )
            reserve_rows = await conn.fetch(
                f"""
                SELECT
                    reserve,
                    symbol,
                    decimals,
                    total_supply,
                    total_borrow,
                    utilization,
                    borrow_rate,
                    supply_rate,
                    {price_in_base_select},
                    price_usd,
                    supply_usd,
                    borrow_usd
                FROM loan.{reserve_table}
                WHERE "timestamp" = $1
                  AND market = $2
                ORDER BY symbol NULLS LAST, reserve
                """,
                point_ts,
                market_bytes,
            )
            reserves = [_map_market_reserve_row(item) for item in reserve_rows]

    return MarketStateResponse(
        version=version,
        market=_bytea_to_address(row["market"]),
        symbol=row["symbol"],
        timestamp=_timestamp_to_utc_string(row["timestamp"]),
        total_supply=_fmt(row["total_supply"]),
        total_borrow=_fmt(row["total_borrow"]),
        collateral_usd=_fmt(row["collateral_usd"]),
        utilization=_fmt(row["utilization"]),
        borrow_apr=_annualize_rate(row["borrow_rate"]),
        supply_apr=_annualize_rate(row["supply_rate"]),
        price_usd=_fmt(row["price_usd"]),
        supply_usd=_fmt(row["supply_usd"]),
        borrow_usd=_fmt(row["borrow_usd"]),
        reserves=reserves,
    )


def _market_name_map(version: str) -> dict[str, str]:
    return COMPOUND_V2_MARKET_NAMES if version == "v2" else COMPOUND_V3_MARKET_NAMES


def _configured_market_addresses(version: str) -> list[str]:
    app_cfg = load_config()
    cfg = getattr(app_cfg, "market_state", None)
    if cfg is None:
        return []
    raw = cfg.v2_markets if version == "v2" else cfg.v3_markets
    return [
        item.strip().lower() for item in raw if isinstance(item, str) and item.strip()
    ]


def _available_market_addresses(version: str) -> list[str]:
    configured = _configured_market_addresses(version)
    if configured:
        return list(dict.fromkeys(configured))
    return list(_market_name_map(version).keys())
