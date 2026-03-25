"""Backfill Compound event-driven position snapshots for one user address."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from crawler_shared.logging import setup_cli_logging

from compound_crawler.config import load_config
from compound_crawler.constants import (
    COMPOUND_V2_MARKET_NAMES,
    COMPOUND_V3_MARKET_NAMES,
)
from compound_crawler.crawler import _build_web3, close_web3
from compound_crawler.db import (
    CompoundEventPositionSnapshotRow,
    create_pool,
    ensure_compound_event_snapshot_table,
    fetch_compound_cached_event_keys,
    fetch_compound_user_tx_history,
    upsert_compound_event_snapshots,
)
from compound_crawler.user_position_snapshots import (
    _collect_user_snapshots_batch,
    _load_market_context,
    _parse_utc_time,
)

logger = logging.getLogger(__name__)

DEFAULT_START = "2020-01-01"
POSITION_METHOD_IDS: dict[str, set[str]] = {
    "v2": {
        "2608f818",  # mint
        "0e752702",  # redeemUnderlying
        "852a12e3",  # redeem
        "a0712d68",  # borrow
        "db006a75",  # repayBorrow
        "f5e3c462",  # repayBorrowBehalf
        "c5ebeaec",  # liquidateBorrow
    },
    "v3": {
        "f3fef3a3",  # supply
        "c3b35a7e",  # supplyTo
        "f2b9fdb8",  # withdraw
        "4232cd63",  # buyCollateral
        "c3cecfd2",  # absorb
    },
}
METHOD_BRIEF_MAP: dict[str, dict[str, str]] = {
    "v2": {
        "2608f818": "存入",
        "0e752702": "赎回",
        "852a12e3": "赎回",
        "a0712d68": "借入",
        "db006a75": "还款",
        "f5e3c462": "代还",
        "c5ebeaec": "清算",
    },
    "v3": {
        "f3fef3a3": "存入",
        "c3b35a7e": "代存",
        "f2b9fdb8": "提取",
        "4232cd63": "买入抵押品",
        "c3cecfd2": "吸收清算",
    },
}


@dataclass
class UserTxEvent:
    tx_hash: str
    block_number: int
    block_timestamp: datetime
    market: str
    method_id: str | None


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_address_bytes(user_address: str) -> bytes:
    value = user_address.strip().lower()
    if not value.startswith("0x") or len(value) != 42:
        raise ValueError(f"invalid address: {user_address}")
    return bytes.fromhex(value[2:])


def _normalize_hex_address(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("0x") and len(text) == 42:
            return text.lower()
        return None
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)) and len(value) == 20:
        return "0x" + bytes(value).hex()
    return None


def _normalize_tx_hash(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return None
        return text if text.startswith("0x") else f"0x{text}"
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if not raw:
            return None
        return "0x" + raw.hex()
    return None


def _normalize_method_id(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return None
        if text.startswith("0x"):
            text = text[2:]
        return text if len(text) == 8 else None
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if not raw:
            return None
        return raw.hex()[:8].lower()
    return None


def _is_position_method(protocol: str, method_id: str | None) -> bool:
    if method_id is None:
        return False
    return method_id in POSITION_METHOD_IDS.get(protocol, set())


def _market_symbol(protocol: str, market: bytes) -> str:
    address = "0x" + market.hex()
    if protocol == "v2":
        return COMPOUND_V2_MARKET_NAMES.get(address, address)
    return COMPOUND_V3_MARKET_NAMES.get(address, address)


def _fmt_amount(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def _chunked[T](items: list[T], size: int) -> list[list[T]]:
    if size <= 0:
        raise ValueError("chunk size must be > 0")
    return [items[i : i + size] for i in range(0, len(items), size)]


def _resolve_v3_market_filter(market: str) -> str | None:
    value = market.strip().lower()
    if value == "all":
        return None
    if value.startswith("0x") and len(value) == 42:
        return value
    for addr, symbol in COMPOUND_V3_MARKET_NAMES.items():
        if symbol.lower() == value:
            return addr
    raise ValueError(f"unknown v3 market: {market}")


def _row_to_event(
    row: Any,
    *,
    protocol: str,
    market_filter: str | None,
    only_position_ops: bool,
) -> UserTxEvent | None:
    market = _normalize_hex_address(row.get("market"))
    if market is None:
        return None
    if market_filter is not None and market != market_filter:
        return None

    tx_hash = _normalize_tx_hash(row.get("tx_hash"))
    if tx_hash is None:
        return None
    method_id = _normalize_method_id(row.get("method_id"))
    if only_position_ops and not _is_position_method(protocol, method_id):
        return None

    block_number = int(row["block_number"])
    block_timestamp = _to_utc(row["block_timestamp"])
    return UserTxEvent(
        tx_hash=tx_hash,
        block_number=block_number,
        block_timestamp=block_timestamp,
        market=market,
        method_id=method_id,
    )


def _snapshot_to_event_row(
    snapshot: Any,
    *,
    protocol: str,
    tx_hash: str,
    block_timestamp: datetime,
    brief: str,
) -> CompoundEventPositionSnapshotRow:
    return CompoundEventPositionSnapshotRow(
        user_address=snapshot.user_address,
        protocol=protocol,
        market=snapshot.market,
        symbol=snapshot.symbol,
        block_number=snapshot.block_number,
        tx_hash=tx_hash,
        block_timestamp=block_timestamp,
        has_open_position=snapshot.has_open_position,
        is_liquidatable=snapshot.is_liquidatable,
        base_token=snapshot.base_token,
        base_symbol=snapshot.base_symbol,
        base_price_usd=snapshot.base_price_usd,
        eth_price_usd=snapshot.eth_price_usd,
        total_collateral_usd=snapshot.total_collateral_usd,
        total_debt_usd=snapshot.total_debt_usd,
        discounted_collateral_usd=snapshot.discounted_collateral_usd,
        liquidation_buffer_usd=snapshot.liquidation_buffer_usd,
        health_factor=snapshot.health_factor,
        eth_sensitive_collateral_usd=snapshot.eth_sensitive_collateral_usd,
        eth_sensitive_debt_usd=snapshot.eth_sensitive_debt_usd,
        net_eth_exposure_usd=snapshot.net_eth_exposure_usd,
        non_eth_collateral_usd=snapshot.non_eth_collateral_usd,
        non_eth_debt_usd=snapshot.non_eth_debt_usd,
        basis_risk_collateral_usd=snapshot.basis_risk_collateral_usd,
        eth_down_liq_price_usd=snapshot.eth_down_liq_price_usd,
        eth_up_liq_price_usd=snapshot.eth_up_liq_price_usd,
        eth_liq_mode=snapshot.eth_liq_mode,
        dominant_risk=snapshot.dominant_risk,
        assets_jsonb=snapshot.assets_jsonb,
        brief=brief,
    )


async def _load_briefs_from_detail_tables(
    pool: Any,
    *,
    protocol: str,
    user_address: bytes,
    tx_hashes: list[bytes],
) -> dict[str, str]:
    if not tx_hashes:
        return {}
    version_int = 3 if protocol == "v3" else 2
    brief_map: dict[str, str] = {}
    async with pool.acquire() as conn:
        mint_rows = await conn.fetch(
            """
            SELECT tx_hash, market_address, underlying_amount_decimal, input_amount_decimal
            FROM compound.compound_mint
            WHERE version = $1
              AND tx_hash = ANY($2::bytea[])
              AND minter = $3
            """,
            version_int,
            tx_hashes,
            user_address,
        )
        for row in mint_rows:
            txh = "0x" + bytes(row["tx_hash"]).hex()
            symbol = _market_symbol(protocol, bytes(row["market_address"]))
            amount = row["underlying_amount_decimal"] or row["input_amount_decimal"]
            brief_map[txh] = f"存入 {_fmt_amount(amount)} {symbol}"

        redeem_rows = await conn.fetch(
            """
            SELECT tx_hash, market_address, underlying_amount_decimal, input_amount_decimal
            FROM compound.compound_redeem
            WHERE version = $1
              AND tx_hash = ANY($2::bytea[])
              AND redeemer = $3
            """,
            version_int,
            tx_hashes,
            user_address,
        )
        for row in redeem_rows:
            txh = "0x" + bytes(row["tx_hash"]).hex()
            symbol = _market_symbol(protocol, bytes(row["market_address"]))
            amount = row["underlying_amount_decimal"] or row["input_amount_decimal"]
            brief_map[txh] = f"提取 {_fmt_amount(amount)} {symbol}"

        borrow_rows = await conn.fetch(
            """
            SELECT tx_hash, market_address, underlying_amount_decimal, input_amount_decimal
            FROM compound.compound_borrow
            WHERE version = $1
              AND tx_hash = ANY($2::bytea[])
              AND borrower = $3
            """,
            version_int,
            tx_hashes,
            user_address,
        )
        for row in borrow_rows:
            txh = "0x" + bytes(row["tx_hash"]).hex()
            symbol = _market_symbol(protocol, bytes(row["market_address"]))
            amount = row["underlying_amount_decimal"] or row["input_amount_decimal"]
            brief_map[txh] = f"借入 {_fmt_amount(amount)} {symbol}"

        repay_rows = await conn.fetch(
            """
            SELECT tx_hash, market_address, underlying_amount_decimal, input_amount_decimal
            FROM compound.compound_repay
            WHERE version = $1
              AND tx_hash = ANY($2::bytea[])
              AND (payer = $3 OR borrower = $3)
            """,
            version_int,
            tx_hashes,
            user_address,
        )
        for row in repay_rows:
            txh = "0x" + bytes(row["tx_hash"]).hex()
            symbol = _market_symbol(protocol, bytes(row["market_address"]))
            amount = row["underlying_amount_decimal"] or row["input_amount_decimal"]
            brief_map[txh] = f"还款 {_fmt_amount(amount)} {symbol}"

        liq_rows = await conn.fetch(
            """
            SELECT tx_hash, market_address, borrower, liquidator
            FROM compound.compound_liquidate
            WHERE version = $1
              AND tx_hash = ANY($2::bytea[])
              AND (borrower = $3 OR liquidator = $3)
            """,
            version_int,
            tx_hashes,
            user_address,
        )
        for row in liq_rows:
            txh = "0x" + bytes(row["tx_hash"]).hex()
            symbol = _market_symbol(protocol, bytes(row["market_address"]))
            role = "被清算" if bytes(row["borrower"]) == user_address else "执行清算"
            brief_map[txh] = f"{role} {symbol}"
    return brief_map


def _fallback_brief(event: UserTxEvent, protocol: str, market: bytes) -> str:
    action = METHOD_BRIEF_MAP.get(protocol, {}).get(event.method_id or "", "仓位操作")
    return f"{action} {_market_symbol(protocol, market)}"


async def _collect_event_rows_for_user(
    *,
    address: bytes,
    protocol: str,
    market_filter: str | None,
    from_dt: datetime,
    to_dt: datetime,
    dry_run: bool,
    write_batch_size: int,
    config_path: str | None,
    only_position_ops: bool,
    rpc_concurrency: int,
) -> None:
    cfg = load_config(config_path)
    cfg.protocol = protocol

    pool = await create_pool(cfg.postgres)
    w3 = None
    try:
        await ensure_compound_event_snapshot_table(pool)
        tx_rows = await fetch_compound_user_tx_history(
            pool,
            user_address=address,
            protocol=protocol,
            from_dt=from_dt,
            to_dt=to_dt,
            market=(bytes.fromhex(market_filter[2:]) if market_filter else None),
            user_column="from_address",
        )
        events = [
            event
            for row in tx_rows
            if (
                event := _row_to_event(
                    row,
                    protocol=protocol,
                    market_filter=market_filter,
                    only_position_ops=only_position_ops,
                )
            )
            is not None
        ]
        if not events:
            other_protocol = "v2" if protocol == "v3" else "v3"
            other_rows = await fetch_compound_user_tx_history(
                pool,
                user_address=address,
                protocol=other_protocol,
                from_dt=from_dt,
                to_dt=to_dt,
                market=None,
            )
            logger.info(
                "No tx events found for protocol=%s in selected range. address=0x%s",
                protocol,
                address.hex(),
            )
            logger.info(
                "Address tx count hint: protocol=%s count=%s, protocol=%s count=%s",
                protocol,
                len(tx_rows),
                other_protocol,
                len(other_rows),
            )
            return

        grouped: dict[tuple[str, int], list[UserTxEvent]] = defaultdict(list)
        for event in events:
            grouped[(event.market, event.block_number)].append(event)

        cached_keys = await fetch_compound_cached_event_keys(
            pool,
            user_address=address,
            protocol=protocol,
            from_dt=from_dt,
            to_dt=to_dt,
            market=(bytes.fromhex(market_filter[2:]) if market_filter else None),
        )
        if cached_keys:
            before = len(events)
            events = [
                event
                for event in events
                if (
                    bytes.fromhex(event.market[2:]),
                    event.tx_hash.lower(),
                )
                not in cached_keys
            ]
            if len(events) != before:
                logger.info(
                    "Skip cached tx rows: skipped=%s remaining=%s",
                    before - len(events),
                    len(events),
                )
            if not events:
                logger.info("All tx rows already cached, nothing to do.")
                return

        grouped = defaultdict(list)
        for event in events:
            grouped[(event.market, event.block_number)].append(event)

        logger.info(
            "Loaded tx events: total=%s grouped_points=%s",
            len(events),
            len(grouped),
        )

        tx_hash_bytes = [bytes.fromhex(event.tx_hash[2:]) for event in events]
        brief_map = await _load_briefs_from_detail_tables(
            pool,
            protocol=protocol,
            user_address=address,
            tx_hashes=tx_hash_bytes,
        )

        w3 = await _build_web3(cfg)
        metadata_cache: dict[str, tuple[str | None, int | None]] = {}
        pending_rows: list[CompoundEventPositionSnapshotRow] = []
        processed_points = 0
        inserted = 0
        user_addresses = [address]
        if protocol != "v3":
            raise NotImplementedError(
                "Event snapshot backfill currently supports only Compound v3."
            )

        point_items = sorted(grouped.items())
        sem = asyncio.Semaphore(max(1, rpc_concurrency))

        async def _process_point(
            point_item: tuple[tuple[str, int], list[UserTxEvent]],
        ) -> list[CompoundEventPositionSnapshotRow]:
            (market, block_number), event_group = point_item
            async with sem:
                market_ctx = await _load_market_context(
                    w3,
                    market_address=market,
                    block_number=block_number,
                    metadata_cache=metadata_cache,
                )
                batch_rows = await _collect_user_snapshots_batch(
                    w3,
                    market_ctx,
                    user_addresses=user_addresses,
                    point_ts=event_group[0].block_timestamp,
                    block_number=block_number,
                )
            if not batch_rows:
                return []

            snapshot_row, _ = batch_rows[0]
            return [
                _snapshot_to_event_row(
                    snapshot_row,
                    protocol=protocol,
                    tx_hash=event.tx_hash,
                    block_timestamp=event.block_timestamp,
                    brief=brief_map.get(
                        event.tx_hash,
                        _fallback_brief(event, protocol, snapshot_row.market),
                    ),
                )
                for event in event_group
            ]

        submit_batch_size = max(rpc_concurrency * 4, rpc_concurrency)
        for point_batch in _chunked(point_items, submit_batch_size):
            tasks = [asyncio.create_task(_process_point(item)) for item in point_batch]
            for task in asyncio.as_completed(tasks):
                rows = await task
                processed_points += 1
                if not rows:
                    continue
                pending_rows.extend(rows)
                if len(pending_rows) >= write_batch_size:
                    if dry_run:
                        logger.info("dry-run flush rows=%s", len(pending_rows))
                    else:
                        inserted += await upsert_compound_event_snapshots(
                            pool, pending_rows
                        )
                    pending_rows = []

        if pending_rows:
            if dry_run:
                logger.info("dry-run final flush rows=%s", len(pending_rows))
            else:
                inserted += await upsert_compound_event_snapshots(pool, pending_rows)

        if dry_run:
            logger.info(
                "Done (dry-run): grouped_points=%s event_rows=%s",
                processed_points,
                len(events),
            )
        else:
            logger.info(
                "Done: grouped_points=%s inserted_rows=%s",
                processed_points,
                inserted,
            )
    finally:
        await close_web3(w3)
        await pool.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", required=True, help="user address (0x...)")
    parser.add_argument(
        "--protocol",
        default="v3",
        choices=["v2", "v3"],
        help="compound protocol version",
    )
    parser.add_argument(
        "--market",
        default="all",
        help="v3 market symbol/address (e.g. WETH, USDC, 0x...), or all",
    )
    parser.add_argument(
        "--start", default=DEFAULT_START, help="UTC start datetime/date"
    )
    parser.add_argument("--end", default=None, help="UTC end datetime/date")
    parser.add_argument("--config", default=None, help="config.yaml path")
    parser.add_argument(
        "--write-batch-size",
        type=int,
        default=500,
        help="upsert batch size",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="collect only, do not write",
    )
    parser.add_argument(
        "--include-non-position",
        action="store_true",
        default=False,
        help="include non position-impacting methods",
    )
    parser.add_argument(
        "--rpc-concurrency",
        type=int,
        default=8,
        help="max concurrent RPC point collection workers",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="enable DEBUG logging",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    setup_cli_logging(args.verbose)

    address = _parse_address_bytes(args.address)
    start = _parse_utc_time(args.start)
    end = _parse_utc_time(args.end) if args.end else datetime.now(timezone.utc)
    if start > end:
        raise SystemExit("--start must be <= --end")
    if args.write_batch_size <= 0:
        raise SystemExit("--write-batch-size must be > 0")
    if args.rpc_concurrency <= 0:
        raise SystemExit("--rpc-concurrency must be > 0")

    market_filter = None
    if args.protocol == "v3":
        market_filter = _resolve_v3_market_filter(args.market)
    elif args.market.strip().lower() != "all":
        raise SystemExit("v2 currently supports only --market all")

    asyncio.run(
        _collect_event_rows_for_user(
            address=address,
            protocol=args.protocol,
            market_filter=market_filter,
            from_dt=start,
            to_dt=end,
            dry_run=args.dry_run,
            write_batch_size=args.write_batch_size,
            config_path=args.config,
            only_position_ops=not args.include_non_position,
            rpc_concurrency=args.rpc_concurrency,
        )
    )


if __name__ == "__main__":
    main()
