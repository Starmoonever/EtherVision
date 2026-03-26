"""Backfill Compound event-driven position snapshots for one user address."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from crawler_shared.logging import setup_cli_logging
from web3 import AsyncWeb3

from compound_crawler.config import load_config
from compound_crawler.constants import (
    COMPOUND_V2_MARKET_NAMES,
    COMPOUND_V3_MARKET_NAMES,
    CTOKEN_V2_ABI,
    COMPTROLLER_V2_ABI,
)
from compound_crawler.crawler import (
    COMET_FACTOR_SCALE,
    ETH_USD_PRICE_FEED,
    WETH_MAINNET,
    _build_web3,
    _price_from_feed_direct,
    _token_metadata,
    _v2_underlying_price_usd,
    close_web3,
)
from compound_crawler.db import (
    CompoundEventPositionSnapshotRow,
    create_pool,
    ensure_compound_event_snapshot_table,
    fetch_compound_cached_event_keys,
    fetch_compound_user_tx_history,
    upsert_compound_event_snapshots,
)
from compound_crawler.user_position_snapshots import (
    _collect_user_snapshots_batch,
    _load_market_context,
    _parse_utc_time,
)

logger = logging.getLogger(__name__)

DEFAULT_START = "2020-01-01"
POSITION_METHOD_IDS: dict[str, set[str]] = {
    "v2": {
        "a0712d68",  # mint(uint256)
        "db006a75",  # redeem(uint256)
        "852a12e3",  # redeem
        "c5ebeaec",  # borrow(uint256)
        "0e752702",  # repayBorrow(uint256)
        "2608f818",  # repayBorrowBehalf(address,uint256)
        "f5e3c462",  # liquidateBorrow(address,uint256,address)
    },
    "v3": {
        "f3fef3a3",  # supply
        "c3b35a7e",  # supplyTo
        "f2b9fdb8",  # withdraw
        "4232cd63",  # buyCollateral
        "c3cecfd2",  # absorb
    },
}
METHOD_BRIEF_MAP: dict[str, dict[str, str]] = {
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
SELF_IMPACT_METHOD_IDS: dict[str, set[str]] = {
    "v2": {
        "a0712d68",  # mint(uint256)
        "db006a75",  # redeem(uint256)
        "852a12e3",  # redeem
        "c5ebeaec",  # borrow(uint256)
        "0e752702",  # repayBorrow(uint256)
    },
    "v3": {
        "f3fef3a3",  # supply
        "f2b9fdb8",  # withdraw
    },
}
ETH_CORRELATED_SYMBOLS = {"ETH", "WETH", "WSTETH", "RETH", "CBETH"}
MAX_HF = Decimal("1e18")
CTOKEN_V2_USER_ABI = [
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
COMPTROLLER_V2_USER_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "getAssetsIn",
        "outputs": [{"internalType": "address[]", "name": "", "type": "address[]"}],
        "stateMutability": "view",
        "type": "function",
    },
]
COMPTROLLER_V2_MARKETS_LEGACY_ABI = [
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


@dataclass
class UserTxEvent:
    tx_hash: str
    block_number: int
    block_timestamp: datetime
    market: str
    method_id: str | None


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_address_bytes(user_address: str) -> bytes:
    value = user_address.strip().lower()
    if not value.startswith("0x") or len(value) != 42:
        raise ValueError(f"invalid address: {user_address}")
    return bytes.fromhex(value[2:])


def _normalize_hex_address(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("0x") and len(text) == 42:
            return text.lower()
        return None
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)) and len(value) == 20:
        return "0x" + bytes(value).hex()
    return None


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
        return text if len(text) == 8 else None
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if not raw:
            return None
        return raw.hex()[:8].lower()
    return None


def _is_position_method(protocol: str, method_id: str | None) -> bool:
    if method_id is None:
        return False
    return method_id in POSITION_METHOD_IDS.get(protocol, set())


def _is_self_impact_method(protocol: str, method_id: str | None) -> bool:
    if method_id is None:
        return False
    return method_id in SELF_IMPACT_METHOD_IDS.get(protocol, set())


async def _load_v2_accrued_balances(
    ctoken: Any,
    *,
    user_checksum: str,
    block_number: int,
) -> tuple[int, int, int]:
    balance_raw = int(
        await ctoken.functions.balanceOf(user_checksum).call(
            block_identifier=block_number
        )
    )

    try:
        borrow_raw, exchange_rate_raw = await asyncio.gather(
            ctoken.functions.borrowBalanceCurrent(user_checksum).call(
                block_identifier=block_number
            ),
            ctoken.functions.exchangeRateCurrent().call(block_identifier=block_number),
        )
    except Exception:
        borrow_raw, exchange_rate_raw = await asyncio.gather(
            ctoken.functions.borrowBalanceStored(user_checksum).call(
                block_identifier=block_number
            ),
            ctoken.functions.exchangeRateStored().call(block_identifier=block_number),
        )

    return balance_raw, int(borrow_raw), int(exchange_rate_raw)


def _market_symbol(protocol: str, market: bytes) -> str:
    address = "0x" + market.hex()
    if protocol == "v2":
        return COMPOUND_V2_MARKET_NAMES.get(address, address)
    return COMPOUND_V3_MARKET_NAMES.get(address, address)


def _format_compound_brief(
    protocol: str,
    action: str,
    symbol: str,
    *,
    amount: Decimal | None = None,
) -> str:
    base = (
        f"{action} {_fmt_amount(amount)} {symbol}"
        if amount is not None
        else f"{action} {symbol}"
    )
    if protocol == "v3":
        return f"{base} @{symbol}"
    return base


def _fmt_amount(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def _chunked[T](items: list[T], size: int) -> list[list[T]]:
    if size <= 0:
        raise ValueError("chunk size must be > 0")
    return [items[i : i + size] for i in range(0, len(items), size)]


def _resolve_v3_market_filter(market: str) -> str | None:
    value = market.strip().lower()
    if value == "all":
        return None
    if value.startswith("0x") and len(value) == 42:
        return value
    for addr, symbol in COMPOUND_V3_MARKET_NAMES.items():
        if symbol.lower() == value:
            return addr
    raise ValueError(f"unknown v3 market: {market}")


def _resolve_v2_market_filter(market: str) -> str | None:
    value = market.strip().lower()
    if value == "all":
        return None
    if value.startswith("0x") and len(value) == 42:
        return value
    for addr, symbol in COMPOUND_V2_MARKET_NAMES.items():
        if symbol.lower() == value:
            return addr
    raise ValueError(f"unknown v2 market: {market}")


async def _collect_v2_account_snapshot_row(
    w3: Any,
    *,
    user_address: bytes,
    event_market: str,
    block_number: int,
    point_ts: datetime,
    metadata_cache: dict[str, tuple[str | None, int | None]],
) -> CompoundEventPositionSnapshotRow:
    user_checksum = AsyncWeb3.to_checksum_address("0x" + user_address.hex())
    market_addresses = list(COMPOUND_V2_MARKET_NAMES.keys())
    event_market_lc = event_market.lower()

    first_market = event_market_lc
    first_ctoken = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(first_market),
        abi=CTOKEN_V2_ABI,
    )
    comptroller_address = await first_ctoken.functions.comptroller().call(
        block_identifier=block_number
    )
    comptroller = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(str(comptroller_address)),
        abi=COMPTROLLER_V2_ABI + COMPTROLLER_V2_USER_ABI,
    )
    assets_in = await comptroller.functions.getAssetsIn(user_checksum).call(
        block_identifier=block_number
    )
    collateral_markets = {str(addr).lower() for addr in assets_in}

    market_rows: list[dict[str, Any]] = []
    legacy_comptroller = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(str(comptroller_address)),
        abi=COMPTROLLER_V2_MARKETS_LEGACY_ABI,
    )
    for market in market_addresses:
        market_checksum = AsyncWeb3.to_checksum_address(market)
        code = await w3.eth.get_code(market_checksum, block_identifier=block_number)
        if not code:
            continue
        ctoken = w3.eth.contract(address=market_checksum, abi=CTOKEN_V2_USER_ABI)
        ctoken_meta = w3.eth.contract(address=market_checksum, abi=CTOKEN_V2_ABI)
        symbol = COMPOUND_V2_MARKET_NAMES.get(market, market)

        try:
            underlying = await ctoken_meta.functions.underlying().call(
                block_identifier=block_number
            )
            underlying_symbol, underlying_dec_meta = await _token_metadata(
                w3, str(underlying), block_number, metadata_cache
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
            )
        except Exception:
            if underlying_address.lower() == WETH_MAINNET.lower():
                price_usd = await _price_from_feed_direct(
                    w3, ETH_USD_PRICE_FEED, block_number
                )
            else:
                price_usd = Decimal("0")

        balance_raw, borrow_raw, exchange_rate_raw = await _load_v2_accrued_balances(
            ctoken,
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
                "market": market,
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

    if not market_rows:
        raise RuntimeError(f"no deployed v2 markets at block={block_number}")

    eth_price_usd = Decimal("0")
    for row in market_rows:
        if (
            row["underlying_symbol"]
            and str(row["underlying_symbol"]).upper() in ETH_CORRELATED_SYMBOLS
        ):
            eth_price_usd = row["price_usd"]
            break
    if eth_price_usd <= 0:
        eth_price_usd = await _price_from_feed_direct(
            w3, ETH_USD_PRICE_FEED, block_number
        )

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

    for row in market_rows:
        supply_usd = row["supply"] * row["price_usd"]
        borrow_usd = row["borrow"] * row["price_usd"]
        discounted_usd = (
            supply_usd * row["collateral_factor"]
            if row["is_collateral"]
            else Decimal("0")
        )
        is_eth_corr = str(row["underlying_symbol"]).upper() in ETH_CORRELATED_SYMBOLS
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
                        if row["market"].lower() == event_market_lc
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
        MAX_HF if total_debt_usd <= 0 else discounted_collateral_usd / total_debt_usd
    )
    net_eth_exposure_usd = eth_sensitive_collateral_usd - eth_sensitive_debt_usd
    basis_risk_collateral_usd = Decimal("0")
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
        (row for row in market_rows if row["market"].lower() == event_market_lc),
        None,
    )
    if event_market_row is None:
        logger.warning(
            "event market not deployed at block, fallback base token to WETH: market=%s block=%s",
            event_market_lc,
            block_number,
        )
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
        market=bytes.fromhex(event_market_lc[2:]),
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
        basis_risk_collateral_usd=basis_risk_collateral_usd,
        eth_down_liq_price_usd=eth_down_liq_price_usd,
        eth_up_liq_price_usd=eth_up_liq_price_usd,
        eth_liq_mode=eth_liq_mode,
        dominant_risk=dominant_risk,
        assets_jsonb=assets_jsonb,
        brief="",
    )


def _row_to_event(
    row: Any,
    *,
    protocol: str,
    market_filter: str | None,
    only_position_ops: bool,
) -> UserTxEvent | None:
    market = _normalize_hex_address(row.get("market"))
    if market is None:
        return None
    if market_filter is not None and market != market_filter:
        return None

    tx_hash = _normalize_tx_hash(row.get("tx_hash"))
    if tx_hash is None:
        return None
    method_id = _normalize_method_id(row.get("method_id"))
    if only_position_ops and not _is_position_method(protocol, method_id):
        return None

    block_number = int(row["block_number"])
    block_timestamp = _to_utc(row["block_timestamp"])
    return UserTxEvent(
        tx_hash=tx_hash,
        block_number=block_number,
        block_timestamp=block_timestamp,
        market=market,
        method_id=method_id,
    )


def _snapshot_to_event_row(
    snapshot: Any,
    *,
    protocol: str,
    tx_hash: str,
    block_timestamp: datetime,
    brief: str,
) -> CompoundEventPositionSnapshotRow:
    return CompoundEventPositionSnapshotRow(
        user_address=snapshot.user_address,
        protocol=protocol,
        market=snapshot.market,
        symbol=snapshot.symbol,
        block_number=snapshot.block_number,
        tx_hash=tx_hash,
        block_timestamp=block_timestamp,
        has_open_position=snapshot.has_open_position,
        is_liquidatable=snapshot.is_liquidatable,
        base_token=snapshot.base_token,
        base_symbol=snapshot.base_symbol,
        base_price_usd=snapshot.base_price_usd,
        eth_price_usd=snapshot.eth_price_usd,
        total_collateral_usd=snapshot.total_collateral_usd,
        total_debt_usd=snapshot.total_debt_usd,
        discounted_collateral_usd=snapshot.discounted_collateral_usd,
        liquidation_buffer_usd=snapshot.liquidation_buffer_usd,
        health_factor=snapshot.health_factor,
        eth_sensitive_collateral_usd=snapshot.eth_sensitive_collateral_usd,
        eth_sensitive_debt_usd=snapshot.eth_sensitive_debt_usd,
        net_eth_exposure_usd=snapshot.net_eth_exposure_usd,
        non_eth_collateral_usd=snapshot.non_eth_collateral_usd,
        non_eth_debt_usd=snapshot.non_eth_debt_usd,
        basis_risk_collateral_usd=snapshot.basis_risk_collateral_usd,
        eth_down_liq_price_usd=snapshot.eth_down_liq_price_usd,
        eth_up_liq_price_usd=snapshot.eth_up_liq_price_usd,
        eth_liq_mode=snapshot.eth_liq_mode,
        dominant_risk=snapshot.dominant_risk,
        assets_jsonb=snapshot.assets_jsonb,
        brief=brief,
    )


async def _load_briefs_from_detail_tables(
    pool: Any,
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

        liq_rows = await conn.fetch(
            """
            SELECT tx_hash, market_address, borrower, liquidator
            FROM compound.compound_liquidate
            WHERE version = $1
              AND tx_hash = ANY($2::bytea[])
              AND (borrower = $3 OR liquidator = $3)
            """,
            version_int,
            tx_hashes,
            user_address,
        )
        for row in liq_rows:
            txh = "0x" + bytes(row["tx_hash"]).hex()
            symbol = _market_symbol(protocol, bytes(row["market_address"]))
            role = "被清算" if bytes(row["borrower"]) == user_address else "执行清算"
            brief_map[txh] = _format_compound_brief(protocol, role, symbol)
    return brief_map


def _fallback_brief(event: UserTxEvent, protocol: str, market: bytes) -> str:
    action = METHOD_BRIEF_MAP.get(protocol, {}).get(event.method_id or "", "仓位操作")
    return _format_compound_brief(protocol, action, _market_symbol(protocol, market))


async def _collect_event_rows_for_user(
    *,
    address: bytes,
    protocol: str,
    market_filter: str | None,
    from_dt: datetime,
    to_dt: datetime,
    dry_run: bool,
    write_batch_size: int,
    config_path: str | None,
    only_position_ops: bool,
    rpc_concurrency: int,
) -> None:
    cfg = load_config(config_path)
    cfg.protocol = protocol

    pool = await create_pool(cfg.postgres)
    w3 = None
    try:
        await ensure_compound_event_snapshot_table(pool)
        tx_rows = await fetch_compound_user_tx_history(
            pool,
            user_address=address,
            protocol=protocol,
            from_dt=from_dt,
            to_dt=to_dt,
            market=(bytes.fromhex(market_filter[2:]) if market_filter else None),
            user_column="from_address",
        )
        events = [
            event
            for row in tx_rows
            if (
                event := _row_to_event(
                    row,
                    protocol=protocol,
                    market_filter=market_filter,
                    only_position_ops=only_position_ops,
                )
            )
            is not None
        ]
        if not events:
            other_protocol = "v2" if protocol == "v3" else "v3"
            other_rows = await fetch_compound_user_tx_history(
                pool,
                user_address=address,
                protocol=other_protocol,
                from_dt=from_dt,
                to_dt=to_dt,
                market=None,
            )
            logger.info(
                "No tx events found for protocol=%s in selected range. address=0x%s",
                protocol,
                address.hex(),
            )
            logger.info(
                "Address tx count hint: protocol=%s count=%s, protocol=%s count=%s",
                protocol,
                len(tx_rows),
                other_protocol,
                len(other_rows),
            )
            return

        grouped: dict[tuple[str, int], list[UserTxEvent]] = defaultdict(list)
        for event in events:
            grouped[(event.market, event.block_number)].append(event)

        cached_keys = await fetch_compound_cached_event_keys(
            pool,
            user_address=address,
            protocol=protocol,
            from_dt=from_dt,
            to_dt=to_dt,
            market=(bytes.fromhex(market_filter[2:]) if market_filter else None),
        )
        if cached_keys:
            before = len(events)
            events = [
                event
                for event in events
                if (
                    bytes.fromhex(event.market[2:]),
                    event.tx_hash.lower(),
                )
                not in cached_keys
            ]
            if len(events) != before:
                logger.info(
                    "Skip cached tx rows: skipped=%s remaining=%s",
                    before - len(events),
                    len(events),
                )
            if not events:
                logger.info("All tx rows already cached, nothing to do.")
                return

        tx_hash_bytes = [bytes.fromhex(event.tx_hash[2:]) for event in events]
        brief_map = await _load_briefs_from_detail_tables(
            pool,
            protocol=protocol,
            user_address=address,
            tx_hashes=tx_hash_bytes,
        )
        before_impact_filter = len(events)
        events = [
            event
            for event in events
            if _is_self_impact_method(protocol, event.method_id)
        ]
        if len(events) != before_impact_filter:
            logger.info(
                "Filtered non-impact tx rows: dropped=%s remaining=%s",
                before_impact_filter - len(events),
                len(events),
            )
        if not events:
            logger.info("No position-impact tx events remain after impact filter.")
            return

        grouped = defaultdict(list)
        for event in events:
            grouped[(event.market, event.block_number)].append(event)

        logger.info(
            "Loaded tx events: total=%s grouped_points=%s",
            len(events),
            len(grouped),
        )

        w3 = await _build_web3(cfg)
        metadata_cache: dict[str, tuple[str | None, int | None]] = {}
        pending_rows: list[CompoundEventPositionSnapshotRow] = []
        processed_points = 0
        inserted = 0
        user_addresses = [address]
        point_items = sorted(grouped.items())
        sem = asyncio.Semaphore(max(1, rpc_concurrency))

        async def _process_point(
            point_item: tuple[tuple[str, int], list[UserTxEvent]],
        ) -> list[CompoundEventPositionSnapshotRow]:
            (market, block_number), event_group = point_item
            async with sem:
                if protocol == "v3":
                    market_ctx = await _load_market_context(
                        w3,
                        market_address=market,
                        block_number=block_number,
                        metadata_cache=metadata_cache,
                    )
                    batch_rows = await _collect_user_snapshots_batch(
                        w3,
                        market_ctx,
                        user_addresses=user_addresses,
                        point_ts=event_group[0].block_timestamp,
                        block_number=block_number,
                    )
                    if not batch_rows:
                        return []
                    snapshot_row, _ = batch_rows[0]
                    return [
                        _snapshot_to_event_row(
                            snapshot_row,
                            protocol=protocol,
                            tx_hash=event.tx_hash,
                            block_timestamp=event.block_timestamp,
                            brief=brief_map.get(
                                event.tx_hash,
                                _fallback_brief(event, protocol, snapshot_row.market),
                            ),
                        )
                        for event in event_group
                    ]

                v2_row = await _collect_v2_account_snapshot_row(
                    w3,
                    user_address=address,
                    event_market=market,
                    block_number=block_number,
                    point_ts=event_group[0].block_timestamp,
                    metadata_cache=metadata_cache,
                )
                return [
                    CompoundEventPositionSnapshotRow(
                        user_address=v2_row.user_address,
                        protocol=v2_row.protocol,
                        market=v2_row.market,
                        symbol=v2_row.symbol,
                        block_number=v2_row.block_number,
                        tx_hash=event.tx_hash,
                        block_timestamp=event.block_timestamp,
                        has_open_position=v2_row.has_open_position,
                        is_liquidatable=v2_row.is_liquidatable,
                        base_token=v2_row.base_token,
                        base_symbol=v2_row.base_symbol,
                        base_price_usd=v2_row.base_price_usd,
                        eth_price_usd=v2_row.eth_price_usd,
                        total_collateral_usd=v2_row.total_collateral_usd,
                        total_debt_usd=v2_row.total_debt_usd,
                        discounted_collateral_usd=v2_row.discounted_collateral_usd,
                        liquidation_buffer_usd=v2_row.liquidation_buffer_usd,
                        health_factor=v2_row.health_factor,
                        eth_sensitive_collateral_usd=v2_row.eth_sensitive_collateral_usd,
                        eth_sensitive_debt_usd=v2_row.eth_sensitive_debt_usd,
                        net_eth_exposure_usd=v2_row.net_eth_exposure_usd,
                        non_eth_collateral_usd=v2_row.non_eth_collateral_usd,
                        non_eth_debt_usd=v2_row.non_eth_debt_usd,
                        basis_risk_collateral_usd=v2_row.basis_risk_collateral_usd,
                        eth_down_liq_price_usd=v2_row.eth_down_liq_price_usd,
                        eth_up_liq_price_usd=v2_row.eth_up_liq_price_usd,
                        eth_liq_mode=v2_row.eth_liq_mode,
                        dominant_risk=v2_row.dominant_risk,
                        assets_jsonb=v2_row.assets_jsonb,
                        brief=brief_map.get(
                            event.tx_hash,
                            _fallback_brief(event, protocol, v2_row.market),
                        ),
                    )
                    for event in event_group
                ]

        submit_batch_size = max(rpc_concurrency * 4, rpc_concurrency)
        for point_batch in _chunked(point_items, submit_batch_size):
            tasks = [asyncio.create_task(_process_point(item)) for item in point_batch]
            for task in asyncio.as_completed(tasks):
                rows = await task
                processed_points += 1
                if not rows:
                    continue
                pending_rows.extend(rows)
                if len(pending_rows) >= write_batch_size:
                    if dry_run:
                        logger.info("dry-run flush rows=%s", len(pending_rows))
                    else:
                        inserted += await upsert_compound_event_snapshots(
                            pool, pending_rows
                        )
                    pending_rows = []

        if pending_rows:
            if dry_run:
                logger.info("dry-run final flush rows=%s", len(pending_rows))
            else:
                inserted += await upsert_compound_event_snapshots(pool, pending_rows)

        if dry_run:
            logger.info(
                "Done (dry-run): grouped_points=%s event_rows=%s",
                processed_points,
                len(events),
            )
        else:
            logger.info(
                "Done: grouped_points=%s inserted_rows=%s",
                processed_points,
                inserted,
            )
    finally:
        await close_web3(w3)
        await pool.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", required=True, help="user address (0x...)")
    parser.add_argument(
        "--protocol",
        default="v3",
        choices=["v2", "v3"],
        help="compound protocol version",
    )
    parser.add_argument(
        "--market",
        default="all",
        help="v3 market symbol/address (e.g. WETH, USDC, 0x...), or all",
    )
    parser.add_argument(
        "--start", default=DEFAULT_START, help="UTC start datetime/date"
    )
    parser.add_argument("--end", default=None, help="UTC end datetime/date")
    parser.add_argument("--config", default=None, help="config.yaml path")
    parser.add_argument(
        "--write-batch-size",
        type=int,
        default=500,
        help="upsert batch size",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="collect only, do not write",
    )
    parser.add_argument(
        "--include-non-position",
        action="store_true",
        default=False,
        help="include non position-impacting methods",
    )
    parser.add_argument(
        "--rpc-concurrency",
        type=int,
        default=8,
        help="max concurrent RPC point collection workers",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="enable DEBUG logging",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    setup_cli_logging(args.verbose)

    address = _parse_address_bytes(args.address)
    start = _parse_utc_time(args.start)
    end = _parse_utc_time(args.end) if args.end else datetime.now(timezone.utc)
    if start > end:
        raise SystemExit("--start must be <= --end")
    if args.write_batch_size <= 0:
        raise SystemExit("--write-batch-size must be > 0")
    if args.rpc_concurrency <= 0:
        raise SystemExit("--rpc-concurrency must be > 0")

    market_filter = None
    if args.protocol == "v3":
        market_filter = _resolve_v3_market_filter(args.market)
    else:
        market_filter = _resolve_v2_market_filter(args.market)

    asyncio.run(
        _collect_event_rows_for_user(
            address=address,
            protocol=args.protocol,
            market_filter=market_filter,
            from_dt=start,
            to_dt=end,
            dry_run=args.dry_run,
            write_batch_size=args.write_batch_size,
            config_path=args.config,
            only_position_ops=not args.include_non_position,
            rpc_concurrency=args.rpc_concurrency,
        )
    )


if __name__ == "__main__":
    main()
