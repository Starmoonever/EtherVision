"""Backfill Compound v3 user position snapshots focused on liquidation metrics."""

from __future__ import annotations

import ast
import asyncio
import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
from eth_abi.abi import decode as _abi_decode
from web3 import AsyncWeb3

from aave_crawler.rpc import MULTICALL3_ABI, MULTICALL3_ADDRESS, MULTICALL3_DEPLOY_BLOCK
from .config import AppConfig
from .constants import COMET_ABI, COMPOUND_V3_MARKET_NAMES
from .crawler import (
    _base_token_usd_price,
    _block_at_timestamp,
    _build_web3,
    close_web3,
    _price_from_feed_direct,
    _price_from_oracle,
    _scale_to_decimals,
    _to_bytes,
    _token_metadata,
    ETH_USD_PRICE_FEED,
)
from .db import (
    UserPositionAssetRow,
    UserPositionSnapshotRow,
    ensure_user_position_snapshot_tables,
    fetch_existing_user_position_addresses,
    upsert_user_position_asset_rows,
    upsert_user_position_snapshots,
)

logger = logging.getLogger(__name__)

MIN_INTERVAL_DAYS = 1
INF_HEALTH_FACTOR = Decimal("1e18")
ZERO = Decimal("0")
ONE = Decimal("1")
_UINT256_OUTPUT = ["uint256"]
_USER_COLLATERAL_OUTPUT = ["uint128", "uint128"]
ETH_CORRELATED_SYMBOLS = frozenset(
    {
        "ETH",
        "WETH",
        "CBETH",
        "WSTETH",
        "RETH",
        "WEETH",
        "EZETH",
        "RSETH",
        "OSETH",
        "ETHX",
    }
)
MARKET_CONTEXT_RPC_CONCURRENCY = 8


@dataclass
class AssetContext:
    address: str
    symbol: str | None
    decimals: int
    price_in_base: Decimal
    price_usd: Decimal
    borrow_collateral_factor: Decimal
    liquidate_collateral_factor: Decimal
    liquidation_factor: Decimal
    beta_to_eth: Decimal
    is_eth_correlated: bool


@dataclass
class MarketContext:
    market_address: str
    market_symbol: str
    comet: Any
    base_token: str
    base_symbol: str | None
    base_decimals: int
    base_price_usd: Decimal
    eth_price_usd: Decimal
    assets: list[AssetContext]


@dataclass
class BackfillStats:
    snapshots: int = 0
    assets: int = 0
    skipped_existing: int = 0
    skipped_empty: int = 0


@dataclass
class CollectedMarketSnapshots:
    timestamp: datetime
    block_number: int
    market: str
    symbol: str
    snapshots: list[UserPositionSnapshotRow]


def _normalize_market_name(name: str) -> str:
    return name.strip().lower()


def _resolve_market_address(market: str) -> str:
    normalized = market.strip().lower()
    if normalized.startswith("0x") and len(normalized) == 42:
        for address in COMPOUND_V3_MARKET_NAMES:
            if address.lower() == normalized:
                return address.lower()
        raise ValueError(f"unknown market: {market}")

    for address, name in COMPOUND_V3_MARKET_NAMES.items():
        if name.lower() == normalized:
            return address
    raise ValueError(f"unknown market: {market}")


def available_csv_markets(base_dir: Path) -> list[str]:
    markets: list[str] = []
    for path in sorted(base_dir.glob("compound_v3_*_users.csv")):
        stem = path.stem
        prefix = "compound_v3_"
        suffix = "_users"
        if stem.startswith(prefix) and stem.endswith(suffix):
            markets.append(stem[len(prefix) : -len(suffix)])
    return markets


def parse_csv_address_cell(value: str) -> bytes:
    text = value.strip()
    if not text:
        raise ValueError("empty address cell")
    if text.startswith("0x"):
        return bytes.fromhex(text[2:].lower())

    parsed = ast.literal_eval(text)
    if isinstance(parsed, str) and parsed.startswith("0x"):
        return bytes.fromhex(parsed[2:].lower())
    if isinstance(parsed, (bytes, bytearray)):
        return bytes(parsed)
    raise ValueError(f"unsupported address cell: {value!r}")


def iter_snapshot_points(
    start: datetime,
    end: datetime,
    interval_days: int,
) -> list[datetime]:
    if interval_days < MIN_INTERVAL_DAYS:
        raise ValueError(f"interval_days must be >= {MIN_INTERVAL_DAYS}")
    if start > end:
        raise ValueError("start must be <= end")

    points: list[datetime] = []
    cursor = start
    delta = timedelta(days=interval_days)
    while cursor <= end:
        points.append(cursor)
        cursor += delta
    return points


def _chunked[T](items: list[T], size: int) -> list[list[T]]:
    if size <= 0:
        raise ValueError("chunk size must be > 0")
    return [items[i : i + size] for i in range(0, len(items), size)]


