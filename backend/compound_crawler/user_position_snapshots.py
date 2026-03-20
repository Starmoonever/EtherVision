"""Backfill Compound v3 user position snapshots focused on liquidation metrics."""

from __future__ import annotations

import ast
import asyncio
import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
from web3 import AsyncWeb3

from .config import AppConfig
from .constants import COMET_ABI, COMPOUND_V3_MARKET_NAMES
from .crawler import (
    _base_token_usd_price,
    _block_at_timestamp,
    _build_web3,
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


def _normalize_market_name(name: str) -> str:
    return name.strip().lower()


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
    base_symbol, base_decimals_meta = await _token_metadata(
        w3, base_token, block_number, metadata_cache
    )
    base_price_usd = await _base_token_usd_price(
        w3, comet, base_token, base_token_feed, block_number
    )
    eth_price_usd = await _price_from_feed_direct(w3, ETH_USD_PRICE_FEED, block_number)
    base_decimals = (
        base_decimals_meta
        if base_decimals_meta is not None
        else _scale_to_decimals(int(base_scale))
    )

    assets: list[AssetContext] = []
    for i in range(int(num_assets)):
        asset_info = await comet.functions.getAssetInfo(i).call(
            block_identifier=block_number
        )
        asset_address = asset_info[1]
        asset_price_feed = asset_info[2]
        asset_scale = int(asset_info[3])
        asset_symbol, asset_decimals_meta = await _token_metadata(
            w3, asset_address, block_number, metadata_cache
        )
        price_in_base = await _price_from_oracle(
            w3, comet, asset_price_feed, block_number
        )
        symbol = asset_symbol or asset_address
        assets.append(
            AssetContext(
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
                liquidate_collateral_factor=Decimal(int(asset_info[5]))
                / Decimal(10**18),
                liquidation_factor=Decimal(int(asset_info[6])) / Decimal(10**18),
                beta_to_eth=_beta_to_eth(symbol),
                is_eth_correlated=(symbol.upper() in ETH_CORRELATED_SYMBOLS),
            )
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


async def _collect_user_snapshot(
    market_ctx: MarketContext,
    user_address: bytes,
    point_ts: datetime,
    block_number: int,
) -> tuple[UserPositionSnapshotRow, list[UserPositionAssetRow]]:
    user_hex = "0x" + user_address.hex()
    user_checksum = AsyncWeb3.to_checksum_address(user_hex)

    base_supply_raw, base_borrow_raw = await asyncio.gather(
        market_ctx.comet.functions.balanceOf(user_checksum).call(
            block_identifier=block_number
        ),
        market_ctx.comet.functions.borrowBalanceOf(user_checksum).call(
            block_identifier=block_number
        ),
    )

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

    user_collateral_calls = [
        market_ctx.comet.functions.userCollateral(
            user_checksum,
            AsyncWeb3.to_checksum_address(asset.address),
        ).call(block_identifier=block_number)
        for asset in market_ctx.assets
    ]
    collateral_results = await asyncio.gather(
        *user_collateral_calls, return_exceptions=True
    )

    for asset, result in zip(market_ctx.assets, collateral_results):
        if isinstance(result, BaseException):
            logger.warning(
                "Failed to fetch user collateral user=%s market=%s asset=%s block=%s: %s",
                user_hex,
                market_ctx.market_address,
                asset.address,
                block_number,
                result,
            )
            continue

        collateral_tuple = tuple(result)
        balance_raw = int(collateral_tuple[0])
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


async def _collect_market_point(
    w3: AsyncWeb3,
    pool: asyncpg.Pool,
    cfg: AppConfig,
    market_name: str,
    point_ts: datetime,
    users: list[bytes],
    skip_existing: bool,
    dry_run: bool,
    stats: BackfillStats,
    metadata_cache: dict[str, tuple[str | None, int | None]],
) -> None:
    market_address = next(
        (
            addr
            for addr, name in COMPOUND_V3_MARKET_NAMES.items()
            if name.lower() == market_name.lower()
        ),
        None,
    )
    if market_address is None:
        raise ValueError(f"unknown market: {market_name}")

    block_number = await _block_at_timestamp(w3, int(point_ts.timestamp()), pool=pool)
    market_ctx = await _load_market_context(
        w3, market_address, block_number, metadata_cache
    )
    pending_users = users
    if skip_existing:
        existing = await fetch_existing_user_position_addresses(
            pool,
            point_ts,
            _to_bytes(market_address),
            users,
        )
        stats.skipped_existing += len(existing)
        pending_users = [addr for addr in users if addr not in existing]
    if not pending_users:
        return

    sem = asyncio.Semaphore(max(1, cfg.crawler.concurrency))

    async def _one_user(
        user_address: bytes,
    ) -> tuple[UserPositionSnapshotRow, list[UserPositionAssetRow]] | None:
        async with sem:
            try:
                return await _collect_user_snapshot(
                    market_ctx,
                    user_address=user_address,
                    point_ts=point_ts,
                    block_number=block_number,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to collect user position market=%s user=%s ts=%s block=%s: %s",
                    market_name,
                    "0x" + user_address.hex(),
                    point_ts.isoformat(),
                    block_number,
                    exc,
                )
                return None

    results = await asyncio.gather(*(_one_user(user) for user in pending_users))
    snapshot_rows: list[UserPositionSnapshotRow] = []
    asset_rows: list[UserPositionAssetRow] = []
    for item in results:
        if item is None:
            continue
        snapshot_row, asset_row_group = item
        snapshot_rows.append(snapshot_row)
        asset_rows.extend(asset_row_group)

    if dry_run:
        stats.snapshots += len(snapshot_rows)
        stats.assets += len(asset_rows)
        return

    stats.snapshots += await upsert_user_position_snapshots(pool, snapshot_rows)
    stats.assets += await upsert_user_position_asset_rows(pool, asset_rows)


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
) -> BackfillStats:
    await ensure_user_position_snapshot_tables(
        pool, use_timescaledb=cfg.market_state.use_timescaledb
    )
    w3 = await _build_web3(cfg)

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

    logger.info(
        "Compound user position backfill invoked: markets=%s start=%s end=%s interval_days=%s dry_run=%s skip_existing=%s",
        ",".join(markets),
        start_ts.isoformat(),
        end_ts.isoformat(),
        interval_days,
        dry_run,
        skip_existing,
    )

    for point in points:
        for market in markets:
            users = market_users[market.lower()]
            if not users:
                continue
            await _collect_market_point(
                w3,
                pool,
                cfg,
                market_name=market,
                point_ts=point,
                users=users,
                skip_existing=skip_existing,
                dry_run=dry_run,
                stats=stats,
                metadata_cache=metadata_cache,
            )

    logger.info(
        "Compound user position backfill done: snapshots=%s assets=%s skipped_existing=%s dry_run=%s",
        stats.snapshots,
        stats.assets,
        stats.skipped_existing,
        dry_run,
    )
    return stats


__all__ = [
    "BackfillStats",
    "MIN_INTERVAL_DAYS",
    "available_csv_markets",
    "iter_snapshot_points",
    "parse_csv_address_cell",
    "run_user_position_backfill",
    "_parse_utc_time",
    "_solve_eth_liq_prices",
]
