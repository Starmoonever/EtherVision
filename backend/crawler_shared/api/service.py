"""Protocol-agnostic price API services."""

from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import asyncpg
from web3 import AsyncWeb3

from aave_crawler.rpc import (
    CONTRACTS_V3,
    ORACLE_ABI,
    WETH_ADDRESS,
    get_all_reserve_tokens,
    get_assets_prices,
    get_contracts,
    get_reserve_config,
)
from crawler_shared.price_history import (
    bucket_timestamps,
    get_historical_bucket_prices_usd,
    get_historical_price_usd,
)
from justlend_crawler.api.service import (
    _fetch_justlend_market_catalog,
    _normalize_tron_address,
)
from justlend_crawler.constants import JUSTLEND_CHAIN
from justlend_crawler.db import (
    ensure_tron_price_cache_table,
    get_cached_tron_bucket_prices_usd,
    get_cached_tron_price_usd,
    upsert_tron_price_cache,
)
from .constants import (
    ETHEREUM_PRICE_ASSET_BY_ADDRESS,
    ETHEREUM_PRICE_ASSETS,
    PRICE_ASSET_ALIASES,
    SUPPORTED_PRICE_ASSETS,
)
from .schemas import (
    PriceAssetsResponse,
    PriceAssetSchema,
    PricePeriodItem,
    PricePeriodResponse,
    PriceResponse,
)

logger = logging.getLogger(__name__)

_cache: dict = {}
_TRON_PRICE_CACHE_TTL_SECONDS = 60

_SQL_COMPOUND_V3_RESERVE_BY_SYMBOL = """
SELECT
    symbol,
    CONCAT('0x', encode(reserve, 'hex')) AS token_address
FROM loan.compound_v3_market_snapshot_reserves
WHERE symbol IS NOT NULL
  AND UPPER(symbol) = $1
ORDER BY "timestamp" DESC
LIMIT 1
"""

_SQL_JUSTLEND_LATEST_CURRENT_PRICE = """
SELECT
    price_usd,
    snapshot_at
FROM loan.justlend_markets_current
WHERE underlying_address = $1
  AND price_usd IS NOT NULL
ORDER BY snapshot_at DESC
LIMIT 1
"""

_SQL_JUSTLEND_LATEST_SNAPSHOT_PRICE = """
SELECT
    price_usd,
    snapshot_at
FROM loan.justlend_market_snapshots
WHERE underlying_address = $1
  AND snapshot_at <= to_timestamp($2)
  AND price_usd IS NOT NULL
ORDER BY snapshot_at DESC
LIMIT 1
"""

_SQL_JUSTLEND_SNAPSHOT_BUCKET_PRICES = """
SELECT DISTINCT ON (snapshot_bucket)
    snapshot_bucket AS timestamp_bucket,
    price_usd
FROM (
    SELECT
        ((EXTRACT(EPOCH FROM snapshot_at)::bigint / 900) * 900) AS snapshot_bucket,
        snapshot_at,
        price_usd
    FROM loan.justlend_market_snapshots
    WHERE underlying_address = $1
      AND price_usd IS NOT NULL
      AND ((EXTRACT(EPOCH FROM snapshot_at)::bigint / 900) * 900) = ANY($2::bigint[])
) AS bucketed
ORDER BY snapshot_bucket ASC, snapshot_at DESC
"""

_SQL_COMPOUND_V3_LATEST_RESERVE_PRICE = """
SELECT
    price_usd,
    "timestamp"
FROM loan.compound_v3_market_snapshot_reserves
WHERE reserve = decode(replace(lower($1), '0x', ''), 'hex')
ORDER BY "timestamp" DESC
LIMIT 1
"""


def _fmt(value: Decimal, decimals: int = 2) -> str:
    quantize = Decimal(10) ** -decimals
    return str(value.quantize(quantize, rounding=ROUND_HALF_UP))