async def _multicall_contract_reads(
    w3: AsyncWeb3,
    block_number: int,
    calls: list[tuple[str, str, list[Any], list[str]]],
) -> list[Any | BaseException]:
    if not calls:
        return []

    if block_number < MULTICALL3_DEPLOY_BLOCK:
        coroutines = [
            w3.eth.contract(
                address=AsyncWeb3.to_checksum_address(target), abi=COMET_ABI
            )
            .get_function_by_name(method)(*args)
            .call(block_identifier=block_number)
            for target, method, args, _ in calls
        ]
        return list(await asyncio.gather(*coroutines, return_exceptions=True))

    mc_contract = w3.eth.contract(address=MULTICALL3_ADDRESS, abi=MULTICALL3_ABI)
    encoded_calls = []
    for target, method, args, _ in calls:
        contract = w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(target),
            abi=COMET_ABI,
        )
        encoded_calls.append(
            (
                AsyncWeb3.to_checksum_address(target),
                True,
                contract.encode_abi(method, args=args),
            )
        )

    raw_results: list[tuple[bool, bytes]] = await mc_contract.functions.aggregate3(
        encoded_calls
    ).call(block_identifier=block_number)

    decoded_results: list[Any | BaseException] = []
    for (_, _, _, output_types), (success, return_data) in zip(calls, raw_results):
        if not success or not return_data:
            decoded_results.append(
                Exception("Multicall3: call failed or empty return data")
            )
            continue
        try:
            decoded_results.append(_abi_decode(output_types, return_data))
        except Exception as exc:
            decoded_results.append(exc)
    return decoded_results


def _beta_to_eth(symbol: str | None) -> Decimal:
    if symbol and symbol.upper() in ETH_CORRELATED_SYMBOLS:
        return Decimal("1")
    return ZERO


def _solve_eth_liq_prices(
    *,
    eth_price_usd: Decimal,
    discounted_eth_collateral_usd: Decimal,
    eth_debt_usd: Decimal,
    discounted_stable_collateral_usd: Decimal,
    stable_debt_usd: Decimal,
) -> tuple[Decimal | None, Decimal | None, str]:
    if eth_price_usd <= 0:
        return None, None, "neutral"

    slope = discounted_eth_collateral_usd - eth_debt_usd
    intercept = discounted_stable_collateral_usd - stable_debt_usd
    if slope == 0:
        return None, None, "neutral"

    ratio = (-intercept) / slope
    if ratio <= 0:
        return None, None, "mixed"

    liq_price = eth_price_usd * ratio
    if slope > 0 and ratio < 1:
        return liq_price, None, "down"
    if slope < 0 and ratio > 1:
        return None, liq_price, "up"
    return None, None, "mixed"


def _parse_utc_time(value: str) -> datetime:
    formats = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"invalid UTC datetime: {value}")


def _load_users_from_csv(path: Path) -> list[bytes]:
    users: list[bytes] = []
    seen: set[bytes] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            cell = row.get("address")
            if not cell:
                continue
            addr = parse_csv_address_cell(cell)
            if addr in seen:
                continue
            seen.add(addr)
            users.append(addr)
    return users


