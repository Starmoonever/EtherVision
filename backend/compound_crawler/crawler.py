"""Batch crawler entry for Compound positions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from aave_crawler.market_collector import _block_at_timestamp
import asyncpg
from web3 import AsyncHTTPProvider, AsyncWeb3

from .config import AppConfig
from .constants import (
    CHAINLINK_AGGREGATOR_V3_ABI,
    COMET_ABI,
    COMPOUND_V2_MARKETS,
    COMPOUND_V2_MARKET_NAMES,
    COMPOUND_V3_MARKETS,
    COMPOUND_V3_MARKET_NAMES,
    ERC20_METADATA_ABI,
    ERC20_SYMBOL_BYTES32_ABI,
)
from .db import (
    MarketSnapshotRow,
    ReserveSnapshotRow,
    ensure_market_state_tables,
    market_table_name,
    upsert_market_snapshots,
    upsert_reserve_snapshots,
)

logger = logging.getLogger(__name__)

ETH_CHAIN_ID = 1
COMET_PRICE_SCALE = Decimal(10**8)
ONE = Decimal("1")
WETH_MAINNET = "0xc02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
ETH_USD_PRICE_FEED = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"
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


def _market_name_map(protocol: str) -> dict[str, str]:
    if protocol == "v3":
        return COMPOUND_V3_MARKET_NAMES
    return COMPOUND_V2_MARKET_NAMES


def _resolve_market_name(protocol: str, market_address: str) -> str:
    name = _market_name_map(protocol).get(market_address.lower())
    if name:
        return name
    return "MARKET"


async def _price_from_feed_direct(
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


async def _price_from_comet(
    comet: Any,
    price_feed: str,
    block_number: int,
) -> Decimal:
    price_raw = await comet.functions.getPrice(
        AsyncWeb3.to_checksum_address(price_feed)
    ).call(block_identifier=block_number)
    if int(price_raw) <= 0:
        return Decimal("0")
    return Decimal(int(price_raw)) / COMET_PRICE_SCALE


async def _price_from_oracle(
    w3: AsyncWeb3,
    comet: Any,
    price_feed: str,
    block_number: int,
) -> Decimal:
    try:
        return await _price_from_comet(comet, price_feed, block_number)
    except Exception as exc:
        logger.debug(
            "Comet.getPrice failed for feed=%s block=%s, fallback to latestRoundData: %s",
            price_feed,
            block_number,
            exc,
        )
        return await _price_from_feed_direct(w3, price_feed, block_number)


async def _base_token_usd_price(
    w3: AsyncWeb3,
    comet: Any,
    base_token: str,
    base_token_feed: str,
    block_number: int,
) -> Decimal:
    if base_token.lower() == WETH_MAINNET.lower():
        return await _price_from_feed_direct(w3, ETH_USD_PRICE_FEED, block_number)
    return await _price_from_oracle(w3, comet, base_token_feed, block_number)


def _decode_symbol_bytes32(value: Any) -> str | None:
    if not isinstance(value, (bytes, bytearray)):
        return None
    raw = bytes(value).rstrip(b"\x00")
    if not raw:
        return None
    try:
        return raw.decode("utf-8")
    except Exception:
        return None


async def _token_metadata(
    w3: AsyncWeb3,
    token_address: str,
    block_number: int,
    cache: dict[str, tuple[str | None, int | None]],
) -> tuple[str | None, int | None]:
    key = token_address.lower()
    if key in cache:
        return cache[key]

    checksum = AsyncWeb3.to_checksum_address(token_address)
    symbol: str | None = None
    decimals: int | None = None

    try:
        token = w3.eth.contract(address=checksum, abi=ERC20_METADATA_ABI)
        symbol_res, decimals_res = await asyncio.gather(
            token.functions.symbol().call(block_identifier=block_number),
            token.functions.decimals().call(block_identifier=block_number),
        )
        symbol = str(symbol_res) if symbol_res is not None else None
        decimals = int(decimals_res) if decimals_res is not None else None
    except Exception:
        try:
            token_dec = w3.eth.contract(address=checksum, abi=ERC20_METADATA_ABI)
            decimals_res = await token_dec.functions.decimals().call(
                block_identifier=block_number
            )
            decimals = int(decimals_res)
        except Exception:
            decimals = None
        try:
            token_sym32 = w3.eth.contract(
                address=checksum, abi=ERC20_SYMBOL_BYTES32_ABI
            )
            sym32 = await token_sym32.functions.symbol().call(
                block_identifier=block_number
            )
            symbol = _decode_symbol_bytes32(sym32)
        except Exception:
            symbol = None

    cache[key] = (symbol, decimals)
    return cache[key]


async def _collect_v3_market_at_block(
    w3: AsyncWeb3,
    protocol: str,
    market_address: str,
    point_ts: datetime,
    block_number: int,
    metadata_cache: dict[str, tuple[str | None, int | None]],
) -> tuple[MarketSnapshotRow, list[ReserveSnapshotRow]]:
    comet = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(market_address),
        abi=COMET_ABI,
    )

    market_symbol = _resolve_market_name(protocol, market_address)

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

    base_price_usd = await _base_token_usd_price(
        w3, comet, base_token, base_token_feed, block_number
    )
    base_symbol, base_decimals_meta = await _token_metadata(
        w3, base_token, block_number, metadata_cache
    )

    base_scale_dec = Decimal(int(base_scale))
    total_supply = Decimal(int(total_supply_raw)) / base_scale_dec
    total_borrow = Decimal(int(total_borrow_raw)) / base_scale_dec
    utilization = Decimal(int(utilization_raw)) / Decimal(10**18)
    supply_rate = Decimal(int(supply_rate_raw)) / Decimal(10**18)
    borrow_rate = Decimal(int(borrow_rate_raw)) / Decimal(10**18)
    supply_usd = total_supply * base_price_usd
    borrow_usd = total_borrow * base_price_usd
    collateral_usd = Decimal("0")

    market_row = MarketSnapshotRow(
        timestamp=point_ts,
        market=_to_bytes(market_address),
        symbol=market_symbol,
        total_supply=total_supply,
        total_borrow=total_borrow,
        collateral_usd=collateral_usd,
        utilization=utilization,
        borrow_rate=borrow_rate,
        supply_rate=supply_rate,
        price_usd=base_price_usd,
        supply_usd=supply_usd,
        borrow_usd=borrow_usd,
    )

    reserve_rows: list[ReserveSnapshotRow] = [
        ReserveSnapshotRow(
            timestamp=point_ts,
            market=_to_bytes(market_address),
            reserve=_to_bytes(base_token),
            symbol=base_symbol or market_symbol,
            decimals=(
                base_decimals_meta
                if base_decimals_meta is not None
                else _scale_to_decimals(int(base_scale))
            ),
            total_supply=total_supply,
            total_borrow=total_borrow,
            utilization=utilization,
            borrow_rate=borrow_rate,
            supply_rate=supply_rate,
            price_in_base=ONE,
            price_usd=base_price_usd,
            supply_usd=supply_usd,
            borrow_usd=borrow_usd,
        )
    ]

    for i in range(int(num_assets)):
        try:
            asset_info = await comet.functions.getAssetInfo(i).call(
                block_identifier=block_number
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch v3 asset info i=%s market=%s block=%s: %s",
                i,
                market_address,
                block_number,
                exc,
            )
            continue

        # tuple: (offset, asset, priceFeed, scale, ...)
        asset_address = asset_info[1]
        asset_price_feed = asset_info[2]
        asset_scale = int(asset_info[3])

        asset_symbol, asset_decimals_meta = await _token_metadata(
            w3, asset_address, block_number, metadata_cache
        )

        try:
            totals_collateral = await comet.functions.totalsCollateral(
                AsyncWeb3.to_checksum_address(asset_address)
            ).call(block_identifier=block_number)
            total_supply_asset_raw = int(totals_collateral[0])
            asset_price_in_base = await _price_from_oracle(
                w3, comet, asset_price_feed, block_number
            )
        except Exception as exc:
            logger.warning(
                "Failed to price v3 collateral asset i=%s asset=%s feed=%s market=%s block=%s: %s",
                i,
                asset_address,
                asset_price_feed,
                market_address,
                block_number,
                exc,
            )
            continue

        asset_supply = Decimal(total_supply_asset_raw) / Decimal(asset_scale)
        asset_price_usd = asset_price_in_base * base_price_usd
        asset_supply_usd = asset_supply * asset_price_usd
        collateral_usd += asset_supply_usd

        reserve_rows.append(
            ReserveSnapshotRow(
                timestamp=point_ts,
                market=_to_bytes(market_address),
                reserve=_to_bytes(asset_address),
                symbol=asset_symbol,
                decimals=(
                    asset_decimals_meta
                    if asset_decimals_meta is not None
                    else _scale_to_decimals(asset_scale)
                ),
                total_supply=asset_supply,
                total_borrow=Decimal("0"),
                utilization=Decimal("0"),
                borrow_rate=Decimal("0"),
                supply_rate=Decimal("0"),
                price_in_base=asset_price_in_base,
                price_usd=asset_price_usd,
                supply_usd=asset_supply_usd,
                borrow_usd=Decimal("0"),
            )
        )

    market_row.collateral_usd = collateral_usd
    return market_row, reserve_rows


async def _collect_v3_markets_at_block(
    cfg: AppConfig,
    w3: AsyncWeb3,
    point_ts: datetime,
    block_number: int,
    markets: Sequence[str],
    metadata_cache: dict[str, tuple[str | None, int | None]],
) -> tuple[list[MarketSnapshotRow], list[ReserveSnapshotRow]]:
    sem = asyncio.Semaphore(max(1, cfg.crawler.concurrency))

    async def _one_market(
        market: str,
    ) -> tuple[MarketSnapshotRow | None, list[ReserveSnapshotRow]]:
        async with sem:
            try:
                return await _collect_v3_market_at_block(
                    w3,
                    protocol=cfg.protocol,
                    market_address=market,
                    point_ts=point_ts,
                    block_number=block_number,
                    metadata_cache=metadata_cache,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to collect v3 market=%s ts=%s block=%s: %s",
                    market,
                    point_ts.isoformat(),
                    block_number,
                    exc,
                )
                return None, []

    results = await asyncio.gather(*(_one_market(market) for market in markets))
    market_rows: list[MarketSnapshotRow] = []
    reserve_rows: list[ReserveSnapshotRow] = []
    for market_row, rows in results:
        if market_row is not None:
            market_rows.append(market_row)
            reserve_rows.extend(rows)
    return market_rows, reserve_rows


async def _filter_pending_markets(
    pool: asyncpg.Pool,
    protocol: str,
    point_ts: datetime,
    markets: Sequence[str],
) -> tuple[list[str], int]:
    if not markets:
        return [], 0

    market_table = market_table_name(protocol)
    market_keys = [_to_bytes(market) for market in markets if market.startswith("0x")]
    if not market_keys:
        return list(markets), 0

    async with pool.acquire() as conn:
        existing_rows = await conn.fetch(
            f"""
            SELECT market
            FROM loan.{market_table}
            WHERE "timestamp" = $1
              AND market = ANY($2::bytea[])
            """,
            point_ts,
            market_keys,
        )
    existing_market_set = {row["market"] for row in existing_rows}

    pending: list[str] = []
    skipped = 0
    for market in markets:
        if market.startswith("0x") and _to_bytes(market) in existing_market_set:
            skipped += 1
            continue
        pending.append(market)
    return pending, skipped


async def _collect_rows_for_point(
    cfg: AppConfig,
    w3: AsyncWeb3 | None,
    point_ts: datetime,
    markets: Sequence[str],
    pool,
    metadata_cache: dict[str, tuple[str | None, int | None]],
) -> tuple[list[MarketSnapshotRow], list[ReserveSnapshotRow]]:
    if cfg.protocol != "v3" or w3 is None:
        return _build_rows_for_point(point_ts, list(markets))

    block_number = await _block_at_timestamp(w3, int(point_ts.timestamp()), pool=pool)
    return await _collect_v3_markets_at_block(
        cfg,
        w3,
        point_ts=point_ts,
        block_number=block_number,
        markets=markets,
        metadata_cache=metadata_cache,
    )


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
                symbol="MARKET",
                total_supply=zero,
                total_borrow=zero,
                collateral_usd=zero,
                utilization=zero,
                borrow_rate=zero,
                supply_rate=zero,
                price_usd=zero,
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
                symbol=_resolve_market_name("v2", market),
                decimals=18,
                total_supply=zero,
                total_borrow=zero,
                utilization=zero,
                borrow_rate=zero,
                supply_rate=zero,
                price_in_base=zero,
                price_usd=zero,
                supply_usd=zero,
                borrow_usd=zero,
            )
        )
    return market_rows, reserve_rows


async def _writer_loop(
    cfg: AppConfig,
    pool: asyncpg.Pool,
    queue: asyncio.Queue[
        tuple[list[MarketSnapshotRow], list[ReserveSnapshotRow]] | None
    ],
    totals: dict[str, int],
    dry_run: bool,
) -> None:
    while True:
        item = await queue.get()
        try:
            if item is None:
                return
            market_rows, reserve_rows = item
            if dry_run:
                totals["market"] += len(market_rows)
                totals["reserve"] += len(reserve_rows)
                continue

            inserted_market = await upsert_market_snapshots(
                pool, cfg.protocol, market_rows
            )
            inserted_reserve = await upsert_reserve_snapshots(
                pool, cfg.protocol, reserve_rows
            )
            totals["market"] += inserted_market
            totals["reserve"] += inserted_reserve
        finally:
            queue.task_done()


async def run_crawler(
    cfg: AppConfig,
    pool,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    interval_hours: int = 1,
    skip_existing: bool = False,
    dry_run: bool = False,
) -> None:
    await ensure_market_state_tables(
        pool,
        protocol=cfg.protocol,
        use_timescaledb=cfg.market_state.use_timescaledb,
    )

    # 默认采集当前小时；若传入区间，则按配置间隔逐点采集。
    now_utc = datetime.now(timezone.utc)
    interval = timedelta(hours=interval_hours)

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
        "Compound market_state crawl invoked: protocol=%s dry_run=%s skip_existing=%s start=%s end=%s interval_hours=%s points=%s",
        cfg.protocol,
        dry_run,
        skip_existing,
        start.isoformat(),
        end.isoformat(),
        interval_hours,
        len(points),
    )

    markets = _market_addresses(cfg)
    totals: dict[str, int] = {"market": 0, "reserve": 0}
    w3: AsyncWeb3 | None = None
    if cfg.protocol == "v3":
        w3 = await _build_web3(cfg)
    elif cfg.protocol == "v2":
        logger.warning(
            "v2 real collection is not implemented yet, fallback to placeholder rows"
        )

    metadata_cache: dict[str, tuple[str | None, int | None]] = {}

    write_queue: asyncio.Queue[
        tuple[list[MarketSnapshotRow], list[ReserveSnapshotRow]] | None
    ] = asyncio.Queue(maxsize=max(1, cfg.crawler.batch_size))
    writer_task = asyncio.create_task(
        _writer_loop(cfg, pool, write_queue, totals=totals, dry_run=dry_run)
    )

    point_sem = asyncio.Semaphore(max(1, min(4, cfg.crawler.concurrency // 2 or 1)))

    async def _process_point(ts: datetime) -> None:
        async with point_sem:
            logger.debug("market_state point scheduled: %s", ts.isoformat())
            point_markets = list(markets)
            if skip_existing:
                point_markets, skipped_market = await _filter_pending_markets(
                    pool,
                    cfg.protocol,
                    point_ts=ts,
                    markets=point_markets,
                )
                if skipped_market:
                    logger.info(
                        "Skipped existing market snapshots before RPC at %s: market=%s",
                        ts.isoformat(),
                        skipped_market,
                    )
            if not point_markets:
                return

            market_rows, reserve_rows = await _collect_rows_for_point(
                cfg,
                w3,
                point_ts=ts,
                markets=point_markets,
                pool=pool,
                metadata_cache=metadata_cache,
            )
            if not market_rows and not reserve_rows:
                return
            await write_queue.put((market_rows, reserve_rows))

    try:
        await asyncio.gather(*(_process_point(ts) for ts in points))
    finally:
        await write_queue.put(None)
        await write_queue.join()
        await writer_task

    logger.info(
        "Compound market_state crawl done: protocol=%s dry_run=%s market_rows=%s reserve_rows=%s",
        cfg.protocol,
        dry_run,
        totals["market"],
        totals["reserve"],
    )