async def _get_common_data(w3: AsyncWeb3, protocol: str = "v3") -> tuple:
    contracts = get_contracts(protocol)
    cache_key_tokens = f"reserve_tokens_{protocol}"
    cache_key_configs = f"reserve_configs_{protocol}"
    cache_key_addresses = f"token_addresses_{protocol}"

    if cache_key_tokens not in _cache:
        reserve_tokens = await get_all_reserve_tokens(w3, contracts)
        token_addresses = [rt.token_address for rt in reserve_tokens]
        configs = await asyncio.gather(
            *[
                get_reserve_config(w3, address, contracts)
                for address in token_addresses
            ],
            return_exceptions=True,
        )
        reserve_configs = {
            address: config
            for address, config in zip(token_addresses, configs)
            if not isinstance(config, Exception)
        }
        _cache[cache_key_tokens] = reserve_tokens
        _cache[cache_key_configs] = reserve_configs
        _cache[cache_key_addresses] = token_addresses
        logger.info("[%s] cached reserve tokens: %d", protocol, len(reserve_tokens))

    prices = await get_assets_prices(w3, _cache[cache_key_addresses], contracts)
    asset_prices = dict(zip(_cache[cache_key_addresses], prices))

    if contracts.oracle_price_in_eth:
        v3_oracle = w3.eth.contract(address=CONTRACTS_V3.oracle, abi=ORACLE_ABI)
        eth_usd_raw: int = await v3_oracle.functions.getAssetPrice(WETH_ADDRESS).call()
        if eth_usd_raw > 0:
            asset_prices = {
                address: (price * eth_usd_raw) // (10**18)
                for address, price in asset_prices.items()
            }
            asset_prices[WETH_ADDRESS] = eth_usd_raw
        else:
            logger.warning("[v2] failed to normalize oracle prices with ETH/USD")

    return _cache[cache_key_tokens], _cache[cache_key_configs], asset_prices


def _normalize_price_asset(asset: str) -> str:
    return asset.strip()


def _is_evm_token_address(asset: str) -> bool:
    value = asset.strip()
    return value.startswith("0x") and len(value) == 42


def _normalize_token_address(asset: str) -> str | None:
    if not _is_evm_token_address(asset):
        return None
    return asset.strip()


def _normalize_chain(chain: str | None) -> str:
    if chain is None:
        return "ethereum"
    normalized = chain.strip().lower()
    if normalized in {"eth", "ethereum"}:
        return "ethereum"
    if normalized in {"tron", "trx"}:
        return JUSTLEND_CHAIN
    from fastapi import HTTPException

    raise HTTPException(status_code=400, detail=f"不支持的 chain: {chain}")


def _resolve_cache_asset_symbol(
    *,
    resolved_asset: str,
    token_address: str,
    asset_chain: str,
) -> str:
    if asset_chain != JUSTLEND_CHAIN:
        return resolved_asset
    for asset, registered_token, chain in SUPPORTED_PRICE_ASSETS:
        if chain == JUSTLEND_CHAIN and registered_token == token_address:
            return asset
    return resolved_asset


async def _resolve_price_asset(
    *,
    symbol: str | None,
    address: str | None,
    chain: str | None = None,
) -> tuple[str, str, str]:
    from fastapi import HTTPException

    normalized_chain = _normalize_chain(chain)

    if (symbol is None) == (address is None):
        raise HTTPException(
            status_code=400,
            detail="symbol 和 address 必须且只能提供其中一个",
        )

    if address is not None:
        normalized_address = _normalize_token_address(address)
        if normalized_address is not None:
            if normalized_chain != "ethereum":
                raise HTTPException(
                    status_code=400,
                    detail="address 与 chain 不匹配：EVM 地址必须使用 ethereum",
                )
            registered = ETHEREUM_PRICE_ASSET_BY_ADDRESS.get(normalized_address.lower())
            if registered is not None:
                registered_asset, token_address, asset_chain = registered
                return registered_asset, token_address, asset_chain
            return normalized_address, normalized_address, "ethereum"

        normalized_tron_address = _normalize_tron_address(address)
        if normalized_tron_address is not None:
            if normalized_chain != JUSTLEND_CHAIN:
                raise HTTPException(
                    status_code=400,
                    detail="address 与 chain 不匹配：TRON 地址必须使用 tron",
                )
            for asset, token_address, asset_chain in SUPPORTED_PRICE_ASSETS:
                if (
                    asset_chain == JUSTLEND_CHAIN
                    and token_address == normalized_tron_address
                ):
                    return asset, token_address, asset_chain
            return normalized_tron_address, normalized_tron_address, JUSTLEND_CHAIN

        raise HTTPException(
            status_code=400,
            detail="address 不是有效的 EVM 或 TRON Base58 地址",
        )

    assert symbol is not None
    normalized_asset = _normalize_price_asset(symbol)
    target = PRICE_ASSET_ALIASES.get(normalized_asset.upper(), normalized_asset.upper())
    if normalized_chain == "ethereum":
        registered = ETHEREUM_PRICE_ASSETS.get(target.upper())
        if registered is not None:
            registered_asset, token_address, asset_chain = registered
            return registered_asset, token_address, asset_chain
    else:
        for asset, token_address, asset_chain in SUPPORTED_PRICE_ASSETS:
            if asset_chain == JUSTLEND_CHAIN and asset.upper() == target.upper():
                return asset, token_address, asset_chain

    raise HTTPException(
        status_code=404,
        detail=f"未找到 symbol '{symbol}' 在 chain '{normalized_chain}' 对应的受支持资产",
    )