async def _load_market_context(
    w3: AsyncWeb3,
    market_address: str,
    block_number: int,
    metadata_cache: dict[str, tuple[str | None, int | None]],
) -> MarketContext:
    comet = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(market_address),
        abi=COMET_ABI,
    )
    market_symbol = COMPOUND_V3_MARKET_NAMES.get(
        market_address.lower(), market_address.lower()
    )

    (
        base_scale,
        base_token,
        base_token_feed,
        num_assets,
    ) = await asyncio.gather(
        comet.functions.baseScale().call(block_identifier=block_number),
        comet.functions.baseToken().call(block_identifier=block_number),
        comet.functions.baseTokenPriceFeed().call(block_identifier=block_number),
        comet.functions.numAssets().call(block_identifier=block_number),
    )
    (
        (base_symbol, base_decimals_meta),
        base_price_usd,
        eth_price_usd,
    ) = await asyncio.gather(
        _token_metadata(w3, base_token, block_number, metadata_cache),
        _base_token_usd_price(w3, comet, base_token, base_token_feed, block_number),
        _price_from_feed_direct(w3, ETH_USD_PRICE_FEED, block_number),
    )
    base_decimals = (
        base_decimals_meta
        if base_decimals_meta is not None
        else _scale_to_decimals(int(base_scale))
    )

    asset_count = int(num_assets)
    sem = asyncio.Semaphore(MARKET_CONTEXT_RPC_CONCURRENCY)

    async def _get_asset_info(i: int) -> Any:
        async with sem:
            return await comet.functions.getAssetInfo(i).call(
                block_identifier=block_number
            )

    asset_infos = list(
        await asyncio.gather(*[_get_asset_info(i) for i in range(asset_count)])
    )

    async def _build_asset_context(asset_info: Any) -> AssetContext:
        asset_address = asset_info[1]
        asset_price_feed = asset_info[2]
        asset_scale = int(asset_info[3])

        async def _token_meta() -> tuple[str | None, int | None]:
            async with sem:
                return await _token_metadata(
                    w3, asset_address, block_number, metadata_cache
                )

        async def _oracle_price() -> Decimal:
            async with sem:
                return await _price_from_oracle(
                    w3, comet, asset_price_feed, block_number
                )

        (asset_symbol, asset_decimals_meta), price_in_base = await asyncio.gather(
            _token_meta(),
            _oracle_price(),
        )
        symbol = asset_symbol or asset_address
        return AssetContext(
            address=asset_address,
            symbol=asset_symbol,
            decimals=(
                asset_decimals_meta
                if asset_decimals_meta is not None
                else _scale_to_decimals(asset_scale)
            ),
            price_in_base=price_in_base,
            price_usd=price_in_base * base_price_usd,
            borrow_collateral_factor=Decimal(int(asset_info[4])) / Decimal(10**18),
            liquidate_collateral_factor=Decimal(int(asset_info[5])) / Decimal(10**18),
            liquidation_factor=Decimal(int(asset_info[6])) / Decimal(10**18),
            beta_to_eth=_beta_to_eth(symbol),
            is_eth_correlated=(symbol.upper() in ETH_CORRELATED_SYMBOLS),
        )

    assets = list(
        await asyncio.gather(*[_build_asset_context(info) for info in asset_infos])
    )

    return MarketContext(
        market_address=market_address,
        market_symbol=market_symbol,
        comet=comet,
        base_token=base_token,
        base_symbol=base_symbol,
        base_decimals=base_decimals,
        base_price_usd=base_price_usd,
        eth_price_usd=eth_price_usd,
        assets=assets,
    )


