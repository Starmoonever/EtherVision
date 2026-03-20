"""Business service layer for Compound API."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from fastapi import HTTPException
from ..constants import COMPOUND_V3_MARKET_NAMES
from ..db import market_table_name, reserve_table_name
from .schemas import (
    MarketStateReserveResponse,
    MarketStateResponse,
    PositionResponse,
    MarketStatePeriodResponse,
)


async def get_market_state_period(
    pool,
    version: str,
    market: str,
    start: str,
    end: str,
    interval: int = 24,
    detail: bool = False,
) -> "MarketStatePeriodResponse":
    if version != "v3":
        raise HTTPException(
            status_code=400,
            detail="当前仅支持 version=v3",
        )
    if interval < 1 or interval > 168:
        raise HTTPException(status_code=400, detail="interval 必须为 1~168 小时")

    start_dt = _parse_hour_utc(start)
    end_dt = _parse_hour_utc(end)
    if start_dt > end_dt:
        raise HTTPException(status_code=400, detail="start 必须小于等于 end")

    market_address = _market_name_to_address(market)
    market_bytes = _address_to_bytes(market_address)
    market_table = market_table_name(version)
    reserve_table = reserve_table_name(version)

    # (已移除函数体内 import)
    points: list[datetime] = []
    cursor = start_dt
    delta = timedelta(hours=interval)
    while cursor <= end_dt:
        points.append(cursor)
        cursor += delta

    async with pool.acquire() as conn:
        # 一次查出所有 market 行
        rows = await conn.fetch(
            f"""
            SELECT
                "timestamp",
                total_supply,
                total_borrow,
                utilization,
                borrow_rate,
                supply_rate,
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
            r["timestamp"].replace(minute=0, second=0, microsecond=0): r for r in rows
        }

        reserves_map: dict[datetime, list[MarketStateReserveResponse]] = {}
        if detail:
            # 一次查出所有 reserve 行
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
            for r in reserve_rows:
                ts = r["timestamp"].replace(minute=0, second=0, microsecond=0)
                reserves_map.setdefault(ts, []).append(
                    MarketStateReserveResponse(
                        reserve="0x" + bytes(r["reserve"]).hex(),
                        symbol=r["symbol"],
                        decimals=r["decimals"],
                        total_supply=_fmt(r["total_supply"]),
                        total_borrow=_fmt(r["total_borrow"]),
                        utilization=_fmt(r["utilization"]),
                        borrow_rate=_fmt(r["borrow_rate"]),
                        supply_rate=_fmt(r["supply_rate"]),
                        supply_usd=_fmt(r["supply_usd"]),
                        borrow_usd=_fmt(r["borrow_usd"]),
                    )
                )

    result: list[MarketStateResponse] = []
    for ts in points:
        row = row_map.get(ts)
        if row is None:
            continue
        reserves = reserves_map.get(ts) if detail else None
        result.append(
            MarketStateResponse(
                version=version,
                market=market.strip().upper(),
                timestamp=row["timestamp"]
                .astimezone(timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
                total_supply=_fmt(row["total_supply"]),
                total_borrow=_fmt(row["total_borrow"]),
                utilization=_fmt(row["utilization"]),
                borrow_rate=_fmt(row["borrow_rate"]),
                supply_rate=_fmt(row["supply_rate"]),
                supply_usd=_fmt(row["supply_usd"]),
                borrow_usd=_fmt(row["borrow_usd"]),
                reserves=reserves,
            )
        )
    return MarketStatePeriodResponse(points=result)


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
            if dt.minute != 0 or dt.second != 0 or dt.microsecond != 0:
                raise HTTPException(
                    status_code=400,
                    detail="date 需精确到小时（分钟和秒必须为 00）",
                )
            return dt
        except ValueError:
            continue
    raise HTTPException(
        status_code=400,
        detail="date 格式无法识别，示例：2026-03-19T12:00:00Z",
    )


def _fmt(value: Decimal | float | int | None) -> str:
    if value is None:
        return "0"
    return str(value)


def _market_name_to_address(market: str) -> str:
    normalized = market.strip().upper()
    for address, name in COMPOUND_V3_MARKET_NAMES.items():
        if name.upper() == normalized:
            return address
    raise HTTPException(
        status_code=400,
        detail="market 仅支持 USDC | USDT | WETH（不区分大小写）",
    )


def _address_to_bytes(address: str) -> bytes:
    addr = address.strip().lower()
    if addr.startswith("0x"):
        addr = addr[2:]
    return bytes.fromhex(addr)


async def get_market_state(
    pool,
    version: str,
    market: str,
    date: str,
    detail: bool,
) -> "MarketStateResponse":
    if version != "v3":
        raise HTTPException(
            status_code=400,
            detail="当前仅支持 version=v3",
        )

    point_ts = _parse_hour_utc(date)
    market_address = _market_name_to_address(market)
    market_bytes = _address_to_bytes(market_address)

    market_table = market_table_name(version)
    reserve_table = reserve_table_name(version)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT
                "timestamp",
                total_supply,
                total_borrow,
                utilization,
                borrow_rate,
                supply_rate,
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
            raise HTTPException(
                status_code=404,
                detail="未找到该时刻的 market state",
            )

        reserves: list[MarketStateReserveResponse] | None = None
        if detail:
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
            reserves = [
                MarketStateReserveResponse(
                    reserve="0x" + bytes(r["reserve"]).hex(),
                    symbol=r["symbol"],
                    decimals=r["decimals"],
                    total_supply=_fmt(r["total_supply"]),
                    total_borrow=_fmt(r["total_borrow"]),
                    utilization=_fmt(r["utilization"]),
                    borrow_rate=_fmt(r["borrow_rate"]),
                    supply_rate=_fmt(r["supply_rate"]),
                    supply_usd=_fmt(r["supply_usd"]),
                    borrow_usd=_fmt(r["borrow_usd"]),
                )
                for r in reserve_rows
            ]

    return MarketStateResponse(
        version=version,
        market=market.strip().upper(),
        timestamp=row["timestamp"]
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        total_supply=_fmt(row["total_supply"]),
        total_borrow=_fmt(row["total_borrow"]),
        utilization=_fmt(row["utilization"]),
        borrow_rate=_fmt(row["borrow_rate"]),
        supply_rate=_fmt(row["supply_rate"]),
        supply_usd=_fmt(row["supply_usd"]),
        borrow_usd=_fmt(row["borrow_usd"]),
        reserves=reserves,
    )
