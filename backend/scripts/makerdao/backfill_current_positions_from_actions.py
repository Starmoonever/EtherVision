"""Backfill MakerDAO current positions from makerdao.makerdao_vault_action.

The source action table is maintained outside this module. Its relevant columns
are expected to match the known DDL:
vault_id, ilk, ilk_label, urn_address, owner_address.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, cast

from web3 import AsyncWeb3

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from aave_crawler.rpc import build_web3
from crawler_shared.logging import setup_cli_logging
from makerdao_crawler.api import service as makerdao_service
from makerdao_crawler.config import load_config
from makerdao_crawler.db import (
    create_pool,
    ensure_makerdao_tables,
    fetch_ilks,
)

logger = logging.getLogger(__name__)

_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


@dataclass(frozen=True)
class ActionRef:
    vault_id: int | None
    ilk: str | None
    urn_address: str | None
    owner_address: str | None
    is_system: bool


@dataclass
class BackfillStats:
    source_rows: int = 0
    skipped: int = 0
    empty: int = 0
    normal_upserts: int = 0
    system_upserts: int = 0
    errors: int = 0


@dataclass
class RefResult:
    stats: BackfillStats = field(default_factory=BackfillStats)
    normal_payloads: list[dict[str, Any]] = field(default_factory=list)
    system_payloads: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class IlkRuntimeData:
    rate_raw: int
    spot_raw: int
    mat_raw: int
    collateral_symbol: str
    collateral_token_address: str | None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read MakerDAO vault refs from makerdao.makerdao_vault_action and "
            "write current positions into loan.makerdao_current_vault_positions "
            "and loan.makerdao_system_urn_positions_current."
        )
    )
    parser.add_argument("--config", "-c", default=None, help="config.yaml path")
    parser.add_argument("--source-schema", default="makerdao")
    parser.add_argument("--source-table", default="makerdao_vault_action")
    parser.add_argument(
        "--mode",
        choices=("all", "normal", "system"),
        default="all",
        help="which position class to backfill",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="limit distinct source refs, useful for smoke tests",
    )
    parser.add_argument(
        "--include-empty",
        action="store_true",
        default=False,
        help="write zero-collateral/zero-debt positions too",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="read and evaluate positions without writing current tables",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=False,
        help="skip refs already present in current position tables",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="number of concurrent on-chain position reads",
    )
    parser.add_argument(
        "--write-batch-size",
        type=int,
        default=200,
        help="number of payloads per database executemany batch",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="enable DEBUG logging",
    )
    return parser


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


async def _load_action_refs(
    pool: Any,
    *,
    schema: str,
    table: str,
    mode: str,
    limit: int | None,
) -> list[ActionRef]:
    limit_sql = " LIMIT $1" if limit is not None else ""
    source = f"{_quote_ident(schema)}.{_quote_ident(table)}"
    normal_sql = f"""
        SELECT DISTINCT ON (vault_id)
            vault_id,
            ilk,
            ilk_label,
            urn_address,
            owner_address,
            FALSE AS is_system_ref
        FROM {source}
        WHERE vault_id IS NOT NULL
          AND urn_address IS NOT NULL
          AND (ilk_label IS NOT NULL OR ilk IS NOT NULL)
        ORDER BY vault_id, block_number DESC, log_index DESC
    """
    system_sql = f"""
        SELECT DISTINCT ON (urn_address, COALESCE(ilk_label, encode(ilk, 'hex')))
            vault_id,
            ilk,
            ilk_label,
            urn_address,
            owner_address,
            TRUE AS is_system_ref
        FROM {source}
        WHERE vault_id IS NULL
          AND urn_address IS NOT NULL
          AND (ilk_label IS NOT NULL OR ilk IS NOT NULL)
        ORDER BY urn_address, COALESCE(ilk_label, encode(ilk, 'hex')),
                 block_number DESC, log_index DESC
    """
    if mode == "normal":
        ref_sql = normal_sql
    elif mode == "system":
        ref_sql = system_sql
    else:
        ref_sql = f"({normal_sql}) UNION ALL ({system_sql})"

    sql = f"""
        SELECT
            vault_id,
            ilk,
            ilk_label,
            urn_address,
            owner_address,
            is_system_ref
        FROM ({ref_sql}) AS refs
        ORDER BY is_system_ref, vault_id NULLS LAST, ilk_label NULLS LAST, urn_address
        {limit_sql}
    """

    async with pool.acquire() as conn:
        rows = (
            await conn.fetch(sql, limit) if limit is not None else await conn.fetch(sql)
        )

    refs: list[ActionRef] = []
    for row in rows:
        ref = _row_to_ref(row)
        if ref is not None:
            refs.append(ref)
    return refs


def _row_to_ref(row: Any) -> ActionRef | None:
    vault_id = _parse_int(row["vault_id"])
    ilk = _normalize_ilk(row["ilk_label"]) or _normalize_ilk(row["ilk"])
    urn = _normalize_address(row["urn_address"])
    owner = _normalize_address(row["owner_address"])
    if ilk is None or urn is None:
        return None

    return ActionRef(
        vault_id=vault_id,
        ilk=ilk,
        urn_address=urn,
        owner_address=owner,
        is_system=bool(row["is_system_ref"]),
    )


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_address(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes | bytearray | memoryview):
        raw = bytes(value)
        if len(raw) == 32:
            raw = raw[-20:]
        if len(raw) != 20:
            return None
        candidate = "0x" + raw.hex()
    else:
        candidate = str(value).strip()
        if candidate.startswith("\\x"):
            candidate = "0x" + candidate[2:]
    if len(candidate) != 42 or not candidate.startswith("0x"):
        return None
    if candidate.lower() == _ZERO_ADDRESS:
        return None
    if not all(char in "0123456789abcdefABCDEF" for char in candidate[2:]):
        return None
    return AsyncWeb3.to_checksum_address(candidate)


def _normalize_ilk(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes | bytearray):
        candidate = bytes(value).rstrip(b"\x00").decode("ascii", errors="ignore")
    else:
        candidate = str(value).strip()
        if candidate.startswith("0x") and len(candidate) == 66:
            try:
                candidate = bytes.fromhex(candidate[2:]).rstrip(b"\x00").decode("ascii")
            except ValueError:
                pass
    candidate = candidate.strip().upper().rstrip("\x00")
    return candidate or None


def _load_contracts(cfg: Any) -> Any:
    contracts = makerdao_service._load_contract_addresses()
    overrides = {}
    if cfg.makerdao.vat_address:
        overrides["vat"] = cfg.makerdao.vat_address
    if cfg.makerdao.spotter_address:
        overrides["spotter"] = cfg.makerdao.spotter_address
    if cfg.makerdao.dog_address:
        overrides["dog"] = cfg.makerdao.dog_address
    if overrides:
        contracts = contracts._replace(**overrides)
    return contracts


def _has_open_position(item: Any) -> bool:
    return Decimal(item.collateral_amount) != 0 or Decimal(item.debt_amount) != 0


def _merge_stats(target: BackfillStats, delta: BackfillStats) -> None:
    target.skipped += delta.skipped
    target.empty += delta.empty
    target.normal_upserts += delta.normal_upserts
    target.system_upserts += delta.system_upserts
    target.errors += delta.errors


def _chunks(values: list[ActionRef], size: int) -> list[list[ActionRef]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _payload_chunks(
    values: list[dict[str, Any]],
    size: int,
) -> list[list[dict[str, Any]]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normal_uid(ref: ActionRef) -> str | None:
    if ref.vault_id is None:
        return None
    return f"ethereum:makerdao:{ref.vault_id}"


def _system_uid(ref: ActionRef) -> str | None:
    if ref.urn_address is None or ref.ilk is None:
        return None
    return f"ethereum:makerdao:system_urn:{ref.urn_address.lower()}:{ref.ilk}"


async def _load_existing_position_uids(
    pool: Any,
    refs: list[ActionRef],
) -> tuple[set[str], set[str]]:
    normal_uids = [uid for ref in refs if (uid := _normal_uid(ref)) is not None]
    system_uids = [uid for ref in refs if (uid := _system_uid(ref)) is not None]
    existing_normal: set[str] = set()
    existing_system: set[str] = set()

    async with pool.acquire() as conn:
        for chunk in _value_chunks(normal_uids, 1000):
            rows = await conn.fetch(
                """
                SELECT vault_uid
                FROM loan.makerdao_current_vault_positions
                WHERE vault_uid = ANY($1::text[])
                """,
                chunk,
            )
            existing_normal.update(str(row["vault_uid"]) for row in rows)

        for chunk in _value_chunks(system_uids, 1000):
            rows = await conn.fetch(
                """
                SELECT position_uid
                FROM loan.makerdao_system_urn_positions_current
                WHERE position_uid = ANY($1::text[])
                """,
                chunk,
            )
            existing_system.update(str(row["position_uid"]) for row in rows)

    return existing_normal, existing_system


def _value_chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _filter_existing_refs(
    refs: list[ActionRef],
    *,
    existing_normal: set[str],
    existing_system: set[str],
) -> tuple[list[ActionRef], int]:
    filtered: list[ActionRef] = []
    skipped = 0
    for ref in refs:
        if ref.is_system:
            uid = _system_uid(ref)
            if uid is not None and uid in existing_system:
                skipped += 1
                continue
        else:
            uid = _normal_uid(ref)
            if uid is not None and uid in existing_normal:
                skipped += 1
                continue
        filtered.append(ref)
    return filtered, skipped


async def _load_cached_ilks(pool: Any) -> set[str]:
    rows = await fetch_ilks(pool)
    return {str(row["ilk"] or "").upper() for row in rows if row["ilk"]}


async def _ensure_ilk_cached_once(
    pool: Any,
    *,
    w3: Any,
    cached_ilks: set[str],
    lock: asyncio.Lock,
    ilk: str,
) -> None:
    normalized_ilk = makerdao_service._normalize_ilk(ilk)
    if not normalized_ilk:
        raise ValueError(f"invalid MakerDAO ilk: {ilk!r}")
    if normalized_ilk in cached_ilks:
        return

    async with lock:
        if normalized_ilk in cached_ilks:
            return
        item = await makerdao_service._fetch_live_ilk(normalized_ilk, w3=w3)
        if item is None:
            item = makerdao_service._build_minimal_ilk_detail(normalized_ilk)
        await makerdao_service.upsert_ilk(
            pool,
            makerdao_service._ilk_item_to_payload(item),
        )
        cached_ilks.add(normalized_ilk)


async def _get_ilk_runtime_data(
    w3: Any,
    contracts: Any,
    *,
    cache: dict[str, IlkRuntimeData],
    lock: asyncio.Lock,
    ilk_name: str,
) -> IlkRuntimeData:
    cached = cache.get(ilk_name)
    if cached is not None:
        return cached

    async with lock:
        cached = cache.get(ilk_name)
        if cached is not None:
            return cached

        ilk_bytes = makerdao_service._text_to_bytes32(ilk_name)
        vat = w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(contracts.vat),
            abi=makerdao_service.VAT_ABI,
        )
        spotter = w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(contracts.spotter),
            abi=makerdao_service.SPOTTER_ABI,
        )
        _art_total, rate_raw, spot_raw, _line_raw, _dust_raw = await vat.functions.ilks(
            ilk_bytes
        ).call()
        _pip_address, mat_raw = await spotter.functions.ilks(ilk_bytes).call()
        metadata = await makerdao_service._load_ilk_metadata(w3, contracts, ilk_name)
        item = IlkRuntimeData(
            rate_raw=int(rate_raw),
            spot_raw=int(spot_raw),
            mat_raw=int(mat_raw),
            collateral_symbol=metadata.get("symbol") or ilk_name.split("-")[0],
            collateral_token_address=metadata.get("token_address"),
        )
        cache[ilk_name] = item
        return item


async def _build_item_from_ref(
    w3: Any,
    contracts: Any,
    ref: ActionRef,
    *,
    vat: Any,
    ilk_runtime_cache: dict[str, IlkRuntimeData],
    ilk_runtime_lock: asyncio.Lock,
    block_number: int,
    block_timestamp: datetime,
    snapshot_at: datetime,
) -> Any | None:
    if ref.urn_address is None or ref.ilk is None:
        return None
    ilk_name = ref.ilk
    ilk_bytes = makerdao_service._text_to_bytes32(ilk_name)
    urn_address = AsyncWeb3.to_checksum_address(ref.urn_address)
    ink_raw, art_raw = await vat.functions.urns(ilk_bytes, urn_address).call()
    ilk_data = await _get_ilk_runtime_data(
        w3,
        contracts,
        cache=ilk_runtime_cache,
        lock=ilk_runtime_lock,
        ilk_name=ilk_name,
    )

    collateral_amount = Decimal(int(ink_raw)) / Decimal(makerdao_service.WAD)
    debt_amount = (
        Decimal(int(art_raw))
        * Decimal(ilk_data.rate_raw)
        / Decimal(makerdao_service.RAD)
    )
    liquidation_ratio = (
        Decimal(ilk_data.mat_raw) / Decimal(makerdao_service.RAY)
        if ilk_data.mat_raw
        else None
    )
    collateral_price = (
        Decimal(ilk_data.spot_raw)
        * Decimal(ilk_data.mat_raw)
        / Decimal(makerdao_service.RAY)
        / Decimal(makerdao_service.RAY)
        if ilk_data.spot_raw and ilk_data.mat_raw
        else None
    )
    collateral_value = (
        collateral_amount * collateral_price if collateral_price is not None else None
    )
    debt_value = debt_amount
    liquidation_price = (
        debt_amount * liquidation_ratio / collateral_amount
        if collateral_amount > 0 and liquidation_ratio is not None
        else None
    )
    health_factor = (
        collateral_value / (debt_value * liquidation_ratio)
        if collateral_value is not None
        and liquidation_ratio is not None
        and debt_value > 0
        else None
    )
    is_healthy = (
        True
        if debt_value == 0
        else bool(health_factor is not None and health_factor >= Decimal("1"))
    )
    collateral_amount_str = makerdao_service._fmt_decimal(collateral_amount)
    debt_amount_str = makerdao_service._fmt_decimal(debt_amount)
    collateral_value_str = makerdao_service._fmt_optional_decimal(
        collateral_value,
        scale=8,
    )
    debt_value_str = makerdao_service._fmt_optional_decimal(debt_value, scale=8)

    return makerdao_service.MakerDaoVaultPositionItemResponse(
        vault_uid=(
            f"ethereum:makerdao:{ref.vault_id}"
            if ref.vault_id is not None
            else f"ethereum:makerdao:urn:{urn_address.lower()}:{ilk_name}"
        ),
        vault_id=ref.vault_id,
        vault_type=makerdao_service.MAKERDAO_DEFAULT_VAULT_TYPE,
        ilk=ilk_name,
        urn_address=makerdao_service._checksum_or_none(ref.urn_address) or "",
        owner_address=makerdao_service._checksum_or_none(ref.owner_address),
        proxy_address=None,
        block_number=block_number,
        block_timestamp=makerdao_service._record_ts(block_timestamp),
        snapshot_at=makerdao_service._record_ts(snapshot_at),
        collateral_symbol=ilk_data.collateral_symbol,
        collateral_token_address=ilk_data.collateral_token_address,
        collateral_amount=collateral_amount_str,
        collateral_value_usd=collateral_value_str,
        debt_symbol="DAI",
        debt_token_address=makerdao_service.MAKERDAO_DAI_ADDRESS,
        debt_amount=debt_amount_str,
        debt_value_usd=debt_value_str,
        liquidation_ratio=makerdao_service._fmt_optional_decimal(liquidation_ratio),
        liquidation_price_usd=makerdao_service._fmt_optional_decimal(
            liquidation_price,
            scale=8,
        ),
        health_factor=makerdao_service._fmt_optional_decimal(health_factor),
        is_healthy=is_healthy,
        data_source="onchain-live",
        assets=[
            makerdao_service.MakerDaoPositionAssetResponse(
                role="collateral",
                token_address=ilk_data.collateral_token_address,
                symbol=ilk_data.collateral_symbol,
                amount=collateral_amount_str,
                value_usd=collateral_value_str,
            ),
            makerdao_service.MakerDaoPositionAssetResponse(
                role="debt",
                token_address=makerdao_service.MAKERDAO_DAI_ADDRESS,
                symbol="DAI",
                amount=debt_amount_str,
                value_usd=debt_value_str,
            ),
        ],
    )


async def _batch_upsert_current_vault_positions(
    pool: Any,
    payloads: list[dict[str, Any]],
) -> None:
    if not payloads:
        return
    rows = [
        (
            payload["vault_uid"],
            payload.get("vault_id"),
            payload.get("chain"),
            payload.get("protocol"),
            payload.get("vault_type"),
            payload.get("ilk"),
            payload.get("urn_address"),
            payload.get("owner_address"),
            payload.get("proxy_address"),
            payload["snapshot_at"],
            payload["block_timestamp"],
            payload.get("block_number"),
            payload.get("collateral_symbol"),
            payload.get("collateral_token_address"),
            _decimal(payload.get("collateral_amount")),
            _decimal(payload.get("collateral_value_usd")),
            payload.get("debt_symbol"),
            payload.get("debt_token_address"),
            _decimal(payload.get("debt_amount")),
            _decimal(payload.get("debt_value_usd")),
            _decimal(payload.get("liquidation_ratio")),
            _decimal(payload.get("liquidation_price_usd")),
            _decimal(payload.get("health_factor")),
            bool(payload.get("is_healthy", True)),
            json.dumps(payload.get("extra_jsonb") or {}),
        )
        for payload in payloads
    ]
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO loan.makerdao_current_vault_positions (
                vault_uid,
                vault_id,
                chain,
                protocol,
                vault_type,
                ilk,
                urn_address,
                owner_address,
                proxy_address,
                snapshot_at,
                block_timestamp,
                block_number,
                collateral_symbol,
                collateral_token_address,
                collateral_amount,
                collateral_value_usd,
                debt_symbol,
                debt_token_address,
                debt_amount,
                debt_value_usd,
                liquidation_ratio,
                liquidation_price_usd,
                health_factor,
                is_healthy,
                extra_jsonb,
                updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9,
                $10, $11, $12, $13, $14, $15, $16, $17,
                $18, $19, $20, $21, $22, $23, $24, $25::jsonb, NOW()
            )
            ON CONFLICT (vault_uid) DO UPDATE SET
                vault_id = EXCLUDED.vault_id,
                chain = EXCLUDED.chain,
                protocol = EXCLUDED.protocol,
                vault_type = EXCLUDED.vault_type,
                ilk = EXCLUDED.ilk,
                urn_address = EXCLUDED.urn_address,
                owner_address = EXCLUDED.owner_address,
                proxy_address = EXCLUDED.proxy_address,
                snapshot_at = EXCLUDED.snapshot_at,
                block_timestamp = EXCLUDED.block_timestamp,
                block_number = EXCLUDED.block_number,
                collateral_symbol = EXCLUDED.collateral_symbol,
                collateral_token_address = EXCLUDED.collateral_token_address,
                collateral_amount = EXCLUDED.collateral_amount,
                collateral_value_usd = EXCLUDED.collateral_value_usd,
                debt_symbol = EXCLUDED.debt_symbol,
                debt_token_address = EXCLUDED.debt_token_address,
                debt_amount = EXCLUDED.debt_amount,
                debt_value_usd = EXCLUDED.debt_value_usd,
                liquidation_ratio = EXCLUDED.liquidation_ratio,
                liquidation_price_usd = EXCLUDED.liquidation_price_usd,
                health_factor = EXCLUDED.health_factor,
                is_healthy = EXCLUDED.is_healthy,
                extra_jsonb = EXCLUDED.extra_jsonb,
                updated_at = NOW()
            """,
            rows,
        )