async def _fetch_defillama_current_price(
    token_address: str,
) -> tuple[Decimal, int] | None:
    import asyncio
    import aiohttp
    from fastapi import HTTPException

    coin_key = f"ethereum:{token_address.lower()}"
    current_ts = int(_time.time())
    urls = (
        f"https://coins.llama.fi/prices/current/{coin_key}",
        f"https://coins.llama.fi/prices/historical/{current_ts}/{coin_key}",
    )

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            for url in urls:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    entry = data.get("coins", {}).get(coin_key)
                    if entry is None or entry.get("price") is None:
                        continue
                    return Decimal(str(entry["price"])), int(
                        entry.get("timestamp", current_ts)
                    )
    except (aiohttp.ClientError, asyncio.TimeoutError, asyncio.CancelledError) as exc:
        raise HTTPException(
            status_code=502, detail=f"无法连接 DeFiLlama: {exc}"
        ) from exc

    return None


async def _fetch_coingecko_current_price(
    token_address: str,
) -> tuple[Decimal, int] | None:
    import asyncio
    import aiohttp
    from fastapi import HTTPException

    normalized_address = token_address.lower()
    urls = (
        (
            "simple",
            "https://api.coingecko.com/api/v3/simple/token_price/ethereum"
            f"?contract_addresses={normalized_address}"
            "&vs_currencies=usd&include_last_updated_at=true",
        ),
        (
            "onchain",
            "https://api.coingecko.com/api/v3/onchain/simple/networks/eth/"
            f"token_price/{normalized_address}",
        ),
    )

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            for mode, url in urls:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    if mode == "simple":
                        entry = data.get(normalized_address)
                        if entry is None or entry.get("usd") is None:
                            continue
                        return Decimal(str(entry["usd"])), int(
                            entry.get("last_updated_at", _time.time())
                        )

                    attributes = data.get("data", {}).get("attributes", {})
                    token_prices = attributes.get("token_prices", {})
                    price_raw = token_prices.get(normalized_address)
                    if price_raw is None:
                        continue
                    last_trade_ts = attributes.get("last_trade_timestamp", {})
                    return Decimal(str(price_raw)), int(
                        last_trade_ts.get(normalized_address, _time.time())
                    )
    except (aiohttp.ClientError, asyncio.TimeoutError, asyncio.CancelledError) as exc:
        raise HTTPException(
            status_code=502, detail=f"无法连接 CoinGecko: {exc}"
        ) from exc

    return None


async def _get_latest_compound_v3_reserve_price(
    pool: asyncpg.Pool,
    token_address: str,
) -> tuple[Decimal, int] | None:
    row = await pool.fetchrow(_SQL_COMPOUND_V3_LATEST_RESERVE_PRICE, token_address)
    if row is None or row["price_usd"] is None or row["timestamp"] is None:
        return None
    return Decimal(str(row["price_usd"])), int(row["timestamp"].timestamp())


async def _get_latest_justlend_current_price(
    pool: asyncpg.Pool,
    token_address: str,
) -> tuple[Decimal, int] | None:
    row = await pool.fetchrow(_SQL_JUSTLEND_LATEST_CURRENT_PRICE, token_address)
    if row is None or row["price_usd"] is None or row["snapshot_at"] is None:
        return None
    return Decimal(str(row["price_usd"])), int(row["snapshot_at"].timestamp())


async def _get_latest_justlend_snapshot_price(
    pool: asyncpg.Pool,
    token_address: str,
    timestamp: int,
) -> tuple[Decimal, int] | None:
    row = await pool.fetchrow(
        _SQL_JUSTLEND_LATEST_SNAPSHOT_PRICE, token_address, timestamp
    )
    if row is None or row["price_usd"] is None or row["snapshot_at"] is None:
        return None
    return Decimal(str(row["price_usd"])), int(row["snapshot_at"].timestamp())


