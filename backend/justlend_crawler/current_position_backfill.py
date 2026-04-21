"""Backfill JustLend current positions for users derived from history."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
import logging

import asyncpg
from fastapi import HTTPException

from crawler_shared.tron_rpc import TronRpcClient
from .api.service import (
    _extract_market_address_from_contract,
    _extract_market_address_from_parse_input,
    _normalize_tron_address,
    _tron_address_to_bytes,
    _tron_bytes_to_base58,
)
from .config import AppConfig
from .constants import JUSTLEND_REPLAY_METHOD_IDS
from .db import (
    _CANDIDATE_HISTORY_CONTRACT_TYPE_COLUMNS,
    _CANDIDATE_HISTORY_STATUS_COLUMNS,
    _CANDIDATE_HISTORY_TIME_COLUMNS,
    _CANDIDATE_HISTORY_USER_COLUMNS,
    _first_existing_column,
    delete_current_user_position,
    ensure_justlend_tables,
    fetch_all_current_user_addresses,
    fetch_justlend_markets_current,
    upsert_current_user_position,
)
from .rpc import fetch_justlend_position_via_rpc

_MATCH_MODES = {"any", "all"}
_USER_SOURCES = {"history", "current", "union"}
_DETAIL_SAMPLE_LIMIT = 20

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CurrentPositionBackfillStats:
    selected_users: int = 0
    updated_users: int = 0
    deleted_users: int = 0
    failed_users: int = 0
    skipped_users: int = 0
    deleted_addresses: list[str] = field(default_factory=list)
    failed_reason_counts: dict[str, int] = field(default_factory=dict)
    failed_details: list[dict[str, str]] = field(default_factory=list)


def _record_failed_reason(
    stats: CurrentPositionBackfillStats,
    *,
    user_address: str,
    reason: str,
) -> None:
    stats.failed_reason_counts[reason] = stats.failed_reason_counts.get(reason, 0) + 1
    stats.failed_details.append({"user_address": user_address, "reason": reason})


def _record_deleted_address(
    stats: CurrentPositionBackfillStats,
    *,
    user_address: str,
) -> None:
    stats.deleted_addresses.append(user_address)


def merge_user_addresses(*groups: Iterable[bytes]) -> list[bytes]:
    ordered: OrderedDict[bytes, None] = OrderedDict()
    for group in groups:
        for user_address in group:
            ordered[bytes(user_address)] = None
    return list(ordered.keys())


def normalize_user_address_bytes(address: bytes) -> bytes:
    normalized = _normalize_tron_address(address)
    if normalized is None:
        return bytes(address)
    return _tron_address_to_bytes(normalized)


def normalize_user_addresses(
    addresses: Iterable[bytes],
) -> tuple[list[bytes], dict[bytes, list[bytes]]]:
    canonical_ordered: OrderedDict[bytes, None] = OrderedDict()
    aliases_by_canonical: dict[bytes, list[bytes]] = {}
    for raw_address in addresses:
        original = bytes(raw_address)
        canonical = normalize_user_address_bytes(original)
        canonical_ordered[canonical] = None
        if canonical != original:
            aliases_by_canonical.setdefault(canonical, []).append(original)
    return list(canonical_ordered.keys()), aliases_by_canonical


def build_target_address_symbol_map(
    market_rows: Iterable[Any],
    *,
    target_symbols: set[str],
) -> dict[str, str]:
    address_to_symbol: dict[str, str] = {}
    for row in market_rows:
        symbol = (
            str(
                getattr(row, "underlying_symbol", None)
                or row["underlying_symbol"]
                or ""
            )
            .strip()
            .upper()
        )
        if symbol not in target_symbols:
            continue
        for raw_address_key in ("market_address", "underlying_address"):
            raw_address = getattr(row, raw_address_key, None) or row[raw_address_key]
            normalized = _normalize_tron_address(raw_address)
            if normalized:
                address_to_symbol[normalized] = symbol
    return address_to_symbol


def collect_history_user_matches(
    rows: Iterable[Any],
    *,
    address_to_symbol: dict[str, str],
    target_symbols: set[str],
    match_mode: str,
) -> list[bytes]:
    normalized_match_mode = match_mode.strip().lower()
    if normalized_match_mode not in _MATCH_MODES:
        raise ValueError(f"unsupported match_mode: {match_mode}")

    matched_by_user: OrderedDict[bytes, set[str]] = OrderedDict()
    for row in rows:
        user_address = row["user_address"]
        if user_address is None:
            continue
        user_key = bytes(user_address)
        if user_key not in matched_by_user:
            matched_by_user[user_key] = set()
        for candidate in (
            _extract_market_address_from_contract(row.get("contract")),
            _extract_market_address_from_parse_input(row.get("parse_input")),
        ):
            if candidate is None:
                continue
            symbol = address_to_symbol.get(candidate)
            if symbol is not None:
                matched_by_user[user_key].add(symbol)

    if normalized_match_mode == "all":
        return [
            user_address
            for user_address, symbols in matched_by_user.items()
            if target_symbols.issubset(symbols)
        ]
    return [
        user_address for user_address, symbols in matched_by_user.items() if symbols
    ]


def _coerce_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _scan_history_rows_for_target_users(
    pool: asyncpg.Pool,
    *,
    address_to_symbol: dict[str, str],
    target_symbols: set[str],
    match_mode: str,
    start_time: datetime | None,
    end_time: datetime | None,
    only_success: bool,
) -> list[bytes]:
    async with pool.acquire() as conn:
        column_rows = await conn.fetch(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'justlend'
              AND table_name = 'justlend_history'
            """
        )
        if not column_rows:
            raise RuntimeError("justlend.justlend_history not found")

        column_types = {
            str(row["column_name"]): str(row["data_type"]) for row in column_rows
        }
        user_col = _first_existing_column(column_types, _CANDIDATE_HISTORY_USER_COLUMNS)
        status_col = _first_existing_column(
            column_types, _CANDIDATE_HISTORY_STATUS_COLUMNS
        )
        contract_type_col = _first_existing_column(
            column_types, _CANDIDATE_HISTORY_CONTRACT_TYPE_COLUMNS
        )
        time_col = _first_existing_column(column_types, _CANDIDATE_HISTORY_TIME_COLUMNS)
        contract_col = "contract" if "contract" in column_types else None
        parse_input_col = "parse_input" if "parse_input" in column_types else None
        method_col = "method_id" if "method_id" in column_types else None

        if user_col is None:
            raise RuntimeError("justlend.justlend_history missing user address column")
        if method_col is None:
            raise RuntimeError("justlend.justlend_history missing method_id column")
        if contract_col is None and parse_input_col is None:
            raise RuntimeError(
                "justlend.justlend_history missing both contract and parse_input columns"
            )

        bind_values: list[Any] = []
        where_clauses: list[str] = []

        if only_success and status_col is not None:
            bind_values.append(1)
            where_clauses.append(f"{status_col} = ${len(bind_values)}")

        bind_values.append(list(JUSTLEND_REPLAY_METHOD_IDS))
        where_clauses.append(f"{method_col} = ANY(${len(bind_values)}::text[])")

        if contract_type_col is not None:
            bind_values.append(31)
            where_clauses.append(f"{contract_type_col} = ${len(bind_values)}")

        effective_start_time = _coerce_utc_datetime(start_time)
        effective_end_time = _coerce_utc_datetime(end_time)
        if effective_start_time is not None:
            if time_col is None:
                raise RuntimeError(
                    "justlend.justlend_history missing time column required by --start"
                )
            bind_values.append(effective_start_time)
            where_clauses.append(f"{time_col} >= ${len(bind_values)}::timestamptz")
        if effective_end_time is not None:
            if time_col is None:
                raise RuntimeError(
                    "justlend.justlend_history missing time column required by --end"
                )
            bind_values.append(effective_end_time)
            where_clauses.append(f"{time_col} <= ${len(bind_values)}::timestamptz")

        sql = f"""
            SELECT
                {user_col} AS user_address,
                {contract_col if contract_col is not None else "NULL"} AS contract,
                {parse_input_col if parse_input_col is not None else "NULL"} AS parse_input
            FROM justlend.justlend_history
            WHERE {" AND ".join(where_clauses)}
              AND {user_col} IS NOT NULL
        """

        matched_by_user: OrderedDict[bytes, set[str]] = OrderedDict()
        async with conn.transaction():
            async for row in conn.cursor(sql, *bind_values, prefetch=2000):
                user_address = row["user_address"]
                if user_address is None:
                    continue
                user_key = bytes(user_address)
                if user_key not in matched_by_user:
                    matched_by_user[user_key] = set()
                for candidate in (
                    _extract_market_address_from_contract(row["contract"]),
                    _extract_market_address_from_parse_input(row["parse_input"]),
                ):
                    if candidate is None:
                        continue
                    symbol = address_to_symbol.get(candidate)
                    if symbol is not None:
                        matched_by_user[user_key].add(symbol)

    if match_mode == "all":
        return [
            user_address
            for user_address, symbols in matched_by_user.items()
            if target_symbols.issubset(symbols)
        ]
    return [
        user_address for user_address, symbols in matched_by_user.items() if symbols
    ]


