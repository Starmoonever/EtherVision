"""Shared 15-minute bucket historical USD price helpers for Ethereum assets."""

from __future__ import annotations

import logging
from decimal import Decimal

import aiohttp
import asyncpg
from fastapi import HTTPException

from aave_crawler.db import (
    get_cached_ethereum_price_usd,
    upsert_ethereum_price_cache,
)

logger = logging.getLogger(__name__)

PRICE_BUCKET_SECONDS = 15 * 60
_MAX_CHART_BUCKETS = 400

# Backward-compatible aliases for older tests and call sites that still patch
# the historical ETH-named helpers from this module.
get_cached_eth_price = get_cached_ethereum_price_usd
upsert_eth_price_timestamp = upsert_ethereum_price_cache


def bucket_timestamp(unix_ts: int) -> int:
    return (unix_ts // PRICE_BUCKET_SECONDS) * PRICE_BUCKET_SECONDS


def bucket_timestamps(start_ts: int, end_ts: int, step_seconds: int) -> list[int]:
    if end_ts < start_ts:
        return []
    points = (end_ts - start_ts) // step_seconds + 1
    return [
        bucket_timestamp(start_ts + index * step_seconds) for index in range(points)
    ]


def _group_contiguous_buckets(buckets: list[int]) -> list[list[int]]:
    if not buckets:
        return []
    ordered = sorted(set(buckets))
    groups: list[list[int]] = [[ordered[0]]]
    for bucket in ordered[1:]:
        if bucket - groups[-1][-1] == PRICE_BUCKET_SECONDS:
            groups[-1].append(bucket)
        else:
            groups.append([bucket])
    return groups


async def _fetch_defillama_historical_price(
    token_address: str,
    *,
    bucket_ts: int,
) -> Decimal:
    coin_key = f"ethereum:{token_address.lower()}"
    url = f"https://coins.llama.fi/prices/historical/{bucket_ts}/{coin_key}"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise HTTPException(
                        status_code=502,
                        detail=f"DeFiLlama 返回 HTTP {resp.status}",
                    )
                data = await resp.json()
    except aiohttp.ClientError as exc:
        raise HTTPException(
            status_code=502, detail=f"无法连接 DeFiLlama: {exc}"
        ) from exc

    entry = data.get("coins", {}).get(coin_key)
    if entry is None or entry.get("price") is None:
        raise HTTPException(
            status_code=404,
            detail=f"DeFiLlama 未返回 '{token_address}' 在该时间桶的价格数据",
        )
    return Decimal(str(entry["price"]))


async def get_historical_price_usd(
    pool: asyncpg.Pool | None,
    *,
    token_address: str,
    asset_label: str,
    requested_ts: int,
) -> tuple[Decimal, int, str]:
    bucket_ts = bucket_timestamp(requested_ts)
    if pool is not None:
        cached = await get_cached_ethereum_price_usd(pool, bucket_ts, token_address)
        if cached is not None:
            return cached, bucket_ts, "defillama"

    price = await _fetch_defillama_historical_price(token_address, bucket_ts=bucket_ts)
    if pool is not None:
        try:
            await upsert_ethereum_price_cache(
                pool,
                bucket_ts,
                token_address,
                asset_label,
                price,
                source="defillama",
            )
        except Exception as exc:
            logger.warning("failed to cache historical price: %s", exc)
    return price, bucket_ts, "defillama"


async def get_historical_prices_usd(
    pool: asyncpg.Pool | None,
    *,
    assets: list[tuple[str, str]],
    requested_ts: int,
) -> tuple[dict[str, Decimal], int, str]:
    bucket_ts = bucket_timestamp(requested_ts)
    if not assets:
        return {}, bucket_ts, "defillama"

    results: dict[str, Decimal] = {}
    by_address: dict[str, str] = {}
    for token_address, asset_label in assets:
        normalized = token_address.lower()
        if normalized not in by_address:
            by_address[normalized] = asset_label

    if pool is not None:
        rows = await pool.fetch(
            """
            SELECT asset_address, price_usd
            FROM loan.eth_price_timestamp
            WHERE timestamp_bucket = $1
              AND asset_address = ANY($2::text[])
            """,
            bucket_ts,
            list(by_address.keys()),
        )
        for row in rows:
            results[str(row["asset_address"]).lower()] = Decimal(str(row["price_usd"]))

    for token_address, asset_label in assets:
        normalized = token_address.lower()
        if normalized in results:
            continue
        price = await _fetch_defillama_historical_price(
            token_address,
            bucket_ts=bucket_ts,
        )
        results[normalized] = price
        if pool is not None:
            try:
                await upsert_ethereum_price_cache(
                    pool,
                    bucket_ts,
                    token_address,
                    asset_label,
                    price,
                    source="defillama",
                )
            except Exception as exc:
                logger.warning("failed to cache historical price: %s", exc)

    return results, bucket_ts, "defillama"


async def _fetch_cached_bucket_prices(
    pool: asyncpg.Pool,
    *,
    token_address: str,
    buckets: list[int],
) -> dict[int, Decimal]:
    if not buckets:
        return {}
    rows = await pool.fetch(
        """
        SELECT timestamp_bucket, price_usd
        FROM loan.eth_price_timestamp
        WHERE asset_address = lower($1)
          AND timestamp_bucket = ANY($2::bigint[])
        ORDER BY timestamp_bucket ASC
        """,
        token_address,
        buckets,
    )
    return {
        int(row["timestamp_bucket"]): Decimal(str(row["price_usd"])) for row in rows
    }


async def _fetch_defillama_chart_buckets(
    token_address: str,
    *,
    start_bucket: int,
    end_bucket: int,
) -> dict[int, Decimal]:
    coin_key = f"ethereum:{token_address.lower()}"
    span = ((end_bucket - start_bucket) // PRICE_BUCKET_SECONDS) + 1
    url = f"https://coins.llama.fi/chart/{coin_key}?start={start_bucket}&span={span}&period=15m"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        ) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise HTTPException(
                        status_code=502,
                        detail=f"DeFiLlama /chart/ 返回 HTTP {resp.status}: {body[:200]}",
                    )
                data = await resp.json()
    except aiohttp.ClientError as exc:
        raise HTTPException(
            status_code=502, detail=f"请求 DeFiLlama 失败: {exc}"
        ) from exc

    prices = data.get("coins", {}).get(coin_key, {}).get("prices", [])
    bucketed: dict[int, Decimal] = {}
    for item in prices:
        if "timestamp" not in item or "price" not in item:
            continue
        bucketed[bucket_timestamp(int(item["timestamp"]))] = Decimal(str(item["price"]))
    return bucketed


async def get_historical_bucket_prices_usd(
    pool: asyncpg.Pool | None,
    *,
    token_address: str,
    asset_label: str,
    buckets: list[int],
) -> dict[int, Decimal]:
    unique_buckets = sorted(set(buckets))
    if not unique_buckets:
        return {}

    cached: dict[int, Decimal] = {}
    if pool is not None:
        cached = await _fetch_cached_bucket_prices(
            pool,
            token_address=token_address,
            buckets=unique_buckets,
        )

    missing = [bucket for bucket in unique_buckets if bucket not in cached]
    fetched: dict[int, Decimal] = {}
    for group in _group_contiguous_buckets(missing):
        if not group:
            continue
        if len(group) == 1:
            continue
        for chunk_start in range(0, len(group), _MAX_CHART_BUCKETS):
            chunk = group[chunk_start : chunk_start + _MAX_CHART_BUCKETS]
            if not chunk:
                continue
            fetched.update(
                await _fetch_defillama_chart_buckets(
                    token_address,
                    start_bucket=chunk[0],
                    end_bucket=chunk[-1],
                )
            )

    result = dict(cached)
    for bucket in missing:
        price = fetched.get(bucket)
        if price is None:
            price, _, _ = await get_historical_price_usd(
                pool,
                token_address=token_address,
                asset_label=asset_label,
                requested_ts=bucket,
            )
        else:
            if pool is not None:
                try:
                    await upsert_ethereum_price_cache(
                        pool,
                        bucket,
                        token_address,
                        asset_label,
                        price,
                        source="defillama",
                    )
                except Exception as exc:
                    logger.warning("failed to cache historical bucket price: %s", exc)
        result[bucket] = price

    return result
