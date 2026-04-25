"""Service helpers for MakerDAO scaffold APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, NamedTuple, cast

from fastapi import HTTPException
from web3 import AsyncWeb3

from aave_crawler.rpc import build_web3
from ..config import load_config
from ..constants import (
    MAKERDAO_DAI_ADDRESS,
    MAKERDAO_CHAIN,
    MAKERDAO_DEFAULT_VAULT_TYPE,
    MAKERDAO_DEFAULT_CONTRACTS,
    MAKERDAO_DEFAULT_ILK_METADATA,
    MAKERDAO_DEFAULT_ILK_NAMES,
    MAKERDAO_PROTOCOL,
    RAD,
    RAY,
    WAD,
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

GET_CDPS_ABI = [
    {
        "inputs": [
            {"name": "manager", "type": "address"},
            {"name": "guy", "type": "address"},
        ],
        "name": "getCdpsAsc",
        "outputs": [
            {"name": "ids", "type": "uint256[]"},
            {"name": "urns", "type": "address[]"},
            {"name": "ilks", "type": "bytes32[]"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

PROXY_REGISTRY_ABI = [
    {
        "inputs": [{"name": "", "type": "address"}],
        "name": "proxies",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]

VAT_ABI = [
    {
        "inputs": [
            {"name": "", "type": "bytes32"},
            {"name": "", "type": "address"},
        ],
        "name": "urns",
        "outputs": [
            {"name": "ink", "type": "uint256"},
            {"name": "art", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "", "type": "bytes32"}],
        "name": "ilks",
        "outputs": [
            {"name": "Art", "type": "uint256"},
            {"name": "rate", "type": "uint256"},
            {"name": "spot", "type": "uint256"},
            {"name": "line", "type": "uint256"},
            {"name": "dust", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

SPOTTER_ABI = [
    {
        "inputs": [{"name": "", "type": "bytes32"}],
        "name": "ilks",
        "outputs": [
            {"name": "pip", "type": "address"},
            {"name": "mat", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

DOG_ABI = [
    {
        "inputs": [{"name": "", "type": "bytes32"}],
        "name": "ilks",
        "outputs": [
            {"name": "clip", "type": "address"},
            {"name": "chop", "type": "uint256"},
            {"name": "hole", "type": "uint256"},
            {"name": "dirt", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

ILK_REGISTRY_ABI = [
    {
        "inputs": [],
        "name": "list",
        "outputs": [{"name": "", "type": "bytes32[]"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "", "type": "bytes32"}],
        "name": "gem",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "", "type": "bytes32"}],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


class _MakerDaoContracts(NamedTuple):
    vat: str
    spotter: str
    dog: str
    cdp_manager: str
    get_cdps: str
    proxy_registry: str
    ilk_registry: str


def get_scaffold_status() -> MakerDaoScaffoldStatusResponse:
    return MakerDaoScaffoldStatusResponse(
        module=MAKERDAO_PROTOCOL,
        status="live-position",
        chain=MAKERDAO_CHAIN,
        supported_protocols=[MAKERDAO_DEFAULT_VAULT_TYPE],
        message="MakerDAO current vault position API is wired for live on-chain reads. Replay and liquidation event parsing are pending.",
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
    *,
    address: str,
    w3: Any = None,
    vault_id: int | None = None,
    ilk: str | None = None,
    include_empty: bool = False,
) -> MakerDaoVaultPositionResponse:
    normalized_address = _normalize_evm_address(address)
    if not normalized_address:
        raise HTTPException(status_code=400, detail="invalid EVM address")
    positions = await _fetch_live_vault_positions(
        normalized_address,
        w3=w3,
        vault_id=vault_id,
        ilk=ilk,
        include_empty=include_empty,
    )
    if not positions:
        raise HTTPException(status_code=404, detail="MakerDAO vault position not found")
    return MakerDaoVaultPositionResponse(
        chain=MAKERDAO_CHAIN,
        protocol=MAKERDAO_PROTOCOL,
        address=normalized_address,
        total_positions=len(positions),
        positions=positions,
    )


async def get_cached_user_vault_position(
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


async def _fetch_live_vault_positions(
    address: str,
    *,
    w3: Any,
    vault_id: int | None,
    ilk: str | None,
    include_empty: bool,
) -> list[MakerDaoVaultPositionItemResponse]:
    own_w3 = False
    active_w3 = w3
    try:
        if active_w3 is None:
            cfg = load_config()
            active_w3 = await build_web3(cast(Any, cfg))
            own_w3 = True

        contracts = _load_contract_addresses()
        latest_block = await active_w3.eth.get_block("latest")
        latest_number = latest_block.get("number")
        latest_timestamp = latest_block.get("timestamp")
        if latest_number is None or latest_timestamp is None:
            raise RuntimeError("latest block missing timestamp or number")
        block_number = int(latest_number)
        block_timestamp = datetime.fromtimestamp(int(latest_timestamp), tz=timezone.utc)
        snapshot_at = datetime.now(timezone.utc)

        cdp_refs = await _resolve_cdp_refs(active_w3, contracts, address)
        if not cdp_refs:
            cdp_refs = await _resolve_direct_urn_refs(active_w3, contracts, address)
        if vault_id is not None:
            cdp_refs = [ref for ref in cdp_refs if ref["vault_id"] == vault_id]
        if ilk is not None:
            cdp_refs = [ref for ref in cdp_refs if ref["ilk"] == ilk]

        items: list[MakerDaoVaultPositionItemResponse] = []
        for ref in cdp_refs:
            item = await _build_live_position_item(
                active_w3,
                contracts,
                ref,
                block_number=block_number,
                block_timestamp=block_timestamp,
                snapshot_at=snapshot_at,
            )
            if not include_empty and (
                Decimal(item.collateral_amount) == 0 and Decimal(item.debt_amount) == 0
            ):
                continue
            items.append(item)
        return sorted(items, key=lambda item: item.vault_id or 0)
    finally:
        if own_w3 and isinstance(active_w3, AsyncWeb3):
            try:
                await active_w3.provider.disconnect()
            except Exception:
                pass


async def _resolve_cdp_refs(
    w3: Any,
    contracts: _MakerDaoContracts,
    address: str,
) -> list[dict[str, Any]]:
    checksum_address = AsyncWeb3.to_checksum_address(address)
    owners = [checksum_address]
    proxy_registry = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(contracts.proxy_registry),
        abi=PROXY_REGISTRY_ABI,
    )
    proxy_address = await proxy_registry.functions.proxies(checksum_address).call()
    if proxy_address and proxy_address.lower() != ZERO_ADDRESS:
        owners.append(AsyncWeb3.to_checksum_address(proxy_address))

    get_cdps = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(contracts.get_cdps),
        abi=GET_CDPS_ABI,
    )
    refs: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for owner in owners:
        ids, urns, ilks = await get_cdps.functions.getCdpsAsc(
            AsyncWeb3.to_checksum_address(contracts.cdp_manager),
            owner,
        ).call()
        for index, raw_id in enumerate(ids):
            cdp_id = int(raw_id)
            if cdp_id in seen_ids:
                continue
            seen_ids.add(cdp_id)
            refs.append(
                {
                    "vault_id": cdp_id,
                    "owner_address": _checksum_or_none(owner),
                    "proxy_address": _checksum_or_none(proxy_address),
                    "urn_address": _checksum_or_none(urns[index]),
                    "ilk": _bytes32_to_text(ilks[index]),
                }
            )
    return refs


async def _resolve_direct_urn_refs(
    w3: Any,
    contracts: _MakerDaoContracts,
    address: str,
) -> list[dict[str, Any]]:
    urn_address = AsyncWeb3.to_checksum_address(address)
    vat = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(contracts.vat),
        abi=VAT_ABI,
    )
    refs: list[dict[str, Any]] = []
    for ilk_name in await _load_ilk_names(w3, contracts, include_registry=False):
        ink_raw, art_raw = await vat.functions.urns(
            _text_to_bytes32(ilk_name),
            urn_address,
        ).call()
        if int(ink_raw) == 0 and int(art_raw) == 0:
            continue
        refs.append(
            {
                "vault_id": None,
                "owner_address": None,
                "proxy_address": None,
                "urn_address": _checksum_or_none(urn_address),
                "ilk": ilk_name,
            }
        )
    return refs


async def _build_live_position_item(
    w3: Any,
    contracts: _MakerDaoContracts,
    ref: dict[str, Any],
    *,
    block_number: int,
    block_timestamp: datetime,
    snapshot_at: datetime,
) -> MakerDaoVaultPositionItemResponse:
    ilk_name = str(ref["ilk"])
    ilk_bytes = _text_to_bytes32(ilk_name)
    urn_address = AsyncWeb3.to_checksum_address(ref["urn_address"])
    vat = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(contracts.vat),
        abi=VAT_ABI,
    )
    spotter = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(contracts.spotter),
        abi=SPOTTER_ABI,
    )
    dog = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(contracts.dog),
        abi=DOG_ABI,
    )

    ink_raw, art_raw = await vat.functions.urns(ilk_bytes, urn_address).call()
    _art_total, rate_raw, spot_raw, _line_raw, _dust_raw = await vat.functions.ilks(
        ilk_bytes
    ).call()
    _pip_address, mat_raw = await spotter.functions.ilks(ilk_bytes).call()
    try:
        _clip_address, _chop_raw, _hole_raw, _dirt_raw = await dog.functions.ilks(
            ilk_bytes
        ).call()
    except Exception:
        pass

    collateral_amount = Decimal(int(ink_raw)) / Decimal(WAD)
    debt_amount = Decimal(int(art_raw)) * Decimal(int(rate_raw)) / Decimal(RAD)
    liquidation_ratio = Decimal(int(mat_raw)) / Decimal(RAY) if mat_raw else None
    collateral_price = (
        Decimal(int(spot_raw)) * Decimal(int(mat_raw)) / Decimal(RAY) / Decimal(RAY)
        if spot_raw and mat_raw
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
    metadata = await _load_ilk_metadata(w3, contracts, ilk_name)
    collateral_symbol = metadata.get("symbol") or ilk_name.split("-")[0]
    collateral_token_address = metadata.get("token_address")
    collateral_amount_str = _fmt_decimal(collateral_amount)
    debt_amount_str = _fmt_decimal(debt_amount)
    collateral_value_str = _fmt_optional_decimal(collateral_value, scale=8)
    debt_value_str = _fmt_optional_decimal(debt_value, scale=8)

    return MakerDaoVaultPositionItemResponse(
        vault_uid=(
            f"ethereum:makerdao:{ref['vault_id']}"
            if ref["vault_id"] is not None
            else f"ethereum:makerdao:urn:{urn_address.lower()}:{ilk_name}"
        ),
        vault_id=ref["vault_id"],
        vault_type=MAKERDAO_DEFAULT_VAULT_TYPE,
        ilk=ilk_name,
        urn_address=_checksum_or_none(ref["urn_address"]) or "",
        owner_address=_checksum_or_none(ref.get("owner_address")),
        proxy_address=_checksum_or_none(ref.get("proxy_address")),
        block_number=block_number,
        block_timestamp=_record_ts(block_timestamp),
        snapshot_at=_record_ts(snapshot_at),
        collateral_symbol=collateral_symbol,
        collateral_token_address=collateral_token_address,
        collateral_amount=collateral_amount_str,
        collateral_value_usd=collateral_value_str,
        debt_symbol="DAI",
        debt_token_address=MAKERDAO_DAI_ADDRESS,
        debt_amount=debt_amount_str,
        debt_value_usd=debt_value_str,
        liquidation_ratio=_fmt_optional_decimal(liquidation_ratio),
        liquidation_price_usd=_fmt_optional_decimal(liquidation_price, scale=8),
        health_factor=_fmt_optional_decimal(health_factor),
        is_healthy=is_healthy,
        data_source="onchain-live",
        assets=[
            MakerDaoPositionAssetResponse(
                role="collateral",
                token_address=collateral_token_address,
                symbol=collateral_symbol,
                amount=collateral_amount_str,
                value_usd=collateral_value_str,
            ),
            MakerDaoPositionAssetResponse(
                role="debt",
                token_address=MAKERDAO_DAI_ADDRESS,
                symbol="DAI",
                amount=debt_amount_str,
                value_usd=debt_value_str,
            ),
        ],
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


def _load_contract_addresses() -> _MakerDaoContracts:
    contracts = dict(MAKERDAO_DEFAULT_CONTRACTS)
    try:
        cfg = load_config()
        if cfg.makerdao.vat_address:
            contracts["vat"] = cfg.makerdao.vat_address
        if cfg.makerdao.spotter_address:
            contracts["spotter"] = cfg.makerdao.spotter_address
        if cfg.makerdao.dog_address:
            contracts["dog"] = cfg.makerdao.dog_address
    except FileNotFoundError:
        pass
    return _MakerDaoContracts(
        vat=contracts["vat"],
        spotter=contracts["spotter"],
        dog=contracts["dog"],
        cdp_manager=contracts["cdp_manager"],
        get_cdps=contracts["get_cdps"],
        proxy_registry=contracts["proxy_registry"],
        ilk_registry=contracts["ilk_registry"],
    )


async def _load_ilk_names(
    w3: Any,
    contracts: _MakerDaoContracts,
    *,
    include_registry: bool = True,
) -> list[str]:
    try:
        cfg = load_config()
        if cfg.makerdao.ilk_names:
            return list(dict.fromkeys(cfg.makerdao.ilk_names))
    except FileNotFoundError:
        pass
    if not include_registry:
        return MAKERDAO_DEFAULT_ILK_NAMES
    try:
        registry = w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(contracts.ilk_registry),
            abi=ILK_REGISTRY_ABI,
        )
        ilks = await registry.functions.list().call()
        names = [_bytes32_to_text(ilk) for ilk in ilks]
        if names:
            return list(dict.fromkeys(names))
    except Exception:
        pass
    return MAKERDAO_DEFAULT_ILK_NAMES


async def _load_ilk_metadata(
    w3: Any,
    contracts: _MakerDaoContracts,
    ilk_name: str,
) -> dict[str, str | None]:
    metadata: dict[str, str | None] = {
        key: value
        for key, value in MAKERDAO_DEFAULT_ILK_METADATA.get(ilk_name, {}).items()
    }
    if metadata.get("symbol") and metadata.get("token_address"):
        return metadata
    try:
        registry = w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(contracts.ilk_registry),
            abi=ILK_REGISTRY_ABI,
        )
        ilk_bytes = _text_to_bytes32(ilk_name)
        token_address = await registry.functions.gem(ilk_bytes).call()
        symbol = await registry.functions.symbol(ilk_bytes).call()
        metadata["token_address"] = _checksum_or_none(token_address)
        metadata["symbol"] = str(symbol) if symbol else ilk_name.split("-")[0]
    except Exception:
        metadata.setdefault("symbol", ilk_name.split("-")[0])
        metadata.setdefault("token_address", None)
    return metadata


def _checksum_or_none(value: Any) -> str | None:
    if value is None:
        return None
    candidate = str(value)
    if not _normalize_evm_address(candidate):
        return None
    if candidate.lower() == ZERO_ADDRESS:
        return None
    return AsyncWeb3.to_checksum_address(candidate)


def _text_to_bytes32(value: str) -> bytes:
    raw = value.encode("ascii")
    if len(raw) > 32:
        raise HTTPException(status_code=400, detail="invalid MakerDAO ilk")
    return raw.ljust(32, b"\x00")


def _bytes32_to_text(value: Any) -> str:
    if isinstance(value, str):
        if value.startswith("0x"):
            raw = bytes.fromhex(value[2:])
        else:
            return value.rstrip("\x00")
    else:
        raw = bytes(value)
    return raw.rstrip(b"\x00").decode("ascii")


def _row_get(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return row[key]


def _fmt_decimal(value: Any, scale: int = 18) -> str:
    decimal_value = Decimal(str(value or 0))
    quant = Decimal(1).scaleb(-scale)
    precision = max(
        len(decimal_value.as_tuple().digits),
        decimal_value.adjusted() + scale + 2,
        scale + 1,
    )
    with localcontext() as ctx:
        ctx.prec = precision
        normalized = decimal_value.quantize(quant).normalize()
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