async def _get_justlend_snapshot_bucket_prices(
    pool: asyncpg.Pool,
    *,
    token_address: str,
    buckets: list[int],
) -> dict[int, Decimal]:
    if not buckets:
        return {}
    rows = await pool.fetch(
        _SQL_JUSTLEND_SNAPSHOT_BUCKET_PRICES,
        token_address,
        sorted(set(buckets)),
    )
    result: dict[int, Decimal] = {}
    for row in rows:
        if row["price_usd"] is None:
            continue
        result[int(row["timestamp_bucket"])] = Decimal(str(row["price_usd"]))
    return result


async def _get_tron_market_prices_from_api(
    cfg: Any,
    tron_rpc: Any,
) -> tuple[dict[str, tuple[str, Decimal]], int]:
    now_ts = int(_time.time())
    cache_key = "tron_market_prices"
    cached = _cache.get(cache_key)
    if (
        isinstance(cached, tuple)
        and len(cached) == 2
        and now_ts - int(cached[1]) < _TRON_PRICE_CACHE_TTL_SECONDS
    ):
        return cached  # type: ignore[return-value]

    catalog = await _fetch_justlend_market_catalog(
        cfg,
        tron_rpc=tron_rpc,
        market_addresses=[],
    )
    prices: dict[str, tuple[str, Decimal]] = {}
    for entry in catalog.values():
        if not isinstance(entry, dict):
            continue
        asset_address = _normalize_tron_address(entry.get("underlying_address"))
        symbol = str(entry.get("underlying_symbol") or "").strip().upper()
        price_usd = entry.get("price_usd")
        if not asset_address or not symbol or price_usd is None:
            continue
        prices[asset_address] = (symbol, Decimal(str(price_usd)))
    value = (prices, now_ts)
    _cache[cache_key] = value
    return value


async def _lazy_fill_current_tron_bucket(
    *,
    pool: asyncpg.Pool,
    cfg: Any,
    tron_rpc: Any,
) -> tuple[dict[str, tuple[str, Decimal]], int]:
    await ensure_tron_price_cache_table(pool)
    prices, fetched_ts = await _get_tron_market_prices_from_api(cfg, tron_rpc)
    await asyncio.gather(
        *[
            upsert_tron_price_cache(
                pool,
                fetched_ts,
                asset_address,
                symbol,
                price_usd,
                source="justlend-api",
            )
            for asset_address, (symbol, price_usd) in prices.items()
        ]
    )
    return prices, fetched_ts


async def _cache_tron_price(
    *,
    pool: asyncpg.Pool,
    unix_ts: int,
    asset_address: str,
    asset_symbol: str,
    price_usd: Decimal,
    source: str,
) -> None:
    try:
        await upsert_tron_price_cache(
            pool,
            unix_ts,
            asset_address,
            asset_symbol,
            price_usd,
            source=source,
        )
    except Exception as exc:
        logger.warning(
            "failed to cache tron price asset=%s bucket=%s source=%s: %s",
            asset_address,
            unix_ts,
            source,
            exc,
        )


