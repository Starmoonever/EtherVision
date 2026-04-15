"""Preview how JustLend replay briefs would change under a new wording strategy.

Examples:
    uv run python scripts/justlend/preview_brief_strategy.py --limit 20
    uv run python scripts/justlend/preview_brief_strategy.py --address TJu9TNd41Z79ZdDriqSLcTavfqA8NqNc33 --start 2026-03-01 --end 2026-03-31
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(os.path.abspath(str(ROOT)))

from crawler_shared.logging import setup_cli_logging  # noqa: E402
from crawler_shared.tron_rpc import build_tron_rpc_client  # noqa: E402
from justlend_crawler.api import service  # noqa: E402
from justlend_crawler.config import load_config  # noqa: E402
from justlend_crawler.db import (  # noqa: E402
    create_pool,
    fetch_justlend_tx_effects,
)

_VALUE_TOLERANCE_USD = Decimal("0.01")


def _parse_utc_time(value: str) -> datetime:
    formats = (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise SystemExit(f"unsupported UTC time format: {value}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="预览 JustLend brief 新策略对现有缓存记录的影响"
    )
    parser.add_argument("--config", default=None, help="config.yaml path")
    parser.add_argument(
        "--address",
        action="append",
        dest="addresses",
        default=None,
        help="target TRON address, repeatable",
    )
    parser.add_argument("--start", default=None, help="UTC start time")
    parser.add_argument("--end", default=None, help="UTC end time")
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="max snapshot rows to preview",
    )
    parser.add_argument(
        "--only-changed",
        action="store_true",
        default=False,
        help="only print rows whose proposed brief differs from current brief",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="enable DEBUG logging",
    )
    return parser


def _format_amount(amount: Decimal) -> str:
    text = format(amount.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _format_usd(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _normalize_symbol(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text or None


def _extract_matching_asset_value_usd(
    row: Any, symbol: str | None, side: str
) -> Decimal:
    if not symbol:
        return Decimal("0")
    total = Decimal("0")
    for item in service._normalize_asset_items(row["assets_jsonb"]):
        if str(item.get("side") or "") != side:
            continue
        if _normalize_symbol(item.get("symbol")) != symbol:
            continue
        total += _decimal(item.get("value_usd"))
    return total


def _infer_supply_side_label(
    *,
    operation_type: str | None,
    current_row: Any,
    previous_row: Any | None,
    symbol: str | None,
) -> tuple[str | None, str | None]:
    if operation_type not in {"deposit", "redeem", "withdraw"}:
        return None, None

    current_discounted = _decimal(current_row.get("discounted_collateral_usd"))
    previous_discounted = (
        _decimal(previous_row.get("discounted_collateral_usd"))
        if previous_row is not None
        else Decimal("0")
    )
    discounted_delta = current_discounted - previous_discounted

    current_asset_value = _extract_matching_asset_value_usd(
        current_row, symbol, "collateral"
    )
    previous_asset_value = (
        _extract_matching_asset_value_usd(previous_row, symbol, "collateral")
        if previous_row is not None
        else Decimal("0")
    )
    asset_delta = current_asset_value - previous_asset_value

    if operation_type == "deposit":
        if (
            discounted_delta > _VALUE_TOLERANCE_USD
            and asset_delta > _VALUE_TOLERANCE_USD
        ):
            return "新增抵押", (
                f"collateral+${_format_usd(asset_delta)}, "
                f"discounted+${_format_usd(discounted_delta)}"
            )
        return "供给", (
            f"collateral+${_format_usd(asset_delta)}, "
            f"discounted+${_format_usd(discounted_delta)}"
        )

    if operation_type in {"redeem", "withdraw"}:
        if (
            discounted_delta < -_VALUE_TOLERANCE_USD
            and asset_delta < -_VALUE_TOLERANCE_USD
        ):
            return "移除抵押", (
                f"collateral-${_format_usd(abs(asset_delta))}, "
                f"discounted-${_format_usd(abs(discounted_delta))}"
            )
        return "提取供给", (
            f"collateral-${_format_usd(abs(asset_delta))}, "
            f"discounted-${_format_usd(abs(discounted_delta))}"
        )

    return None, None


def _build_proposed_brief(
    *,
    operation_type: str | None,
    amount: Decimal,
    symbol: str | None,
    price_usd: Decimal | None,
    fallback: str,
    effect: dict[str, Any] | None,
    user_address: bytes | None,
    current_row: Any,
    previous_row: Any | None,
) -> str:
    normalized_op = (operation_type or "").lower() or None
    label = None
    if normalized_op in {"deposit", "redeem", "withdraw"}:
        label, _ = _infer_supply_side_label(
            operation_type=normalized_op,
            current_row=current_row,
            previous_row=previous_row,
            symbol=symbol,
        )
    if not label:
        label = service._resolve_brief_action_label(
            operation_type=normalized_op,
            effect=effect,
            user_address=user_address,
        )
    if label and amount > 0 and symbol:
        base = f"{label} {_format_amount(amount)} {symbol}"
        if price_usd is not None and price_usd > 0:
            return f"{base} (价值 {_format_usd(amount * price_usd)} usd)"
        return base
    return fallback


async def _fetch_snapshot_rows(
    pool,
    *,
    addresses: list[str] | None,
    start: datetime | None,
    end: datetime | None,
    limit: int,
) -> list[Any]:
    bind_values: list[Any] = []
    where_clauses: list[str] = []

    if addresses:
        address_bytes = [
            service._tron_address_to_bytes(addr.strip())
            for addr in addresses
            if addr.strip()
        ]
        address_text_bytes = [
            normalized.encode("utf-8")
            for addr in addresses
            if (normalized := service._normalize_tron_address(addr)) is not None
        ]
        bind_values.append(address_bytes + address_text_bytes)
        where_clauses.append(f"user_address = ANY(${len(bind_values)}::bytea[])")

    if start is not None:
        bind_values.append(start)
        where_clauses.append(f"block_timestamp >= ${len(bind_values)}::timestamptz")
    if end is not None:
        bind_values.append(end)
        where_clauses.append(f"block_timestamp <= ${len(bind_values)}::timestamptz")

    sql = """
        SELECT
            id,
            user_address,
            tx_hash,
            block_timestamp,
            symbol,
            method_id,
            operation_type,
            brief,
            assets_jsonb
        FROM loan.justlend_position_snapshots
    """
    if where_clauses:
        sql += "\nWHERE " + " AND ".join(where_clauses)
    sql += "\nORDER BY block_timestamp DESC, id DESC"
    if limit > 0:
        bind_values.append(limit)
        sql += f"\nLIMIT ${len(bind_values)}"

    async with pool.acquire() as conn:
        return await conn.fetch(sql, *bind_values)


def _infer_price_usd_from_assets(row: Any, symbol: str | None) -> Decimal | None:
    if not symbol:
        return None
    for item in service._normalize_asset_items(row["assets_jsonb"]):
        if str(item.get("symbol") or "").upper() != symbol.upper():
            continue
        try:
            return Decimal(str(item.get("price_usd") or "0"))
        except Exception:
            return None
    return None


async def run(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    setup_cli_logging(args.verbose)
    pool = await create_pool(cfg.postgres)
    tron_rpc = build_tron_rpc_client(
        cfg.tron_rpc_url, timeout=float(cfg.crawler.rpc_timeout)
    )

    try:
        start = _parse_utc_time(args.start) if args.start else None
        end = _parse_utc_time(args.end) if args.end else None
        rows = await _fetch_snapshot_rows(
            pool,
            addresses=args.addresses,
            start=start,
            end=end,
            limit=args.limit,
        )
        if not rows:
            print("no snapshot rows found")
            return

        effects = await fetch_justlend_tx_effects(
            pool,
            tx_hashes=[str(row["tx_hash"]) for row in rows],
        )
        market_addresses: set[str] = set()
        for effect in effects.values():
            for key in ("market_address", "underlying_address"):
                normalized = service._normalize_tron_address(effect.get(key))
                if normalized:
                    market_addresses.add(normalized)
        market_catalog = await service._fetch_justlend_market_catalog(
            cfg,
            tron_rpc=tron_rpc,
            market_addresses=sorted(market_addresses),
        )

        rows_in_eval_order = sorted(
            rows,
            key=lambda row: (
                row["block_timestamp"],
                int(row["id"]),
            ),
        )
        changed = 0
        unchanged = 0
        label_counter: Counter[str] = Counter()
        preview_rows: list[tuple[Any, str, str, str | None, str | None]] = []
        previous_row_by_address: dict[str, Any] = {}

        for row in rows_in_eval_order:
            tx_hash = str(row["tx_hash"])
            old_brief = str(row["brief"] or "")
            effect = effects.get(tx_hash, {})
            operation_type = (
                str(effect.get("operation_type") or "")
                or str(row["operation_type"] or "")
                or service._method_to_operation_type(row["method_id"])
            )
            symbol = str(row["symbol"] or "").strip() or None
            price_usd = _infer_price_usd_from_assets(row, symbol)

            amount = Decimal("0")
            if effect:
                amount = Decimal(str(effect.get("amount_decimal") or "0"))
                if not symbol:
                    for key in ("underlying_address", "market_address"):
                        normalized = service._normalize_tron_address(effect.get(key))
                        if not normalized:
                            continue
                        try:
                            market_hex = service._tron_address_to_bytes(
                                normalized
                            ).hex()
                        except Exception:
                            continue
                        meta = market_catalog.get(market_hex)
                        if isinstance(meta, dict):
                            symbol = (
                                str(meta.get("underlying_symbol") or "").strip() or None
                            )
                            if price_usd is None:
                                raw_price = meta.get("price_usd")
                                if raw_price is not None:
                                    price_usd = Decimal(str(raw_price))
                            if symbol:
                                break

            address_str = service._normalize_tron_address(row["user_address"]) or ""
            previous_row = previous_row_by_address.get(address_str)
            new_brief = _build_proposed_brief(
                operation_type=operation_type,
                amount=amount,
                symbol=symbol,
                price_usd=price_usd,
                fallback=old_brief,
                effect=effect if effect else None,
                user_address=bytes(row["user_address"])
                if row["user_address"] is not None
                else None,
                current_row=row,
                previous_row=previous_row,
            )
            heuristic_label, heuristic_reason = _infer_supply_side_label(
                operation_type=(operation_type or "").lower() or None,
                current_row=row,
                previous_row=previous_row,
                symbol=symbol,
            )
            is_changed = new_brief != old_brief
            if is_changed:
                changed += 1
            else:
                unchanged += 1
            label_counter[heuristic_label or operation_type or "unknown"] += 1
            preview_rows.append(
                (
                    row,
                    old_brief,
                    new_brief,
                    heuristic_label,
                    heuristic_reason,
                )
            )
            previous_row_by_address[address_str] = row

        for row, old_brief, new_brief, heuristic_label, heuristic_reason in reversed(
            preview_rows
        ):
            is_changed = new_brief != old_brief
            if args.only_changed and not is_changed:
                continue
            tx_hash = str(row["tx_hash"])
            effect = effects.get(tx_hash, {})
            operation_type = (
                str(effect.get("operation_type") or "")
                or str(row["operation_type"] or "")
                or service._method_to_operation_type(row["method_id"])
            )
            address_str = service._normalize_tron_address(row["user_address"]) or ""
            print(
                f"id={row['id']} ts={row['block_timestamp']} addr={address_str} "
                f"op={operation_type or '-'} tx={tx_hash}"
            )
            if heuristic_label:
                print(f"  inferred: {heuristic_label} [{heuristic_reason}]")
            print(f"  old: {old_brief}")
            print(f"  new: {new_brief}")

        print(
            f"summary: total={len(rows)} changed={changed} unchanged={unchanged} "
            f"ops={dict(label_counter)}"
        )
    finally:
        if tron_rpc is not None:
            await tron_rpc.close()
        await pool.close()


def main() -> None:
    asyncio.run(run(_build_parser().parse_args()))


if __name__ == "__main__":
    main()
