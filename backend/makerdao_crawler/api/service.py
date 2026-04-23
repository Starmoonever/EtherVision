"""Service helpers for MakerDAO scaffold APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException

from ..constants import (
    MAKERDAO_CHAIN,
    MAKERDAO_DEFAULT_VAULT_TYPE,
    MAKERDAO_PROTOCOL,
)
from ..db import fetch_current_vault_positions, fetch_ilks
from .schemas import (
    MakerDaoIlkListItem,
    MakerDaoIlkListResponse,
    MakerDaoPositionAssetResponse,
    MakerDaoScaffoldStatusResponse,
    MakerDaoVaultPositionItemResponse,
    MakerDaoVaultPositionResponse,
)


def get_scaffold_status() -> MakerDaoScaffoldStatusResponse:
    return MakerDaoScaffoldStatusResponse(
        module=MAKERDAO_PROTOCOL,
        status="scaffold",
        chain=MAKERDAO_CHAIN,
        supported_protocols=[MAKERDAO_DEFAULT_VAULT_TYPE],
        message="MakerDAO backend scaffold is wired into the unified API. Vault crawling and replay logic are pending.",
    )


async def get_ilks(pool: Any) -> MakerDaoIlkListResponse:
    rows = await fetch_ilks(pool)
    return MakerDaoIlkListResponse(
        chain=MAKERDAO_CHAIN,
        protocol=MAKERDAO_PROTOCOL,
        ilks=[
            MakerDaoIlkListItem(
                ilk=str(_row_get(row, "ilk") or ""),
                vault_type=str(
                    _row_get(row, "vault_type") or MAKERDAO_DEFAULT_VAULT_TYPE
                ),
                gem_symbol=_row_get(row, "gem_symbol"),
                gem_address=_row_get(row, "gem_address"),
                debt_ceiling=_fmt_optional_decimal(_row_get(row, "debt_ceiling")),
                liquidation_ratio=_fmt_optional_decimal(
                    _row_get(row, "liquidation_ratio")
                ),
                liquidation_penalty=_fmt_optional_decimal(
                    _row_get(row, "liquidation_penalty")
                ),
                stability_fee=_fmt_optional_decimal(_row_get(row, "stability_fee")),
                dust=_fmt_optional_decimal(_row_get(row, "dust")),
                updated_at=_record_ts(_row_get(row, "updated_at")),
            )
            for row in rows
        ],
    )


async def get_user_vault_position(
    pool: Any,
    *,
    address: str,
    vault_id: int | None = None,
    ilk: str | None = None,
) -> MakerDaoVaultPositionResponse:
    normalized_address = _normalize_evm_address(address)
    if not normalized_address:
        raise HTTPException(status_code=400, detail="invalid EVM address")
    rows = await fetch_current_vault_positions(
        pool,
        address=normalized_address,
        vault_id=vault_id,
        ilk=ilk,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="MakerDAO vault position not found")
    positions = [_build_position_item(row) for row in rows]
    return MakerDaoVaultPositionResponse(
        chain=MAKERDAO_CHAIN,
        protocol=MAKERDAO_PROTOCOL,
        address=normalized_address,
        total_positions=len(positions),
        positions=positions,
    )


def _build_position_item(row: Any) -> MakerDaoVaultPositionItemResponse:
    collateral_amount = _fmt_decimal(_row_get(row, "collateral_amount"))
    debt_amount = _fmt_decimal(_row_get(row, "debt_amount"))
    collateral_value = _fmt_optional_decimal(_row_get(row, "collateral_value_usd"))
    debt_value = _fmt_optional_decimal(_row_get(row, "debt_value_usd"))
    return MakerDaoVaultPositionItemResponse(
        vault_uid=str(_row_get(row, "vault_uid") or ""),
        vault_id=_row_get(row, "vault_id"),
        vault_type=str(_row_get(row, "vault_type") or MAKERDAO_DEFAULT_VAULT_TYPE),
        ilk=str(_row_get(row, "ilk") or ""),
        urn_address=str(_row_get(row, "urn_address") or ""),
        owner_address=_row_get(row, "owner_address"),
        proxy_address=_row_get(row, "proxy_address"),
        block_number=_row_get(row, "block_number"),
        block_timestamp=_record_ts(_row_get(row, "block_timestamp")),
        snapshot_at=_record_ts(_row_get(row, "snapshot_at")),
        collateral_symbol=_row_get(row, "collateral_symbol"),
        collateral_token_address=_row_get(row, "collateral_token_address"),
        collateral_amount=collateral_amount,
        collateral_value_usd=collateral_value,
        debt_symbol=str(_row_get(row, "debt_symbol") or "DAI"),
        debt_token_address=_row_get(row, "debt_token_address"),
        debt_amount=debt_amount,
        debt_value_usd=debt_value,
        liquidation_ratio=_fmt_optional_decimal(_row_get(row, "liquidation_ratio")),
        liquidation_price_usd=_fmt_optional_decimal(
            _row_get(row, "liquidation_price_usd")
        ),
        health_factor=_fmt_optional_decimal(_row_get(row, "health_factor")),
        is_healthy=bool(_row_get(row, "is_healthy")),
        data_source="cache",
        assets=[
            MakerDaoPositionAssetResponse(
                role="collateral",
                token_address=_row_get(row, "collateral_token_address"),
                symbol=_row_get(row, "collateral_symbol"),
                amount=collateral_amount,
                value_usd=collateral_value,
            ),
            MakerDaoPositionAssetResponse(
                role="debt",
                token_address=_row_get(row, "debt_token_address"),
                symbol=str(_row_get(row, "debt_symbol") or "DAI"),
                amount=debt_amount,
                value_usd=debt_value,
            ),
        ],
    )


def _normalize_evm_address(value: str) -> str | None:
    candidate = value.strip()
    if len(candidate) != 42 or not candidate.startswith("0x"):
        return None
    hex_part = candidate[2:]
    if not all(char in "0123456789abcdefABCDEF" for char in hex_part):
        return None
    return "0x" + hex_part.lower()


def _row_get(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return row[key]


def _fmt_decimal(value: Any, scale: int = 18) -> str:
    decimal_value = Decimal(str(value or 0))
    normalized = decimal_value.quantize(Decimal(1).scaleb(-scale)).normalize()
    return format(normalized, "f")


def _fmt_optional_decimal(value: Any, scale: int = 18) -> str | None:
    if value is None:
        return None
    try:
        return _fmt_decimal(value, scale=scale)
    except (InvalidOperation, ValueError):
        return None


def _record_ts(value: Any) -> str:
    if not isinstance(value, datetime):
        raise TypeError(f"Unsupported datetime value: {value!r}")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