def _build_user_snapshot(
    market_ctx: MarketContext,
    user_address: bytes,
    point_ts: datetime,
    block_number: int,
    base_supply_raw: int,
    base_borrow_raw: int,
    collateral_balance_raws: dict[str, int],
) -> tuple[UserPositionSnapshotRow, list[UserPositionAssetRow]]:
    base_supply = Decimal(int(base_supply_raw)) / (
        Decimal(10) ** market_ctx.base_decimals
    )
    base_borrow = Decimal(int(base_borrow_raw)) / (
        Decimal(10) ** market_ctx.base_decimals
    )
    base_supply_usd = base_supply * market_ctx.base_price_usd
    base_borrow_usd = base_borrow * market_ctx.base_price_usd

    total_collateral_usd = base_supply_usd
    total_debt_usd = base_borrow_usd
    discounted_collateral_usd = base_supply_usd

    eth_sensitive_collateral_usd = (
        base_supply_usd if _beta_to_eth(market_ctx.base_symbol) > 0 else ZERO
    )
    eth_sensitive_debt_usd = (
        base_borrow_usd if _beta_to_eth(market_ctx.base_symbol) > 0 else ZERO
    )
    discounted_eth_collateral_usd = eth_sensitive_collateral_usd
    basis_risk_collateral_usd = ZERO

    assets_jsonb: list[dict[str, Any]] = []
    asset_rows: list[UserPositionAssetRow] = []

    if base_supply > 0:
        assets_jsonb.append(
            {
                "asset": market_ctx.base_token.lower(),
                "symbol": market_ctx.base_symbol,
                "side": "base_supply",
                "amount": str(base_supply),
                "price_usd": str(market_ctx.base_price_usd),
                "price_in_base": "1",
                "value_usd": str(base_supply_usd),
                "discounted_value_usd": str(base_supply_usd),
                "beta_to_eth": str(_beta_to_eth(market_ctx.base_symbol)),
                "is_eth_correlated": bool(_beta_to_eth(market_ctx.base_symbol) > 0),
                "is_basis_risk_asset": False,
            }
        )
        asset_rows.append(
            UserPositionAssetRow(
                timestamp=point_ts,
                block_number=block_number,
                market=_to_bytes(market_ctx.market_address),
                user_address=user_address,
                asset=_to_bytes(market_ctx.base_token),
                symbol=market_ctx.base_symbol,
                side="base_supply",
                decimals=market_ctx.base_decimals,
                amount=base_supply,
                price_in_base=ONE,
                price_usd=market_ctx.base_price_usd,
                value_usd=base_supply_usd,
                discounted_value_usd=base_supply_usd,
                borrow_collateral_factor=None,
                liquidate_collateral_factor=None,
                liquidation_factor=None,
                beta_to_eth=_beta_to_eth(market_ctx.base_symbol),
                is_eth_correlated=bool(_beta_to_eth(market_ctx.base_symbol) > 0),
                is_basis_risk_asset=False,
            )
        )

    if base_borrow > 0:
        assets_jsonb.append(
            {
                "asset": market_ctx.base_token.lower(),
                "symbol": market_ctx.base_symbol,
                "side": "base_borrow",
                "amount": str(base_borrow),
                "price_usd": str(market_ctx.base_price_usd),
                "price_in_base": "1",
                "value_usd": str(base_borrow_usd),
                "discounted_value_usd": "0",
                "beta_to_eth": str(_beta_to_eth(market_ctx.base_symbol)),
                "is_eth_correlated": bool(_beta_to_eth(market_ctx.base_symbol) > 0),
                "is_basis_risk_asset": False,
            }
        )
        asset_rows.append(
            UserPositionAssetRow(
                timestamp=point_ts,
                block_number=block_number,
                market=_to_bytes(market_ctx.market_address),
                user_address=user_address,
                asset=_to_bytes(market_ctx.base_token),
                symbol=market_ctx.base_symbol,
                side="base_borrow",
                decimals=market_ctx.base_decimals,
                amount=base_borrow,
                price_in_base=ONE,
                price_usd=market_ctx.base_price_usd,
                value_usd=base_borrow_usd,
                discounted_value_usd=ZERO,
                borrow_collateral_factor=None,
                liquidate_collateral_factor=None,
                liquidation_factor=None,
                beta_to_eth=_beta_to_eth(market_ctx.base_symbol),
                is_eth_correlated=bool(_beta_to_eth(market_ctx.base_symbol) > 0),
                is_basis_risk_asset=False,
            )
        )

    for asset in market_ctx.assets:
        balance_raw = collateral_balance_raws.get(asset.address.lower(), 0)
        if balance_raw <= 0:
            continue

        amount = Decimal(balance_raw) / (Decimal(10) ** asset.decimals)
        value_usd = amount * asset.price_usd
        discounted_value_usd = value_usd * asset.liquidate_collateral_factor
        is_basis_risk_asset = asset.is_eth_correlated and (
            (asset.symbol or "").upper() != "WETH"
        )

        total_collateral_usd += value_usd
        discounted_collateral_usd += discounted_value_usd
        if asset.is_eth_correlated:
            eth_sensitive_collateral_usd += value_usd
            discounted_eth_collateral_usd += discounted_value_usd
            if is_basis_risk_asset:
                basis_risk_collateral_usd += value_usd

        assets_jsonb.append(
            {
                "asset": asset.address.lower(),
                "symbol": asset.symbol,
                "side": "collateral",
                "amount": str(amount),
                "price_usd": str(asset.price_usd),
                "price_in_base": str(asset.price_in_base),
                "value_usd": str(value_usd),
                "discounted_value_usd": str(discounted_value_usd),
                "borrow_collateral_factor": str(asset.borrow_collateral_factor),
                "liquidate_collateral_factor": str(asset.liquidate_collateral_factor),
                "liquidation_factor": str(asset.liquidation_factor),
                "beta_to_eth": str(asset.beta_to_eth),
                "is_eth_correlated": asset.is_eth_correlated,
                "is_basis_risk_asset": is_basis_risk_asset,
            }
        )
        asset_rows.append(
            UserPositionAssetRow(
                timestamp=point_ts,
                block_number=block_number,
                market=_to_bytes(market_ctx.market_address),
                user_address=user_address,
                asset=_to_bytes(asset.address),
                symbol=asset.symbol,
                side="collateral",
                decimals=asset.decimals,
                amount=amount,
                price_in_base=asset.price_in_base,
                price_usd=asset.price_usd,
                value_usd=value_usd,
                discounted_value_usd=discounted_value_usd,
                borrow_collateral_factor=asset.borrow_collateral_factor,
                liquidate_collateral_factor=asset.liquidate_collateral_factor,
                liquidation_factor=asset.liquidation_factor,
                beta_to_eth=asset.beta_to_eth,
                is_eth_correlated=asset.is_eth_correlated,
                is_basis_risk_asset=is_basis_risk_asset,
            )
        )

    non_eth_collateral_usd = total_collateral_usd - eth_sensitive_collateral_usd
    non_eth_debt_usd = total_debt_usd - eth_sensitive_debt_usd
    discounted_stable_collateral_usd = (
        discounted_collateral_usd - discounted_eth_collateral_usd
    )

    liquidation_buffer_usd = discounted_collateral_usd - total_debt_usd
    health_factor = (
        INF_HEALTH_FACTOR
        if total_debt_usd <= 0
        else discounted_collateral_usd / total_debt_usd
    )
    eth_down_liq_price_usd, eth_up_liq_price_usd, eth_liq_mode = _solve_eth_liq_prices(
        eth_price_usd=market_ctx.eth_price_usd,
        discounted_eth_collateral_usd=discounted_eth_collateral_usd,
        eth_debt_usd=eth_sensitive_debt_usd,
        discounted_stable_collateral_usd=discounted_stable_collateral_usd,
        stable_debt_usd=non_eth_debt_usd,
    )

    dominant_risk = "neutral"
    if eth_liq_mode == "down":
        dominant_risk = "eth_down"
    elif eth_liq_mode == "up":
        dominant_risk = "eth_up"
    elif basis_risk_collateral_usd > 0:
        dominant_risk = "basis"
    elif liquidation_buffer_usd < 0:
        dominant_risk = "mixed"

    snapshot_row = UserPositionSnapshotRow(
        timestamp=point_ts,
        block_number=block_number,
        market=_to_bytes(market_ctx.market_address),
        symbol=market_ctx.market_symbol,
        user_address=user_address,
        has_open_position=bool(base_supply > 0 or base_borrow > 0 or asset_rows),
        is_liquidatable=bool(total_debt_usd > 0 and liquidation_buffer_usd < 0),
        base_token=_to_bytes(market_ctx.base_token),
        base_symbol=market_ctx.base_symbol,
        base_price_usd=market_ctx.base_price_usd,
        eth_price_usd=market_ctx.eth_price_usd,
        total_collateral_usd=total_collateral_usd,
        total_debt_usd=total_debt_usd,
        discounted_collateral_usd=discounted_collateral_usd,
        liquidation_buffer_usd=liquidation_buffer_usd,
        health_factor=health_factor,
        eth_sensitive_collateral_usd=eth_sensitive_collateral_usd,
        eth_sensitive_debt_usd=eth_sensitive_debt_usd,
        net_eth_exposure_usd=eth_sensitive_collateral_usd - eth_sensitive_debt_usd,
        non_eth_collateral_usd=non_eth_collateral_usd,
        non_eth_debt_usd=non_eth_debt_usd,
        basis_risk_collateral_usd=basis_risk_collateral_usd,
        eth_down_liq_price_usd=eth_down_liq_price_usd,
        eth_up_liq_price_usd=eth_up_liq_price_usd,
        eth_liq_mode=eth_liq_mode,
        dominant_risk=dominant_risk,
        assets_jsonb=assets_jsonb,
    )
    return snapshot_row, asset_rows


