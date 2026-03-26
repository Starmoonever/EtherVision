"""Bootstrap Compound v2 daily snapshots with lazy active-user maintenance.

Required argument:
    --end  UTC date or datetime, e.g. 2019-05-08

Workflow:
1. Resolve start day from run watermark; fallback to earliest v2 history event day.
2. For each day:
   - activate users only from that day's compound_history (version=2, from_address)
   - scan current active users and write daily snapshot rows
   - refresh active flags from snapshot results
   - persist run watermark for resume
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from crawler_shared.logging import setup_cli_logging

from compound_crawler.api.service import _collect_v2_replay_snapshot_row
from compound_crawler.config import load_config
from compound_crawler.constants import COMPOUND_V2_MARKET_NAMES
from compound_crawler.crawler import (
    _block_at_timestamp,
    _build_web3,
    _is_contract_deployed_at_block,
    close_web3,
)
from compound_crawler.db import (
    UserPositionAssetRow,
    UserPositionSnapshotRow,
    activate_compound_v2_users_with_event_rows,
    create_pool,
    ensure_compound_v2_active_run_state_table,
    ensure_compound_v2_active_user_table,
    ensure_user_position_snapshot_tables,
    fetch_compound_v2_active_users,
    fetch_compound_v2_run_watermark,
    fetch_compound_v2_users_from_history_day,
    fetch_earliest_compound_event_timestamp,
    refresh_compound_v2_active_users_from_snapshots,
    upsert_compound_v2_run_watermark,
    upsert_user_position_asset_rows,
    upsert_user_position_snapshots,
)

RUNNER_NAME = "compound_v2_lazy_daily_snapshot"


def _parse_utc_datetime(value: str) -> datetime:
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"invalid utc datetime: {value}")


def _floor_utc_day(value: datetime) -> datetime:
    normalized = (
        value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    )
    normalized = normalized.astimezone(timezone.utc)
    return normalized.replace(hour=0, minute=0, second=0, microsecond=0)


def _to_user_snapshot_row(row: Any, *, point_ts: datetime) -> UserPositionSnapshotRow:
    return UserPositionSnapshotRow(
        timestamp=point_ts,
        block_number=row.block_number,
        market=row.market,
        symbol=row.symbol,
        user_address=row.user_address,
        has_open_position=row.has_open_position,
        is_liquidatable=row.is_liquidatable,
        base_token=row.base_token or b"",
        base_symbol=row.base_symbol,
        base_price_usd=Decimal(row.base_price_usd or 0),
        eth_price_usd=Decimal(row.eth_price_usd),
        total_collateral_usd=Decimal(row.total_collateral_usd),
        total_debt_usd=Decimal(row.total_debt_usd),
        discounted_collateral_usd=Decimal(row.discounted_collateral_usd),
        liquidation_buffer_usd=Decimal(row.liquidation_buffer_usd),
        health_factor=Decimal(row.health_factor),
        eth_sensitive_collateral_usd=Decimal(row.eth_sensitive_collateral_usd),
        eth_sensitive_debt_usd=Decimal(row.eth_sensitive_debt_usd),
        net_eth_exposure_usd=Decimal(row.net_eth_exposure_usd),
        non_eth_collateral_usd=Decimal(row.non_eth_collateral_usd),
        non_eth_debt_usd=Decimal(row.non_eth_debt_usd),
        basis_risk_collateral_usd=Decimal(row.basis_risk_collateral_usd),
        eth_down_liq_price_usd=(
            Decimal(row.eth_down_liq_price_usd)
            if row.eth_down_liq_price_usd is not None
            else None
        ),
        eth_up_liq_price_usd=(
            Decimal(row.eth_up_liq_price_usd)
            if row.eth_up_liq_price_usd is not None
            else None
        ),
        eth_liq_mode=row.eth_liq_mode,
        dominant_risk=row.dominant_risk,
        assets_jsonb=list(row.assets_jsonb),
    )


def _to_asset_rows(snapshot_row: UserPositionSnapshotRow) -> list[UserPositionAssetRow]:
    out: list[UserPositionAssetRow] = []
    for item in snapshot_row.assets_jsonb:
        asset = str(item.get("asset") or "").lower()
        if not asset.startswith("0x") or len(asset) != 42:
            continue
        price_in_base_raw = item.get("price_in_base")
        out.append(
            UserPositionAssetRow(
                timestamp=snapshot_row.timestamp,
                block_number=snapshot_row.block_number,
                market=snapshot_row.market,
                user_address=snapshot_row.user_address,
                asset=bytes.fromhex(asset[2:]),
                symbol=item.get("symbol"),
                side=str(item.get("side") or ""),
                decimals=None,
                amount=Decimal(str(item.get("amount") or "0")),
                price_in_base=(
                    Decimal(str(price_in_base_raw))
                    if price_in_base_raw is not None
                    else None
                ),
                price_usd=Decimal(str(item.get("price_usd") or "0")),
                value_usd=Decimal(str(item.get("value_usd") or "0")),
                discounted_value_usd=Decimal(
                    str(item.get("discounted_value_usd") or "0")
                ),
                borrow_collateral_factor=(
                    Decimal(str(item["borrow_collateral_factor"]))
                    if item.get("borrow_collateral_factor") is not None
                    else None
                ),
                liquidate_collateral_factor=(
                    Decimal(str(item["liquidate_collateral_factor"]))
                    if item.get("liquidate_collateral_factor") is not None
                    else None
                ),
                liquidation_factor=(
                    Decimal(str(item["liquidation_factor"]))
                    if item.get("liquidation_factor") is not None
                    else None
                ),
                beta_to_eth=Decimal(str(item.get("beta_to_eth") or "0")),
                is_eth_correlated=bool(item.get("is_eth_correlated")),
                is_basis_risk_asset=bool(item.get("is_basis_risk_asset")),
            )
        )
    return out


async def _resolve_deployed_markets(
    w3: Any,
    *,
    block_number: int,
) -> list[str]:
    deployment_cache: dict[str, dict[str, int]] = {}
    resolved: list[str] = []
    for market in COMPOUND_V2_MARKET_NAMES.keys():
        if await _is_contract_deployed_at_block(
            w3,
            market,
            block_number,
            deployment_cache,
        ):
            resolved.append(market)
    return resolved


async def _collect_rows_for_user(
    w3: Any,
    *,
    user_address: bytes,
    point_ts: datetime,
    block_number: int,
    markets: list[str],
    metadata_cache: dict[str, tuple[str | None, int | None]],
) -> list[UserPositionSnapshotRow]:
    rows: list[UserPositionSnapshotRow] = []
    for market in markets:
        replay_row = await _collect_v2_replay_snapshot_row(
            w3,
            user_address=user_address,
            event_market=bytes.fromhex(market[2:]),
            block_number=block_number,
            point_ts=point_ts,
            metadata_cache=metadata_cache,
        )
        rows.append(_to_user_snapshot_row(replay_row, point_ts=point_ts))
    return rows


async def _resolve_start_day(pool: Any) -> datetime:
    watermark = await fetch_compound_v2_run_watermark(pool, runner_name=RUNNER_NAME)
    if watermark is not None:
        return datetime.combine(
            watermark + timedelta(days=1),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
    earliest = await fetch_earliest_compound_event_timestamp(pool, protocol="v2")
    if earliest is None:
        raise RuntimeError("no compound v2 history rows found")
    return _floor_utc_day(earliest)


async def run(
    *,
    config_path: str | None,
    end_ts: datetime,
    dust_threshold_usd: Decimal = Decimal("1"),
    limit: int = 0,
    user_batch_size: int = 20,
    rpc_concurrency: int = 8,
    write_snapshot_batch_size: int = 500,
    write_asset_batch_size: int = 5000,
) -> None:
    cfg = load_config(config_path)
    cfg.protocol = "v2"
    end_day = _floor_utc_day(end_ts)
    pool = await create_pool(cfg.postgres)
    w3 = None
    try:
        await ensure_compound_v2_active_user_table(pool)
        await ensure_compound_v2_active_run_state_table(pool)
        await ensure_user_position_snapshot_tables(
            pool,
            protocol="v2",
            use_timescaledb=cfg.market_state.use_timescaledb,
        )

        start_day = await _resolve_start_day(pool)
        if start_day > end_day:
            print(
                f"nothing_to_do start_day={start_day.date().isoformat()} end={end_day.date().isoformat()}"
            )
            return

        w3 = await _build_web3(cfg)
        cursor = start_day
        while cursor <= end_day:
            day_start = cursor
            day_end = cursor + timedelta(days=1) - timedelta(seconds=1)
            point_ts = day_end

            history_events = await fetch_compound_v2_users_from_history_day(
                pool,
                day_start=day_start,
                day_end=day_end,
            )
            activated = await activate_compound_v2_users_with_event_rows(
                pool, history_events
            )
            active_users = await fetch_compound_v2_active_users(pool)
            if limit:
                active_users = active_users[:limit]

            print(
                "day=%s history_users=%d activated=%d active_to_scan=%d"
                % (
                    cursor.date().isoformat(),
                    len(history_events),
                    activated,
                    len(active_users),
                )
            )

            if not active_users:
                await upsert_compound_v2_run_watermark(
                    pool,
                    runner_name=RUNNER_NAME,
                    processed_date=cursor.date(),
                )
                cursor += timedelta(days=1)
                continue

            block_number = await _block_at_timestamp(
                w3, int(point_ts.timestamp()), pool=pool
            )
            deployed_markets = await _resolve_deployed_markets(
                w3, block_number=block_number
            )
            print(
                "day=%s block=%d deployed_markets=%d"
                % (cursor.date().isoformat(), block_number, len(deployed_markets))
            )
            if not deployed_markets:
                await upsert_compound_v2_run_watermark(
                    pool,
                    runner_name=RUNNER_NAME,
                    processed_date=cursor.date(),
                )
                cursor += timedelta(days=1)
                continue

            metadata_cache: dict[str, tuple[str | None, int | None]] = {}
            sem = asyncio.Semaphore(max(1, rpc_concurrency))
            pending_snapshots: list[UserPositionSnapshotRow] = []
            pending_assets: list[UserPositionAssetRow] = []
            day_snapshot_written = 0
            day_asset_written = 0

            async def _one_user(user_address: bytes) -> list[UserPositionSnapshotRow]:
                async with sem:
                    return await _collect_rows_for_user(
                        w3,
                        user_address=user_address,
                        point_ts=point_ts,
                        block_number=block_number,
                        markets=deployed_markets,
                        metadata_cache=metadata_cache,
                    )

            for chunk_start in range(0, len(active_users), user_batch_size):
                batch = active_users[chunk_start : chunk_start + user_batch_size]
                tasks = [asyncio.create_task(_one_user(user)) for user in batch]
                batch_rows: list[UserPositionSnapshotRow] = []
                try:
                    for task in asyncio.as_completed(tasks):
                        batch_rows.extend(await task)
                except Exception:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise

                await refresh_compound_v2_active_users_from_snapshots(
                    pool,
                    batch_rows,
                    point_ts=point_ts,
                    dust_threshold_usd=dust_threshold_usd,
                )
                pending_snapshots.extend(batch_rows)
                for row in batch_rows:
                    pending_assets.extend(_to_asset_rows(row))

                if (
                    len(pending_snapshots) >= write_snapshot_batch_size
                    or len(pending_assets) >= write_asset_batch_size
                ):
                    await upsert_user_position_snapshots(
                        pool, pending_snapshots, protocol="v2"
                    )
                    await upsert_user_position_asset_rows(
                        pool, pending_assets, protocol="v2"
                    )
                    day_snapshot_written += len(pending_snapshots)
                    day_asset_written += len(pending_assets)
                    pending_snapshots = []
                    pending_assets = []

            if pending_snapshots:
                await upsert_user_position_snapshots(
                    pool, pending_snapshots, protocol="v2"
                )
                await upsert_user_position_asset_rows(
                    pool, pending_assets, protocol="v2"
                )
                day_snapshot_written += len(pending_snapshots)
                day_asset_written += len(pending_assets)

            await upsert_compound_v2_run_watermark(
                pool,
                runner_name=RUNNER_NAME,
                processed_date=cursor.date(),
            )
            print(
                "day=%s snapshots_written=%d assets_written=%d"
                % (cursor.date().isoformat(), day_snapshot_written, day_asset_written)
            )
            cursor += timedelta(days=1)
    finally:
        await close_web3(w3)
        await pool.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", required=True, help="UTC end date/time")
    parser.add_argument("--config", default=None, help="config.yaml path")
    parser.add_argument("--dust-threshold-usd", default="1")
    parser.add_argument(
        "--limit", type=int, default=0, help="limit active users scanned per day"
    )
    parser.add_argument("--user-batch-size", type=int, default=20)
    parser.add_argument("--rpc-concurrency", type=int, default=8)
    parser.add_argument("--write-snapshot-batch-size", type=int, default=500)
    parser.add_argument("--write-asset-batch-size", type=int, default=5000)
    parser.add_argument("--verbose", "-v", action="store_true", default=False)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    setup_cli_logging(args.verbose)
    asyncio.run(
        run(
            config_path=args.config,
            end_ts=_parse_utc_datetime(args.end),
            dust_threshold_usd=Decimal(args.dust_threshold_usd),
            limit=args.limit,
            user_batch_size=args.user_batch_size,
            rpc_concurrency=args.rpc_concurrency,
            write_snapshot_batch_size=args.write_snapshot_batch_size,
            write_asset_batch_size=args.write_asset_batch_size,
        )
    )


if __name__ == "__main__":
    main()