async def _resolve_history_target_users(
    pool: asyncpg.Pool,
    *,
    target_symbols: set[str],
    match_mode: str,
    start_time: datetime | None,
    end_time: datetime | None,
    only_success: bool,
) -> tuple[list[bytes], list[str], list[str]]:
    market_rows = await fetch_justlend_markets_current(pool)
    if not market_rows:
        raise RuntimeError(
            "loan.justlend_markets_current is empty; cannot map TRX/USDT history rows to JustLend markets"
        )

    address_to_symbol = build_target_address_symbol_map(
        market_rows, target_symbols=target_symbols
    )
    missing_symbols = sorted(
        symbol
        for symbol in target_symbols
        if symbol not in set(address_to_symbol.values())
    )
    if missing_symbols:
        missing_text = ", ".join(missing_symbols)
        raise RuntimeError(
            "loan.justlend_markets_current missing target underlying_symbol rows: "
            f"{missing_text}"
        )

    all_market_addresses = [
        normalized
        for normalized in (
            _normalize_tron_address(row["market_address"]) for row in market_rows
        )
        if normalized is not None
    ]
    deduped_markets = list(dict.fromkeys(all_market_addresses))
    user_rows = await _scan_history_rows_for_target_users(
        pool,
        address_to_symbol=address_to_symbol,
        target_symbols=target_symbols,
        match_mode=match_mode,
        start_time=start_time,
        end_time=end_time,
        only_success=only_success,
    )
    return user_rows, deduped_markets, sorted(target_symbols)