async def _collect_user_snapshots_batch(
    w3: AsyncWeb3,
    market_ctx: MarketContext,
    user_addresses: list[bytes],
    point_ts: datetime,
    block_number: int,
) -> list[tuple[UserPositionSnapshotRow, list[UserPositionAssetRow]]]:
    if not user_addresses:
        return []

    comet_address = market_ctx.market_address
    user_checksums = {
        user_address: AsyncWeb3.to_checksum_address("0x" + user_address.hex())
        for user_address in user_addresses
    }

    base_calls: list[tuple[str, str, list[Any], list[str]]] = []
    for user_address in user_addresses:
        checksum = user_checksums[user_address]
        base_calls.append((comet_address, "balanceOf", [checksum], _UINT256_OUTPUT))
        base_calls.append(
            (comet_address, "borrowBalanceOf", [checksum], _UINT256_OUTPUT)
        )
    base_results = await _multicall_contract_reads(w3, block_number, base_calls)

    base_map: dict[bytes, tuple[int, int]] = {}
    for idx, user_address in enumerate(user_addresses):
        supply_result = base_results[2 * idx]
        borrow_result = base_results[2 * idx + 1]

        base_supply_raw = 0
        base_borrow_raw = 0
        if isinstance(supply_result, BaseException):
            logger.warning(
                "Failed to fetch base supply market=%s user=%s block=%s: %s",
                comet_address,
                "0x" + user_address.hex(),
                block_number,
                supply_result,
            )
        else:
            base_supply_raw = int(tuple(supply_result)[0])

        if isinstance(borrow_result, BaseException):
            logger.warning(
                "Failed to fetch base borrow market=%s user=%s block=%s: %s",
                comet_address,
                "0x" + user_address.hex(),
                block_number,
                borrow_result,
            )
        else:
            base_borrow_raw = int(tuple(borrow_result)[0])

        base_map[user_address] = (base_supply_raw, base_borrow_raw)

    collateral_calls: list[tuple[str, str, list[Any], list[str]]] = []
    call_keys: list[tuple[bytes, str]] = []
    for user_address in user_addresses:
        checksum = user_checksums[user_address]
        for asset in market_ctx.assets:
            collateral_calls.append(
                (
                    comet_address,
                    "userCollateral",
                    [checksum, AsyncWeb3.to_checksum_address(asset.address)],
                    _USER_COLLATERAL_OUTPUT,
                )
            )
            call_keys.append((user_address, asset.address.lower()))

    collateral_results = await _multicall_contract_reads(
        w3, block_number, collateral_calls
    )
    collateral_map: dict[bytes, dict[str, int]] = {
        user_address: {} for user_address in user_addresses
    }

    for (user_address, asset_address), result in zip(call_keys, collateral_results):
        if isinstance(result, BaseException):
            logger.warning(
                "Failed to fetch collateral market=%s user=%s asset=%s block=%s: %s",
                comet_address,
                "0x" + user_address.hex(),
                asset_address,
                block_number,
                result,
            )
            continue
        collateral_tuple = tuple(result)
        collateral_map[user_address][asset_address] = int(collateral_tuple[0])

    return [
        _build_user_snapshot(
            market_ctx,
            user_address=user_address,
            point_ts=point_ts,
            block_number=block_number,
            base_supply_raw=base_map[user_address][0],
            base_borrow_raw=base_map[user_address][1],
            collateral_balance_raws=collateral_map[user_address],
        )
        for user_address in user_addresses
    ]


