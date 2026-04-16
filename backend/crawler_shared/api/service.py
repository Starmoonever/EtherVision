"""Protocol-agnostic price API services."""

from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

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
    try:
        return AsyncWeb3.to_checksum_address(asset.strip())
    except ValueError:
        return None


async def _resolve_price_asset(
    *,
    symbol: str | None,
    address: str | None,
) -> tuple[str, str, bool]:
    from fastapi import HTTPException

    if (symbol is None) == (address is None):
        raise HTTPException(
            status_code=400,
            detail="symbol 和 address 必须且只能提供其中一个",
        )

    if address is not None:
        normalized_address = _normalize_token_address(address)
        if normalized_address is None:
            raise HTTPException(status_code=400, detail="address 不是有效的 EVM 地址")
        registered = ETHEREUM_PRICE_ASSET_BY_ADDRESS.get(normalized_address.lower())
        if registered is not None:
            registered_asset, token_address, _ = registered
            return registered_asset, token_address, False
        return normalized_address, normalized_address, False

    assert symbol is not None
    normalized_asset = _normalize_price_asset(symbol)
    target = PRICE_ASSET_ALIASES.get(normalized_asset.upper(), normalized_asset.upper())
    registered = ETHEREUM_PRICE_ASSETS.get(target.upper())
    if registered is not None:
        registered_asset, token_address, _ = registered
        return registered_asset, token_address, False

    raise HTTPException(
        status_code=404,
        detail=f"未找到 symbol '{symbol}' 对应的受支持资产",
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
    timestamp: int | None = None,
) -> PriceResponse:
    from fastapi import HTTPException

    resolved_asset, token_address, _ = await _resolve_price_asset(
        symbol=symbol,
        address=address,
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
) -> PricePeriodResponse:
    from fastapi import HTTPException

    if end < start:
        raise HTTPException(status_code=400, detail="end 必须晚于或等于 start")
    if interval < 1:
        raise HTTPException(status_code=400, detail="interval 必须 >= 1 分钟")

    resolved_asset, token_address, _ = await _resolve_price_asset(
        symbol=symbol,
        address=address,
    )
    step = interval * 60
    expected_buckets = bucket_timestamps(start, end, step)
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
