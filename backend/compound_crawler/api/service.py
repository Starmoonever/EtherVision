"""Business service layer for Compound API."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from ..config import load_config
from ..constants import COMPOUND_V3_MARKET_NAMES
from ..db import market_table_name, reserve_table_name
from ..user_position_snapshots import collect_market_user_snapshots
from .schemas import (
    MarketStatePeriodResponse,
    MarketStateReserveResponse,
    MarketStateResponse,
    PositionAssetResponse,
    PositionResponse,
    UserPositionResponse,
)

_SECONDS_PER_YEAR = Decimal("31536000")
_USER_POSITION_TABLE = "compound_v3_user_position_snapshots"


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

    market_address = _market_to_address(market)
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
                    price_in_base,
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
) -> UserPositionResponse:
    if version != "v3":
        raise HTTPException(status_code=400, detail="当前仅支持 version=v3")

    market_addresses = _markets_to_addresses(market)
    market_bytes_list = [_address_to_bytes(item) for item in market_addresses]
    user_address_bytes = _parse_user_address(address)

    if date is None:
        positions: list[PositionResponse] = []
        for market_address in market_addresses:
            collected = await collect_market_user_snapshots(
                load_config(),
                pool,
                market=market_address,
                point_ts=None,
                persist=False,
                user_addresses=[user_address_bytes],
            )
            positions.extend(_map_and_sort_positions(collected.snapshots))
        return UserPositionResponse(
            version=version,
            address=_bytea_to_address(user_address_bytes),
            positions=_sort_positions(positions),
        )

    point_ts = _parse_midnight_utc(date)
    rows = await _fetch_position_rows(
        pool, point_ts, market_bytes_list, user_address_bytes
    )
    positions = _map_and_sort_positions(rows)
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
        )
        positions.extend(_map_and_sort_positions(collected.snapshots))

    return UserPositionResponse(
        version=version,
        address=_bytea_to_address(user_address_bytes),
        positions=_sort_positions(positions),
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


def _annualize_rate(value: Decimal | float | int | None) -> str:
    if value is None:
        return "0"
    return _fmt(Decimal(str(value)) * _SECONDS_PER_YEAR)


def _markets_to_addresses(market: str) -> list[str]:
    normalized = market.strip().lower()
    if normalized == "all":
        return list(COMPOUND_V3_MARKET_NAMES.keys())
    return [_market_to_address(market)]


def _market_to_address(market: str) -> str:
    normalized = market.strip().lower()
    if normalized.startswith("0x") and len(normalized) == 42:
        for address in COMPOUND_V3_MARKET_NAMES:
            if address.lower() == normalized:
                return address.lower()
        raise HTTPException(
            status_code=400,
            detail="market 仅支持已知的 Compound v3 市场地址、USDC | USDT | WETH，或 all",
        )

    for address, name in COMPOUND_V3_MARKET_NAMES.items():
        if name.lower() == normalized:
            return address
    raise HTTPException(
        status_code=400,
        detail="market 仅支持已知的 Compound v3 市场地址、USDC | USDT | WETH，或 all",
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
        price_in_base=_fmt(row["price_in_base"]),
        price_usd=_fmt(row["price_usd"]),
        supply_usd=_fmt(row["supply_usd"]),
        borrow_usd=_fmt(row["borrow_usd"]),
    )


async def _fetch_position_rows(
    pool,
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
            FROM loan.{_USER_POSITION_TABLE}
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


async def get_market_state(
    pool,
    version: str,
    market: str,
    date: str,
    detail: bool,
) -> MarketStateResponse:
    if version != "v3":
        raise HTTPException(
            status_code=400,
            detail="当前仅支持 version=v3",
        )

    point_ts = _parse_hour_utc(date)
    market_address = _market_to_address(market)
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
                    price_in_base,
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