async def _collect_market_snapshot_rows(
    w3: AsyncWeb3,
    cfg: AppConfig,
    *,
    market: str,
    point_ts: datetime,
    block_number: int,
    users: list[bytes],
    metadata_cache: dict[str, tuple[str | None, int | None]],
) -> tuple[
    MarketContext, list[UserPositionSnapshotRow], list[UserPositionAssetRow], int
]:
    market_address = _resolve_market_address(market)
    market_ctx = await _load_market_context(
        w3, market_address, block_number, metadata_cache
    )

    user_batch_size = max(1, cfg.crawler.batch_size)
    snapshot_rows: list[UserPositionSnapshotRow] = []
    asset_rows: list[UserPositionAssetRow] = []
    skipped_empty = 0

    for user_batch in _chunked(users, user_batch_size):
        try:
            results = await _collect_user_snapshots_batch(
                w3,
                market_ctx,
                user_addresses=user_batch,
                point_ts=point_ts,
                block_number=block_number,
            )
        except Exception as exc:
            logger.warning(
                "Failed to collect user batch market=%s ts=%s block=%s batch_size=%s: %s",
                market,
                point_ts.isoformat(),
                block_number,
                len(user_batch),
                exc,
            )
            continue

        for snapshot_row, asset_row_group in results:
            if not snapshot_row.has_open_position:
                skipped_empty += 1
                continue
            snapshot_rows.append(snapshot_row)
            asset_rows.extend(asset_row_group)

    return market_ctx, snapshot_rows, asset_rows, skipped_empty