async def backfill_current_positions_from_history(
    pool: asyncpg.Pool,
    *,
    cfg: AppConfig,
    tron_rpc: TronRpcClient,
    target_symbols: Iterable[str],
    match_mode: str = "all",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    addresses: Iterable[str] | None = None,
    limit: int = 0,
    dry_run: bool = False,
    only_success: bool = True,
    delete_closed: bool = True,
    market_addresses: Iterable[str] | None = None,
    user_source: str = "history",
) -> CurrentPositionBackfillStats:
    if tron_rpc is None:
        raise RuntimeError("TRON RPC client is required")

    normalized_symbols = {
        symbol.strip().upper() for symbol in target_symbols if symbol.strip()
    }
    if not normalized_symbols:
        raise ValueError("target_symbols cannot be empty")
    normalized_match_mode = match_mode.strip().lower()
    if normalized_match_mode not in _MATCH_MODES:
        raise ValueError(f"unsupported match_mode: {match_mode}")
    normalized_user_source = user_source.strip().lower()
    if normalized_user_source not in _USER_SOURCES:
        raise ValueError(f"unsupported user_source: {user_source}")

    await ensure_justlend_tables(pool)

    all_users: list[bytes]
    rpc_market_addresses: list[str]
    resolved_symbols: list[str]
    if addresses:
        all_users = [
            _tron_address_to_bytes(address.strip())
            for address in addresses
            if address.strip()
        ]
        resolved_symbols = sorted(normalized_symbols)
        if market_addresses:
            rpc_market_addresses = [
                normalized
                for normalized in (
                    _normalize_tron_address(item) for item in market_addresses
                )
                if normalized is not None
            ]
        else:
            market_rows = await fetch_justlend_markets_current(pool)
            rpc_market_addresses = [
                normalized
                for normalized in (
                    _normalize_tron_address(row["market_address"])
                    for row in market_rows
                )
                if normalized is not None
            ]
    else:
        inferred_rpc_market_addresses: list[str] = []
        resolved_symbols = sorted(normalized_symbols)
        history_users: list[bytes] = []
        if normalized_user_source in {"history", "union"}:
            (
                history_users,
                inferred_rpc_market_addresses,
                resolved_symbols,
            ) = await _resolve_history_target_users(
                pool,
                target_symbols=normalized_symbols,
                match_mode=normalized_match_mode,
                start_time=start_time,
                end_time=end_time,
                only_success=only_success,
            )
        current_users: list[bytes] = []
        if normalized_user_source in {"current", "union"}:
            current_users = await fetch_all_current_user_addresses(pool)
        all_users = merge_user_addresses(history_users, current_users)
        rpc_market_addresses = (
            [
                normalized
                for normalized in (
                    _normalize_tron_address(item) for item in market_addresses
                )
                if normalized is not None
            ]
            if market_addresses
            else inferred_rpc_market_addresses
        )
        if not rpc_market_addresses and normalized_user_source in {"current", "union"}:
            market_rows = await fetch_justlend_markets_current(pool)
            rpc_market_addresses = [
                normalized
                for normalized in (
                    _normalize_tron_address(row["market_address"])
                    for row in market_rows
                )
                if normalized is not None
            ]

    normalized_users, aliases_by_user = normalize_user_addresses(all_users)
    selected_users = normalized_users[:limit] if limit > 0 else normalized_users
    deduped_rpc_markets = list(dict.fromkeys(rpc_market_addresses))
    if not deduped_rpc_markets:
        config_markets = [
            normalized
            for normalized in (
                _normalize_tron_address(item) for item in cfg.justlend.markets
            )
            if normalized is not None
        ]
        deduped_rpc_markets = list(dict.fromkeys(config_markets))
    if not deduped_rpc_markets:
        raise RuntimeError(
            "no JustLend markets available for RPC position fetch; populate loan.justlend_markets_current or config.justlend.markets"
        )

    stats = CurrentPositionBackfillStats(selected_users=len(selected_users))
    for user_address in selected_users:
        user_address_b58 = _tron_bytes_to_base58(user_address)
        legacy_aliases = aliases_by_user.get(user_address, [])
        try:
            payload = await fetch_justlend_position_via_rpc(
                tron_rpc,
                address=user_address_b58,
                protocol="trx",
                market_addresses=deduped_rpc_markets,
            )
        except HTTPException as exc:
            if exc.status_code == 404:
                if delete_closed:
                    if not dry_run:
                        for legacy_user_address in legacy_aliases:
                            await delete_current_user_position(
                                pool, user_address=legacy_user_address
                            )
                        await delete_current_user_position(
                            pool, user_address=user_address
                        )
                    stats.deleted_users += 1
                    _record_deleted_address(stats, user_address=user_address_b58)
                else:
                    stats.skipped_users += 1
                continue
            stats.failed_users += 1
            reason = f"HTTP {exc.status_code}: {exc.detail}"
            _record_failed_reason(
                stats,
                user_address=user_address_b58,
                reason=reason,
            )
            logger.warning(
                "JustLend current position backfill failed: user=%s reason=%s",
                user_address_b58,
                reason,
            )
            continue
        except Exception as exc:
            stats.failed_users += 1
            reason = f"{type(exc).__name__}: {exc}"
            _record_failed_reason(
                stats,
                user_address=user_address_b58,
                reason=reason,
            )
            logger.exception(
                "JustLend current position backfill failed: user=%s",
                user_address_b58,
            )
            continue

        if dry_run:
            stats.updated_users += 1
            continue

        for legacy_user_address in legacy_aliases:
            await delete_current_user_position(pool, user_address=legacy_user_address)
        extra_jsonb = dict(payload["extra_jsonb"])
        extra_jsonb["history_target_symbols"] = resolved_symbols
        extra_jsonb["history_match_mode"] = normalized_match_mode
        extra_jsonb["backfill_user_source"] = normalized_user_source
        await upsert_current_user_position(
            pool,
            user_address=payload["user_address"],
            chain=payload["chain"],
            protocol=payload["protocol"],
            snapshot_at=payload["snapshot_at"],
            block_timestamp=payload["block_timestamp"],
            block_number=payload["block_number"],
            source_cursor=payload["source_cursor"],
            total_deposit_usd=payload["total_deposit_usd"],
            total_collateral_usd=payload["total_collateral_usd"],
            total_debt_usd=payload["total_debt_usd"],
            available_borrow_usd=payload["available_borrow_usd"],
            health_factor=payload["health_factor"],
            ltv=payload["ltv"],
            liquidation_threshold=payload["liquidation_threshold"],
            extra_jsonb=extra_jsonb,
            assets=payload["assets"],
        )
        stats.updated_users += 1

    return stats