def _ts_to_utc_str(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def get_supported_price_assets() -> PriceAssetsResponse:
    return PriceAssetsResponse(
        assets=[
            PriceAssetSchema(asset=asset, token_address=token_address, chain=chain)
            for asset, token_address, chain in SUPPORTED_PRICE_ASSETS
        ]
    )


async def get_price(
    w3: AsyncWeb3,
    *,
    symbol: str | None,
    address: str | None,
    pool: asyncpg.Pool | None,
    chain: str | None = None,
    justlend_cfg: Any | None = None,
    tron_rpc: Any | None = None,
    timestamp: int | None = None,
) -> PriceResponse:
    from fastapi import HTTPException

    resolved_asset, token_address, asset_chain = await _resolve_price_asset(
        symbol=symbol,
        address=address,
        chain=chain,
    )
    cache_asset_symbol = _resolve_cache_asset_symbol(
        resolved_asset=resolved_asset,
        token_address=token_address,
        asset_chain=asset_chain,
    )

    if asset_chain == JUSTLEND_CHAIN:
        if pool is None:
            raise HTTPException(
                status_code=503, detail="数据库连接尚未就绪，请稍后重试"
            )

        if timestamp is None:
            current_price = await _get_latest_justlend_current_price(
                pool, token_address
            )
            if current_price is not None:
                price, snapshot_ts = current_price
                await ensure_tron_price_cache_table(pool)
                await _cache_tron_price(
                    pool=pool,
                    unix_ts=snapshot_ts,
                    asset_address=token_address,
                    asset_symbol=cache_asset_symbol,
                    price_usd=price,
                    source="justlend-current",
                )
                return PriceResponse(
                    asset=resolved_asset,
                    price_usd=_fmt(price, 2),
                    token_address=token_address,
                    timestamp=_ts_to_utc_str(snapshot_ts),
                    source="justlend-current",
                )

            if justlend_cfg is not None:
                prices, fetched_ts = await _lazy_fill_current_tron_bucket(
                    pool=pool,
                    cfg=justlend_cfg,
                    tron_rpc=tron_rpc,
                )
                current = prices.get(token_address)
                if current is not None:
                    _, price = current
                    return PriceResponse(
                        asset=resolved_asset,
                        price_usd=_fmt(price, 2),
                        token_address=token_address,
                        timestamp=_ts_to_utc_str(fetched_ts),
                        source="justlend-api",
                    )

            raise HTTPException(
                status_code=502,
                detail=f"无法获取资产 '{symbol or address}' 的 TRON 实时价格",
            )

        await ensure_tron_price_cache_table(pool)
        cached = await get_cached_tron_price_usd(pool, timestamp, token_address)
        if cached is not None:
            return PriceResponse(
                asset=resolved_asset,
                price_usd=_fmt(cached, 2),
                token_address=token_address,
                timestamp=_ts_to_utc_str((timestamp // 900) * 900),
                source="justlend-cache",
            )

        now_bucket = (int(_time.time()) // 900) * 900
        requested_bucket = (timestamp // 900) * 900
        if requested_bucket == now_bucket and justlend_cfg is not None:
            prices, fetched_ts = await _lazy_fill_current_tron_bucket(
                pool=pool,
                cfg=justlend_cfg,
                tron_rpc=tron_rpc,
            )
            current = prices.get(token_address)
            if current is not None:
                _, price = current
                return PriceResponse(
                    asset=resolved_asset,
                    price_usd=_fmt(price, 2),
                    token_address=token_address,
                    timestamp=_ts_to_utc_str((fetched_ts // 900) * 900),
                    source="justlend-api",
                )

        snapshot = await _get_latest_justlend_snapshot_price(
            pool, token_address, timestamp
        )
        if snapshot is not None:
            price, snapshot_ts = snapshot
            return PriceResponse(
                asset=resolved_asset,
                price_usd=_fmt(price, 2),
                token_address=token_address,
                timestamp=_ts_to_utc_str(snapshot_ts),
                source="justlend-snapshot",
            )

        raise HTTPException(
            status_code=404,
            detail=f"未找到资产 '{symbol or address}' 的 TRON 历史价格",
        )

    if timestamp is None:
        oracle_exc: Exception | None = None
        try:
            prices = await get_assets_prices(w3, [token_address])
        except Exception as exc:
            prices = []
            oracle_exc = exc

        if prices and prices[0] > 0:
            price = Decimal(prices[0]) / Decimal(10**8)
            return PriceResponse(
                asset=resolved_asset,
                price_usd=_fmt(price, 2),
                token_address=token_address,
                timestamp=_ts_to_utc_str(int(_time.time())),
                source="on-chain",
            )

        if pool is not None:
            snapshot = await _get_latest_compound_v3_reserve_price(pool, token_address)
            if snapshot is not None:
                price, snapshot_ts = snapshot
                return PriceResponse(
                    asset=resolved_asset,
                    price_usd=_fmt(price, 2),
                    token_address=token_address,
                    timestamp=_ts_to_utc_str(snapshot_ts),
                    source="compound-snapshot",
                )

        latest_price = await _fetch_defillama_current_price(token_address)
        if latest_price is not None:
            price, price_ts = latest_price
            return PriceResponse(
                asset=resolved_asset,
                price_usd=_fmt(price, 2),
                token_address=token_address,
                timestamp=_ts_to_utc_str(price_ts),
                source="defillama",
            )

        coingecko_price = await _fetch_coingecko_current_price(token_address)
        if coingecko_price is not None:
            price, price_ts = coingecko_price
            return PriceResponse(
                asset=resolved_asset,
                price_usd=_fmt(price, 2),
                token_address=token_address,
                timestamp=_ts_to_utc_str(price_ts),
                source="coingecko",
            )

        if oracle_exc is not None:
            logger.warning(
                "failed to fetch realtime price asset=%s token=%s: %s",
                symbol or address,
                token_address,
                oracle_exc,
            )
        raise HTTPException(
            status_code=502,
            detail=f"无法获取资产 '{symbol or address}' 的实时价格",
        )

    price, bucket_ts, source = await get_historical_price_usd(
        pool,
        token_address=token_address,
        asset_label=resolved_asset,
        requested_ts=timestamp,
    )

    return PriceResponse(
        asset=resolved_asset,
        price_usd=_fmt(price, 2),
        token_address=token_address,
        timestamp=_ts_to_utc_str(bucket_ts),
        source=source,
    )


async def get_price_period_service(
    w3: AsyncWeb3,
    pool: asyncpg.Pool | None,
    *,
    symbol: str | None,
    address: str | None,
    start: int,
    end: int,
    interval: int,
    chain: str | None = None,
    justlend_cfg: Any | None = None,
    tron_rpc: Any | None = None,
) -> PricePeriodResponse:
    from fastapi import HTTPException

    if end < start:
        raise HTTPException(status_code=400, detail="end 必须晚于或等于 start")
    if interval < 15:
        raise HTTPException(status_code=400, detail="interval 必须 >= 15 分钟")

    resolved_asset, token_address, asset_chain = await _resolve_price_asset(
        symbol=symbol,
        address=address,
        chain=chain,
    )
    step = interval * 60
    expected_buckets = bucket_timestamps(start, end, step)

    if asset_chain == JUSTLEND_CHAIN:
        if pool is None:
            raise HTTPException(
                status_code=503, detail="数据库连接尚未就绪，请稍后重试"
            )
        await ensure_tron_price_cache_table(pool)
        price_map = await get_cached_tron_bucket_prices_usd(
            pool,
            asset_address=token_address,
            buckets=expected_buckets,
        )
        now_bucket = (int(_time.time()) // 900) * 900
        if (
            now_bucket in expected_buckets
            and now_bucket not in price_map
            and justlend_cfg is not None
        ):
            prices, _ = await _lazy_fill_current_tron_bucket(
                pool=pool,
                cfg=justlend_cfg,
                tron_rpc=tron_rpc,
            )
            current = prices.get(token_address)
            if current is not None:
                _, price = current
                price_map[now_bucket] = price

        missing = [bucket for bucket in expected_buckets if bucket not in price_map]
        used_snapshot_fallback = False
        if missing:
            used_snapshot_fallback = True
            snapshot_prices = await _get_justlend_snapshot_bucket_prices(
                pool,
                token_address=token_address,
                buckets=missing,
            )
            price_map.update(snapshot_prices)

        items = [
            PricePeriodItem(
                price_usd=_fmt(price_map[bucket], 2),
                timestamp=_ts_to_utc_str(bucket),
            )
            for bucket in expected_buckets
            if bucket in price_map
        ]
        if not items:
            raise HTTPException(
                status_code=404,
                detail=f"未找到 '{symbol or address}' 在指定区间的 TRON 价格数据",
            )
        source = "justlend-mixed" if used_snapshot_fallback else "justlend-cache"
        return PricePeriodResponse(
            asset=resolved_asset,
            token_address=token_address,
            source=source,
            prices=items,
        )

    price_map = await get_historical_bucket_prices_usd(
        pool,
        token_address=token_address,
        asset_label=resolved_asset,
        buckets=expected_buckets,
    )
    items = [
        PricePeriodItem(
            price_usd=_fmt(price_map[bucket], 2),
            timestamp=_ts_to_utc_str(bucket),
        )
        for bucket in expected_buckets
        if bucket in price_map
    ]
    if not items:
        raise HTTPException(
            status_code=404,
            detail=f"DeFiLlama 未返回 '{symbol or address}' 在指定区间的价格数据",
        )
    return PricePeriodResponse(
        asset=resolved_asset,
        token_address=token_address,
        source="defillama",
        prices=items,
    )
