"""Batch crawler entry for Compound positions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aave_crawler.market_collector import _block_at_timestamp
from web3 import AsyncHTTPProvider, AsyncWeb3

from .config import AppConfig
from .constants import (
    CHAINLINK_AGGREGATOR_V3_ABI,
    COMET_ABI,
    COMPOUND_V2_MARKETS,
    COMPOUND_V3_MARKETS,
)
from .db import (
    MarketSnapshotRow,
    ReserveSnapshotRow,
    ensure_market_state_tables,
    upsert_market_snapshots,
    upsert_reserve_snapshots,
)

logger = logging.getLogger(__name__)

ETH_CHAIN_ID = 1
PUBLIC_RPCS = [
    "https://eth.llamarpc.com",
    "https://ethereum-rpc.publicnode.com",
    "https://rpc.ankr.com/eth",
]


async def _build_web3(cfg: AppConfig) -> AsyncWeb3:
    """Build AsyncWeb3 for Ethereum mainnet using compound config."""
    timeout = cfg.crawler.rpc_timeout

    async def _try_url(url: str) -> AsyncWeb3 | None:
        w3 = AsyncWeb3(AsyncHTTPProvider(url, request_kwargs={"timeout": timeout}))
        try:
            chain_id = await w3.eth.chain_id
            if chain_id != ETH_CHAIN_ID:
                logger.warning(
                    "RPC %s chain_id=%d, not Ethereum mainnet(%d), skipped",
                    url,
                    chain_id,
                    ETH_CHAIN_ID,
                )
                return None
            logger.info("Using RPC: %s (chain_id=1)", url)
            return w3
        except Exception as exc:
            logger.debug("RPC %s probe failed: %s", url, exc)
            return None

    custom = (cfg.rpc_url or "").strip()
    if custom:
        w3 = await _try_url(custom)
        if w3 is not None:
            return w3
        logger.warning("Custom RPC unavailable, fallback to public endpoints")

    for url in PUBLIC_RPCS:
        w3 = await _try_url(url)
        if w3 is not None:
            return w3

    raise RuntimeError("All RPC endpoints are unavailable")


def _to_bytes(address: str) -> bytes:
    addr = address.strip().lower()
    if addr.startswith("0x"):
        addr = addr[2:]
    if addr == "":
        return b""
    return bytes.fromhex(addr)


def _market_addresses(cfg: AppConfig) -> list[str]:
    if cfg.protocol == "v2":
        markets = cfg.market_state.v2_markets or COMPOUND_V2_MARKETS
    else:
        markets = cfg.market_state.v3_markets or COMPOUND_V3_MARKETS
    if markets:
        return markets
    placeholder = f"{cfg.protocol}_default_market"
    logger.warning(
        "No %s market addresses configured in compound_market_state.%s_markets; using placeholder market '%s'",
        cfg.protocol,
        cfg.protocol,
        placeholder,
    )
    return [placeholder]


def _scale_to_decimals(scale: int) -> int:
    if scale <= 0:
        return 0
    s = scale
    d = 0
    while s % 10 == 0:
        d += 1
        s //= 10
    return d


async def _price_from_feed(
    w3: AsyncWeb3,
    price_feed: str,
    block_number: int,
) -> Decimal:
    feed = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(price_feed),
        abi=CHAINLINK_AGGREGATOR_V3_ABI,
    )
    decimals, round_data = await asyncio.gather(
        feed.functions.decimals().call(block_identifier=block_number),
        feed.functions.latestRoundData().call(block_identifier=block_number),
    )
    answer = int(round_data[1])
    if answer <= 0:
        return Decimal("0")
    return Decimal(answer) / (Decimal(10) ** int(decimals))


async def _collect_v3_market_at_block(
    w3: AsyncWeb3,
    market_address: str,
    point_ts: datetime,
    block_number: int,
) -> tuple[MarketSnapshotRow, list[ReserveSnapshotRow]]:
    comet = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(market_address),
        abi=COMET_ABI,
    )

    (
        base_scale,
        base_token,
        base_token_feed,
        total_supply_raw,
        total_borrow_raw,
        utilization_raw,
        num_assets,
    ) = await asyncio.gather(
        comet.functions.baseScale().call(block_identifier=block_number),
        comet.functions.baseToken().call(block_identifier=block_number),
        comet.functions.baseTokenPriceFeed().call(block_identifier=block_number),
        comet.functions.totalSupply().call(block_identifier=block_number),
        comet.functions.totalBorrow().call(block_identifier=block_number),
        comet.functions.getUtilization().call(block_identifier=block_number),
        comet.functions.numAssets().call(block_identifier=block_number),
    )

    supply_rate_raw, borrow_rate_raw = await asyncio.gather(
        comet.functions.getSupplyRate(utilization_raw).call(
            block_identifier=block_number
        ),
        comet.functions.getBorrowRate(utilization_raw).call(
            block_identifier=block_number
        ),
    )

    base_price_usd = await _price_from_feed(w3, base_token_feed, block_number)

    base_scale_dec = Decimal(int(base_scale))
    total_supply = Decimal(int(total_supply_raw)) / base_scale_dec
    total_borrow = Decimal(int(total_borrow_raw)) / base_scale_dec
    utilization = Decimal(int(utilization_raw)) / Decimal(10**18)
    supply_rate = Decimal(int(supply_rate_raw)) / Decimal(10**18)
    borrow_rate = Decimal(int(borrow_rate_raw)) / Decimal(10**18)
    supply_usd = total_supply * base_price_usd
    borrow_usd = total_borrow * base_price_usd

    market_row = MarketSnapshotRow(
        timestamp=point_ts,
        market=_to_bytes(market_address),
        total_supply=total_supply,
        total_borrow=total_borrow,
        utilization=utilization,
        borrow_rate=borrow_rate,
        supply_rate=supply_rate,
        supply_usd=supply_usd,
        borrow_usd=borrow_usd,
    )

    reserve_rows: list[ReserveSnapshotRow] = [
        ReserveSnapshotRow(
            timestamp=point_ts,
            market=_to_bytes(market_address),
            reserve=_to_bytes(base_token),
            symbol="BASE",
            decimals=_scale_to_decimals(int(base_scale)),
            total_supply=total_supply,
            total_borrow=total_borrow,
            utilization=utilization,
            borrow_rate=borrow_rate,
            supply_rate=supply_rate,
            supply_usd=supply_usd,
            borrow_usd=borrow_usd,
        )
    ]

    for i in range(int(num_assets)):
        try:
            asset_info = await comet.functions.getAssetInfo(i).call(
                block_identifier=block_number
            )
            # tuple: (offset, asset, priceFeed, scale, ...)
            asset_address = asset_info[1]
            asset_price_feed = asset_info[2]
            asset_scale = int(asset_info[3])

            totals_collateral = await comet.functions.totalsCollateral(
                AsyncWeb3.to_checksum_address(asset_address)
            ).call(block_identifier=block_number)
            total_supply_asset_raw = int(totals_collateral[0])
            asset_price_usd = await _price_from_feed(w3, asset_price_feed, block_number)
            asset_supply = Decimal(total_supply_asset_raw) / Decimal(asset_scale)
            asset_supply_usd = asset_supply * asset_price_usd

            reserve_rows.append(
                ReserveSnapshotRow(
                    timestamp=point_ts,
                    market=_to_bytes(market_address),
                    reserve=_to_bytes(asset_address),
                    symbol=None,
                    decimals=_scale_to_decimals(asset_scale),
                    total_supply=asset_supply,
                    total_borrow=Decimal("0"),
                    utilization=Decimal("0"),
                    borrow_rate=Decimal("0"),
                    supply_rate=Decimal("0"),
                    supply_usd=asset_supply_usd,
                    borrow_usd=Decimal("0"),
                )
            )
        except Exception as exc:
            logger.warning(
                "Failed to collect v3 collateral asset i=%s market=%s block=%s: %s",
                i,
                market_address,
                block_number,
                exc,
            )

    return market_row, reserve_rows


async def _collect_rows_for_point(
    cfg: AppConfig,
    w3: AsyncWeb3 | None,
    point_ts: datetime,
    markets: Sequence[str],
    dry_run: bool,
    pool,
) -> tuple[list[MarketSnapshotRow], list[ReserveSnapshotRow]]:
    if cfg.protocol != "v3" or w3 is None:
        return _build_rows_for_point(point_ts, list(markets))

    block_number = await _block_at_timestamp(w3, int(point_ts.timestamp()), pool=pool)
    market_rows: list[MarketSnapshotRow] = []
    reserve_rows: list[ReserveSnapshotRow] = []
    for market in markets:
        try:
            m_row, r_rows = await _collect_v3_market_at_block(
                w3,
                market_address=market,
                point_ts=point_ts,
                block_number=block_number,
            )
            market_rows.append(m_row)
            reserve_rows.extend(r_rows)
        except Exception as exc:
            logger.warning(
                "Failed to collect v3 market=%s ts=%s block=%s: %s",
                market,
                point_ts.isoformat(),
                block_number,
                exc,
            )
            if dry_run:
                continue
    return market_rows, reserve_rows


def _build_rows_for_point(
    ts: datetime, markets: list[str]
) -> tuple[list[MarketSnapshotRow], list[ReserveSnapshotRow]]:
    market_rows: list[MarketSnapshotRow] = []
    reserve_rows: list[ReserveSnapshotRow] = []
    zero = Decimal("0")

    for market in markets:
        market_bytes = (
            _to_bytes(market) if market.startswith("0x") else market.encode("utf-8")
        )

        market_rows.append(
            MarketSnapshotRow(
                timestamp=ts,
                market=market_bytes,
                total_supply=zero,
                total_borrow=zero,
                utilization=zero,
                borrow_rate=zero,
                supply_rate=zero,
                supply_usd=zero,
                borrow_usd=zero,
            )
        )
        # 先写一条 reserve 明细占位记录，后续接入真实链上 reserve 清单时直接替换。
        reserve_rows.append(
            ReserveSnapshotRow(
                timestamp=ts,
                market=market_bytes,
                reserve=market_bytes,
                symbol="MARKET",
                decimals=18,
                total_supply=zero,
                total_borrow=zero,
                utilization=zero,
                borrow_rate=zero,
                supply_rate=zero,
                supply_usd=zero,
                borrow_usd=zero,
            )
        )
    return market_rows, reserve_rows


async def run_crawler(
    cfg: AppConfig,
    pool,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    dry_run: bool = False,
) -> None:
    await ensure_market_state_tables(
        pool,
        protocol=cfg.protocol,
        use_timescaledb=cfg.market_state.use_timescaledb,
    )

    # 默认采集当前小时；若传入区间，则按配置间隔逐点采集。
    now_utc = datetime.now(timezone.utc)
    interval = timedelta(minutes=cfg.market_state.snapshot_interval_minutes)

    if start_at is None and end_at is None:
        start = now_utc.replace(minute=0, second=0, microsecond=0)
        end = start
    else:
        start = start_at or end_at or now_utc
        end = end_at or start_at or start
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

    if start > end:
        raise ValueError("end_at must be greater than or equal to start_at")

    points: list[datetime] = []
    cursor = start
    while cursor <= end:
        points.append(cursor)
        cursor = cursor + interval

    logger.info(
        "Compound market_state crawl invoked: protocol=%s dry_run=%s start=%s end=%s interval_minutes=%s points=%s",
        cfg.protocol,
        dry_run,
        start.isoformat(),
        end.isoformat(),
        cfg.market_state.snapshot_interval_minutes,
        len(points),
    )

    markets = _market_addresses(cfg)
    total_market_rows = 0
    total_reserve_rows = 0
    w3: AsyncWeb3 | None = None
    if cfg.protocol == "v3":
        w3 = await _build_web3(cfg)
    elif cfg.protocol == "v2":
        logger.warning(
            "v2 real collection is not implemented yet, fallback to placeholder rows"
        )

    for ts in points:
        logger.debug("market_state point scheduled: %s", ts.isoformat())
        market_rows, reserve_rows = await _collect_rows_for_point(
            cfg,
            w3,
            point_ts=ts,
            markets=markets,
            dry_run=dry_run,
            pool=pool,
        )

        if dry_run:
            total_market_rows += len(market_rows)
            total_reserve_rows += len(reserve_rows)
            continue

        inserted_market = await upsert_market_snapshots(pool, cfg.protocol, market_rows)
        inserted_reserve = await upsert_reserve_snapshots(
            pool, cfg.protocol, reserve_rows
        )
        total_market_rows += inserted_market
        total_reserve_rows += inserted_reserve

    logger.info(
        "Compound market_state crawl done: protocol=%s dry_run=%s market_rows=%s reserve_rows=%s",
        cfg.protocol,
        dry_run,
        total_market_rows,
        total_reserve_rows,
    )