async def _collect_market_point(
    w3: AsyncWeb3,
    pool: asyncpg.Pool,
    cfg: AppConfig,
    market_name: str,
    point_ts: datetime,
    block_number: int,
    users: list[bytes],
    skip_existing: bool,
    dry_run: bool,
    stats: BackfillStats,
    metadata_cache: dict[str, tuple[str | None, int | None]],
) -> tuple[list[UserPositionSnapshotRow], list[UserPositionAssetRow]]:
    market_address = _resolve_market_address(market_name)
    pending_users = users
    if skip_existing:
        existing = await fetch_existing_user_position_addresses(
            pool,
            point_ts,
            _to_bytes(market_address),
            users,
            protocol=cfg.protocol,
        )
        stats.skipped_existing += len(existing)
        pending_users = [addr for addr in users if addr not in existing]
    if not pending_users:
        return [], []

    _, snapshot_rows, asset_rows, skipped_empty = await _collect_market_snapshot_rows(
        w3,
        cfg,
        market=market_name,
        point_ts=point_ts,
        block_number=block_number,
        users=pending_users,
        metadata_cache=metadata_cache,
    )
    stats.skipped_empty += skipped_empty

    if dry_run:
        if snapshot_rows:
            logger.info(
                "dry-run point summary market=%s ts=%s block=%s open_positions=%s skipped_empty=%s",
                market_name,
                point_ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                block_number,
                len(snapshot_rows),
                stats.skipped_empty,
            )
        for snapshot_row in snapshot_rows:
            logger.info(
                "dry-run snapshot %s",
                json.dumps(
                    {
                        "timestamp": snapshot_row.timestamp.astimezone(
                            timezone.utc
                        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "block_number": snapshot_row.block_number,
                        "market": "0x" + snapshot_row.market.hex(),
                        "symbol": snapshot_row.symbol,
                        "user_address": "0x" + snapshot_row.user_address.hex(),
                        "base_symbol": snapshot_row.base_symbol,
                        "base_price_usd": str(snapshot_row.base_price_usd),
                        "eth_price_usd": str(snapshot_row.eth_price_usd),
                        "total_collateral_usd": str(snapshot_row.total_collateral_usd),
                        "total_debt_usd": str(snapshot_row.total_debt_usd),
                        "discounted_collateral_usd": str(
                            snapshot_row.discounted_collateral_usd
                        ),
                        "liquidation_buffer_usd": str(
                            snapshot_row.liquidation_buffer_usd
                        ),
                        "health_factor": str(snapshot_row.health_factor),
                        "eth_down_liq_price_usd": (
                            str(snapshot_row.eth_down_liq_price_usd)
                            if snapshot_row.eth_down_liq_price_usd is not None
                            else None
                        ),
                        "eth_up_liq_price_usd": (
                            str(snapshot_row.eth_up_liq_price_usd)
                            if snapshot_row.eth_up_liq_price_usd is not None
                            else None
                        ),
                        "eth_liq_mode": snapshot_row.eth_liq_mode,
                        "dominant_risk": snapshot_row.dominant_risk,
                        "assets": snapshot_row.assets_jsonb,
                    },
                    ensure_ascii=False,
                ),
            )
        return snapshot_rows, asset_rows

    return snapshot_rows, asset_rows


async def _flush_backfill_write_batch(
    pool: asyncpg.Pool,
    *,
    protocol: str = "v3",
    snapshot_rows: list[UserPositionSnapshotRow],
    asset_rows: list[UserPositionAssetRow],
    stats: BackfillStats,
) -> None:
    if not snapshot_rows and not asset_rows:
        return

    logger.info(
        "Flushing Compound user position batch: snapshots=%s assets=%s",
        len(snapshot_rows),
        len(asset_rows),
    )
    inserted_snapshots = await upsert_user_position_snapshots(
        pool, snapshot_rows, protocol=protocol
    )
    inserted_assets = await upsert_user_position_asset_rows(
        pool, asset_rows, protocol=protocol
    )
    stats.snapshots += inserted_snapshots
    stats.assets += inserted_assets
    logger.info(
        "Flushed Compound user position batch: inserted_snapshots=%s inserted_assets=%s total_snapshots=%s total_assets=%s",
        inserted_snapshots,
        inserted_assets,
        stats.snapshots,
        stats.assets,
    )


async def collect_market_user_snapshots(
    cfg: AppConfig,
    pool: asyncpg.Pool,
    *,
    market: str,
    point_ts: datetime | None = None,
    persist: bool = False,
    derived_users_dir: Path | None = None,
    user_addresses: list[bytes] | None = None,
    w3: AsyncWeb3 | None = None,
) -> CollectedMarketSnapshots:
    if persist:
        await ensure_user_position_snapshot_tables(
            pool,
            protocol=cfg.protocol,
            use_timescaledb=cfg.market_state.use_timescaledb,
        )

    market_address = _resolve_market_address(market)
    market_symbol = COMPOUND_V3_MARKET_NAMES[market_address]
    if user_addresses is not None:
        users = user_addresses
    else:
        csv_dir = derived_users_dir or (
            Path(__file__).resolve().parent.parent / "derived_users"
        )
        csv_path = csv_dir / f"compound_v3_{market_symbol.lower()}_users.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"missing user csv: {csv_path}")
        users = _load_users_from_csv(csv_path)
    own_w3 = False
    try:
        if point_ts is None:
            if w3 is None:
                w3 = await _build_web3(cfg)
                own_w3 = True
            latest_block = await w3.eth.get_block("latest")
            latest_timestamp = latest_block.get("timestamp")
            latest_number = latest_block.get("number")
            if latest_timestamp is None or latest_number is None:
                raise RuntimeError("latest block missing timestamp or number")
            timestamp = datetime.fromtimestamp(int(latest_timestamp), tz=timezone.utc)
            block_number = int(latest_number)
        else:
            timestamp = (
                point_ts.replace(tzinfo=timezone.utc)
                if point_ts.tzinfo is None
                else point_ts.astimezone(timezone.utc)
            )
            if w3 is None:
                w3 = await _build_web3(cfg)
                own_w3 = True
            block_number = await _block_at_timestamp(
                w3, int(timestamp.timestamp()), pool=pool
            )

        metadata_cache: dict[str, tuple[str | None, int | None]] = {}
        market_ctx, snapshot_rows, asset_rows, _ = await _collect_market_snapshot_rows(
            w3,
            cfg,
            market=market_address,
            point_ts=timestamp,
            block_number=block_number,
            users=users,
            metadata_cache=metadata_cache,
        )

        if persist:
            await upsert_user_position_snapshots(
                pool, snapshot_rows, protocol=cfg.protocol
            )
            await upsert_user_position_asset_rows(
                pool, asset_rows, protocol=cfg.protocol
            )

        return CollectedMarketSnapshots(
            timestamp=timestamp,
            block_number=block_number,
            market=market_ctx.market_address.lower(),
            symbol=market_ctx.market_symbol,
            snapshots=snapshot_rows,
        )
    finally:
        if own_w3:
            await close_web3(w3)


async def run_user_position_backfill(
    cfg: AppConfig,
    pool: asyncpg.Pool,
    *,
    markets: list[str],
    derived_users_dir: Path,
    start: datetime | None = None,
    end: datetime | None = None,
    interval_days: int = MIN_INTERVAL_DAYS,
    skip_existing: bool = False,
    dry_run: bool = False,
    w3: AsyncWeb3 | None = None,
) -> BackfillStats:
    await ensure_user_position_snapshot_tables(
        pool,
        protocol=cfg.protocol,
        use_timescaledb=cfg.market_state.use_timescaledb,
    )
    own_w3 = False
    if w3 is None:
        w3 = await _build_web3(cfg)
        own_w3 = True

    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start_ts = start or now
    end_ts = end or start_ts
    if start_ts.tzinfo is None:
        start_ts = start_ts.replace(tzinfo=timezone.utc)
    if end_ts.tzinfo is None:
        end_ts = end_ts.replace(tzinfo=timezone.utc)

    points = iter_snapshot_points(start_ts, end_ts, interval_days)
    market_users: dict[str, list[bytes]] = {}
    for market in markets:
        csv_path = derived_users_dir / f"compound_v3_{market.lower()}_users.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"missing user csv: {csv_path}")
        market_users[market.lower()] = _load_users_from_csv(csv_path)

    stats = BackfillStats()
    metadata_cache: dict[str, tuple[str | None, int | None]] = {}
    pending_snapshot_rows: list[UserPositionSnapshotRow] = []
    pending_asset_rows: list[UserPositionAssetRow] = []
    write_snapshot_batch_size = max(1000, cfg.crawler.batch_size * 10)
    write_asset_batch_size = max(5000, cfg.crawler.batch_size * 50)
    try:
        block_numbers = list(
            await asyncio.gather(
                *[
                    _block_at_timestamp(w3, int(point.timestamp()), pool=pool)
                    for point in points
                ]
            )
        )

        logger.info(
            "Compound user position backfill invoked: markets=%s start=%s end=%s interval_days=%s dry_run=%s skip_existing=%s",
            ",".join(markets),
            start_ts.isoformat(),
            end_ts.isoformat(),
            interval_days,
            dry_run,
            skip_existing,
        )
        if not dry_run:
            logger.info(
                "Compound user position write batching enabled: snapshot_batch_size=%s asset_batch_size=%s",
                write_snapshot_batch_size,
                write_asset_batch_size,
            )

        for point, block_number in zip(points, block_numbers):
            for market in markets:
                users = market_users[market.lower()]
                if not users:
                    continue
                snapshot_rows, asset_rows = await _collect_market_point(
                    w3,
                    pool,
                    cfg,
                    market_name=market,
                    point_ts=point,
                    block_number=block_number,
                    users=users,
                    skip_existing=skip_existing,
                    dry_run=dry_run,
                    stats=stats,
                    metadata_cache=metadata_cache,
                )
                if dry_run:
                    stats.snapshots += len(snapshot_rows)
                    stats.assets += len(asset_rows)
                    continue

                pending_snapshot_rows.extend(snapshot_rows)
                pending_asset_rows.extend(asset_rows)
                if (
                    len(pending_snapshot_rows) >= write_snapshot_batch_size
                    or len(pending_asset_rows) >= write_asset_batch_size
                ):
                    if cfg.protocol != "v3":
                        await _flush_backfill_write_batch(
                            pool,
                            protocol=cfg.protocol,
                            snapshot_rows=pending_snapshot_rows,
                            asset_rows=pending_asset_rows,
                            stats=stats,
                        )
                    else:
                        await _flush_backfill_write_batch(
                            pool,
                            snapshot_rows=pending_snapshot_rows,
                            asset_rows=pending_asset_rows,
                            stats=stats,
                        )
                    pending_snapshot_rows = []
                    pending_asset_rows = []

        if not dry_run:
            if cfg.protocol != "v3":
                await _flush_backfill_write_batch(
                    pool,
                    protocol=cfg.protocol,
                    snapshot_rows=pending_snapshot_rows,
                    asset_rows=pending_asset_rows,
                    stats=stats,
                )
            else:
                await _flush_backfill_write_batch(
                    pool,
                    snapshot_rows=pending_snapshot_rows,
                    asset_rows=pending_asset_rows,
                    stats=stats,
                )

        logger.info(
            "Compound user position backfill done: snapshots=%s assets=%s skipped_existing=%s skipped_empty=%s dry_run=%s",
            stats.snapshots,
            stats.assets,
            stats.skipped_existing,
            stats.skipped_empty,
            dry_run,
        )
        return stats
    finally:
        if own_w3:
            await close_web3(w3)


__all__ = [
    "BackfillStats",
    "CollectedMarketSnapshots",
    "MIN_INTERVAL_DAYS",
    "available_csv_markets",
    "collect_market_user_snapshots",
    "iter_snapshot_points",
    "parse_csv_address_cell",
    "run_user_position_backfill",
    "_parse_utc_time",
    "_solve_eth_liq_prices",
]