async def _batch_upsert_system_urn_positions(
    pool: Any,
    payloads: list[dict[str, Any]],
) -> None:
    if not payloads:
        return
    rows = [
        (
            payload["position_uid"],
            payload.get("chain"),
            payload.get("protocol"),
            payload.get("position_type"),
            payload.get("ilk"),
            payload.get("urn_address"),
            payload["snapshot_at"],
            payload["block_timestamp"],
            payload.get("block_number"),
            payload.get("collateral_symbol"),
            payload.get("collateral_token_address"),
            _decimal(payload.get("collateral_amount")),
            _decimal(payload.get("collateral_value_usd")),
            payload.get("debt_symbol"),
            payload.get("debt_token_address"),
            _decimal(payload.get("debt_amount")),
            _decimal(payload.get("debt_value_usd")),
            _decimal(payload.get("liquidation_ratio")),
            _decimal(payload.get("liquidation_price_usd")),
            _decimal(payload.get("health_factor")),
            bool(payload.get("is_healthy", True)),
            json.dumps(payload.get("extra_jsonb") or {}),
        )
        for payload in payloads
    ]
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO loan.makerdao_system_urn_positions_current (
                position_uid,
                chain,
                protocol,
                position_type,
                ilk,
                urn_address,
                snapshot_at,
                block_timestamp,
                block_number,
                collateral_symbol,
                collateral_token_address,
                collateral_amount,
                collateral_value_usd,
                debt_symbol,
                debt_token_address,
                debt_amount,
                debt_value_usd,
                liquidation_ratio,
                liquidation_price_usd,
                health_factor,
                is_healthy,
                extra_jsonb,
                updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9,
                $10, $11, $12, $13, $14, $15, $16, $17,
                $18, $19, $20, $21, $22::jsonb, NOW()
            )
            ON CONFLICT (position_uid) DO UPDATE SET
                chain = EXCLUDED.chain,
                protocol = EXCLUDED.protocol,
                position_type = EXCLUDED.position_type,
                ilk = EXCLUDED.ilk,
                urn_address = EXCLUDED.urn_address,
                snapshot_at = EXCLUDED.snapshot_at,
                block_timestamp = EXCLUDED.block_timestamp,
                block_number = EXCLUDED.block_number,
                collateral_symbol = EXCLUDED.collateral_symbol,
                collateral_token_address = EXCLUDED.collateral_token_address,
                collateral_amount = EXCLUDED.collateral_amount,
                collateral_value_usd = EXCLUDED.collateral_value_usd,
                debt_symbol = EXCLUDED.debt_symbol,
                debt_token_address = EXCLUDED.debt_token_address,
                debt_amount = EXCLUDED.debt_amount,
                debt_value_usd = EXCLUDED.debt_value_usd,
                liquidation_ratio = EXCLUDED.liquidation_ratio,
                liquidation_price_usd = EXCLUDED.liquidation_price_usd,
                health_factor = EXCLUDED.health_factor,
                is_healthy = EXCLUDED.is_healthy,
                extra_jsonb = EXCLUDED.extra_jsonb,
                updated_at = NOW()
            """,
            rows,
        )


async def _flush_payloads(
    pool: Any,
    *,
    normal_payloads: list[dict[str, Any]],
    system_payloads: list[dict[str, Any]],
    write_batch_size: int,
) -> None:
    size = max(1, write_batch_size)
    for chunk in _payload_chunks(normal_payloads, size):
        await _batch_upsert_current_vault_positions(pool, chunk)
    for chunk in _payload_chunks(system_payloads, size):
        await _batch_upsert_system_urn_positions(pool, chunk)


async def _backfill(args: argparse.Namespace) -> BackfillStats:
    cfg = load_config(args.config)
    pool = await create_pool(cfg.postgres)
    w3 = None
    stats = BackfillStats()
    try:
        await ensure_makerdao_tables(pool)
        refs = await _load_action_refs(
            pool,
            schema=args.source_schema,
            table=args.source_table,
            mode=args.mode,
            limit=args.limit,
        )
        stats.source_rows = len(refs)
        logger.info("loaded %s distinct MakerDAO action refs", len(refs))
        if args.skip_existing:
            existing_normal, existing_system = await _load_existing_position_uids(
                pool,
                refs,
            )
            refs, skipped_existing = _filter_existing_refs(
                refs,
                existing_normal=existing_normal,
                existing_system=existing_system,
            )
            stats.skipped += skipped_existing
            logger.info(
                "skip-existing filtered %s refs; remaining=%s",
                skipped_existing,
                len(refs),
            )
        cached_ilks = await _load_cached_ilks(pool)

        w3 = await build_web3(cast(Any, cfg))
        contracts = _load_contracts(cfg)
        vat = w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(contracts.vat),
            abi=makerdao_service.VAT_ABI,
        )
        latest_block = await w3.eth.get_block("latest")
        latest_number = latest_block.get("number")
        latest_timestamp = latest_block.get("timestamp")
        if latest_number is None or latest_timestamp is None:
            raise RuntimeError("latest block missing timestamp or number")
        block_number = int(latest_number)
        block_timestamp = datetime.fromtimestamp(int(latest_timestamp), tz=timezone.utc)
        snapshot_at = datetime.now(timezone.utc)

        seen_normal: set[str] = set()
        seen_system: set[str] = set()
        ilk_lock = asyncio.Lock()
        ilk_runtime_cache: dict[str, IlkRuntimeData] = {}
        ilk_runtime_lock = asyncio.Lock()

        async def _process_ref(ref: ActionRef) -> RefResult:
            result = RefResult()
            try:
                if ref.is_system:
                    item = await _build_item_from_ref(
                        w3,
                        contracts,
                        ref,
                        vat=vat,
                        ilk_runtime_cache=ilk_runtime_cache,
                        ilk_runtime_lock=ilk_runtime_lock,
                        block_number=block_number,
                        block_timestamp=block_timestamp,
                        snapshot_at=snapshot_at,
                    )
                    if item is None:
                        result.stats.skipped += 1
                        return result
                    system_item = makerdao_service._system_urn_position_from_vault_item(
                        item
                    )
                    if system_item.position_uid in seen_system:
                        return result
                    seen_system.add(system_item.position_uid)
                    if not args.include_empty and not _has_open_position(system_item):
                        result.stats.empty += 1
                        return result
                    if not args.dry_run:
                        await _ensure_ilk_cached_once(
                            pool,
                            w3=w3,
                            cached_ilks=cached_ilks,
                            lock=ilk_lock,
                            ilk=system_item.ilk,
                        )
                        result.system_payloads.append(
                            makerdao_service._system_urn_position_to_payload(
                                system_item
                            ),
                        )
                    result.stats.system_upserts += 1
                    return result

                item = await _build_item_from_ref(
                    w3,
                    contracts,
                    ref,
                    vat=vat,
                    ilk_runtime_cache=ilk_runtime_cache,
                    ilk_runtime_lock=ilk_runtime_lock,
                    block_number=block_number,
                    block_timestamp=block_timestamp,
                    snapshot_at=snapshot_at,
                )
                normal_items = [item] if item is not None else []
                if not normal_items:
                    result.stats.skipped += 1
                    return result
                for normal_item in normal_items:
                    if normal_item.vault_uid in seen_normal:
                        continue
                    seen_normal.add(normal_item.vault_uid)
                    if not args.include_empty and not _has_open_position(normal_item):
                        result.stats.empty += 1
                        continue
                    if not args.dry_run:
                        await _ensure_ilk_cached_once(
                            pool,
                            w3=w3,
                            cached_ilks=cached_ilks,
                            lock=ilk_lock,
                            ilk=normal_item.ilk,
                        )
                        result.normal_payloads.append(
                            makerdao_service._vault_position_item_to_payload(
                                normal_item
                            ),
                        )
                    result.stats.normal_upserts += 1
            except Exception:
                result.stats.errors += 1
                logger.exception("failed to backfill MakerDAO ref: %s", ref)
            return result

        concurrency = max(1, int(args.concurrency))
        for batch in _chunks(refs, concurrency):
            results = await asyncio.gather(*(_process_ref(ref) for ref in batch))
            normal_payloads: list[dict[str, Any]] = []
            system_payloads: list[dict[str, Any]] = []
            for result in results:
                _merge_stats(stats, result.stats)
                normal_payloads.extend(result.normal_payloads)
                system_payloads.extend(result.system_payloads)
            if not args.dry_run:
                await _flush_payloads(
                    pool,
                    normal_payloads=normal_payloads,
                    system_payloads=system_payloads,
                    write_batch_size=args.write_batch_size,
                )

        return stats
    finally:
        if w3 is not None:
            await w3.provider.disconnect()
        await pool.close()


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    setup_cli_logging(args.verbose)
    stats = asyncio.run(_backfill(args))
    action = "would write" if args.dry_run else "wrote"
    print(
        f"{action}: source_refs={stats.source_rows} "
        f"normal={stats.normal_upserts} system={stats.system_upserts} "
        f"empty={stats.empty} skipped={stats.skipped} errors={stats.errors}"
    )


if __name__ == "__main__":
    main()
