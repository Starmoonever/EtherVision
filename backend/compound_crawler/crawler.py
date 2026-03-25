"""Batch crawler entry for Compound positions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from aave_crawler.market_collector import _block_at_timestamp
import asyncpg
from web3 import AsyncHTTPProvider, AsyncWeb3

from .config import AppConfig
from .constants import (
    CHAINLINK_AGGREGATOR_V3_ABI,
    COMET_ABI,
    COMPOUND_V2_ORACLE_ABI,
    COMPOUND_V2_MARKETS,
    COMPOUND_V2_MARKET_NAMES,
    COMPOUND_V3_MARKETS,
    COMPOUND_V3_MARKET_NAMES,
    COMPTROLLER_V2_ABI,
    CTOKEN_V2_ABI,
    ERC20_METADATA_ABI,
    ERC20_SYMBOL_BYTES32_ABI,
)
from .db import (
    MarketSnapshotRow,
    MarketConfigAssetRow,
    MarketConfigVersionRow,
    MarketStatusSnapshotRow,
    ReserveSnapshotRow,
    V2MarketConfigVersionRow,
    V2ProtocolConfigVersionRow,
    ensure_market_state_tables,
    fetch_existing_governance_markets,
    fetch_existing_v2_config_markets,
    market_table_name,
    upsert_market_config_asset_rows,
    upsert_market_config_versions,
    upsert_market_snapshots,
    upsert_market_status_snapshots,
    upsert_v2_market_config_versions,
    upsert_v2_protocol_config_versions,
    upsert_reserve_snapshots,
)

logger = logging.getLogger(__name__)

ETH_CHAIN_ID = 1
COMET_PRICE_SCALE = Decimal(10**8)
ONE = Decimal("1")
WETH_MAINNET = "0xc02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
ETH_USD_PRICE_FEED = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"
PUBLIC_RPCS = [
    "https://eth.llamarpc.com",
    "https://ethereum-rpc.publicnode.com",
    "https://rpc.ankr.com/eth",
]

COMET_FACTOR_SCALE = Decimal(10**18)
SECONDS_PER_YEAR = Decimal("31536000")
SECONDS_PER_BLOCK_V2 = Decimal("12")


async def _build_web3(cfg: AppConfig) -> AsyncWeb3:
    """Build AsyncWeb3 for Ethereum mainnet using compound config."""
    timeout = cfg.crawler.rpc_timeout

    async def _safe_disconnect(w3: AsyncWeb3) -> None:
        try:
            await w3.provider.disconnect()
        except Exception:
            pass

    async def _try_url(url: str) -> AsyncWeb3 | None:
        w3 = AsyncWeb3(AsyncHTTPProvider(url, request_kwargs={"timeout": timeout}))
        try:
            chain_id = await w3.eth.chain_id
            if chain_id != ETH_CHAIN_ID:
                logger.warning(
                    "RPC %s chain_id=%d, not Ethereum mainnet(%d), skipped",
                    url,
                    chain_id,
                    ETH_CHAIN_ID,
                )
                await _safe_disconnect(w3)
                return None
            logger.info("Using RPC: %s (chain_id=1)", url)
            return w3
        except Exception as exc:
            logger.debug("RPC %s probe failed: %s", url, exc)
            await _safe_disconnect(w3)
            return None

    custom = (cfg.rpc_url or "").strip()
    if custom:
        w3 = await _try_url(custom)
        if w3 is not None:
            return w3
        logger.warning("Custom RPC unavailable, fallback to public endpoints")

    for url in PUBLIC_RPCS:
        w3 = await _try_url(url)
        if w3 is not None:
            return w3

    raise RuntimeError("All RPC endpoints are unavailable")


async def close_web3(w3: AsyncWeb3 | None) -> None:
    if w3 is None:
        return
    try:
        await w3.provider.disconnect()
    except Exception:
        pass


def _to_bytes(address: str) -> bytes:
    addr = address.strip().lower()
    if addr.startswith("0x"):
        addr = addr[2:]
    if addr == "":
        return b""
    return bytes.fromhex(addr)


def _optional_to_bytes(address: str | None) -> bytes | None:
    if not address:
        return None
    return _to_bytes(address)


def _scale_factor(value: int | str) -> Decimal:
    return Decimal(int(value)) / COMET_FACTOR_SCALE


def _normalize_address_text(address: str | None) -> str | None:
    if not address:
        return None
    return address.lower()


def _governance_config_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _annualize_factor(value: int | str) -> Decimal:
    return _scale_factor(value) * SECONDS_PER_YEAR


def _market_addresses(cfg: AppConfig) -> list[str]:
    if cfg.protocol == "v2":
        markets = cfg.market_state.v2_markets or COMPOUND_V2_MARKETS
    else:
        markets = cfg.market_state.v3_markets or COMPOUND_V3_MARKETS
    if markets:
        return markets
    placeholder = f"{cfg.protocol}_default_market"
    logger.warning(
        "No %s market addresses configured in compound_market_state.%s_markets; using placeholder market '%s'",
        cfg.protocol,
        cfg.protocol,
        placeholder,
    )
    return [placeholder]


def _scale_to_decimals(scale: int) -> int:
    if scale <= 0:
        return 0
    s = scale
    d = 0
    while s % 10 == 0:
        d += 1
        s //= 10
    return d


def _market_name_map(protocol: str) -> dict[str, str]:
    if protocol == "v3":
        return COMPOUND_V3_MARKET_NAMES
    return COMPOUND_V2_MARKET_NAMES


def _resolve_market_name(protocol: str, market_address: str) -> str:
    name = _market_name_map(protocol).get(market_address.lower())
    if name:
        return name
    return "MARKET"


async def _is_contract_deployed_at_block(
    w3: AsyncWeb3,
    address: str,
    block_number: int,
    cache: dict[str, dict[str, int]],
) -> bool:
    key = address.lower()
    state = cache.setdefault(key, {})

    deployed_from = state.get("deployed_from")
    if deployed_from is not None and block_number >= deployed_from:
        return True

    missing_through = state.get("missing_through")
    if missing_through is not None and block_number <= missing_through:
        return False

    code = await w3.eth.get_code(
        AsyncWeb3.to_checksum_address(address), block_identifier=block_number
    )
    has_code = bytes(code) != b""
    if has_code:
        if deployed_from is None or block_number < deployed_from:
            state["deployed_from"] = block_number
    else:
        if missing_through is None or block_number > missing_through:
            state["missing_through"] = block_number
    return has_code


async def _price_from_feed_direct(
    w3: AsyncWeb3,
    price_feed: str,
    block_number: int,
) -> Decimal:
    feed = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(price_feed),
        abi=CHAINLINK_AGGREGATOR_V3_ABI,
    )
    decimals, round_data = await asyncio.gather(
        feed.functions.decimals().call(block_identifier=block_number),
        feed.functions.latestRoundData().call(block_identifier=block_number),
    )
    answer = int(round_data[1])
    if answer <= 0:
        return Decimal("0")
    return Decimal(answer) / (Decimal(10) ** int(decimals))


async def _price_from_comet(
    comet: Any,
    price_feed: str,
    block_number: int,
) -> Decimal:
    price_raw = await comet.functions.getPrice(
        AsyncWeb3.to_checksum_address(price_feed)
    ).call(block_identifier=block_number)
    if int(price_raw) <= 0:
        return Decimal("0")
    return Decimal(int(price_raw)) / COMET_PRICE_SCALE


async def _price_from_oracle(
    w3: AsyncWeb3,
    comet: Any,
    price_feed: str,
    block_number: int,
) -> Decimal:
    try:
        return await _price_from_comet(comet, price_feed, block_number)
    except Exception as exc:
        logger.debug(
            "Comet.getPrice failed for feed=%s block=%s, fallback to latestRoundData: %s",
            price_feed,
            block_number,
            exc,
        )
        return await _price_from_feed_direct(w3, price_feed, block_number)


async def _base_token_usd_price(
    w3: AsyncWeb3,
    comet: Any,
    base_token: str,
    base_token_feed: str,
    block_number: int,
) -> Decimal:
    if base_token.lower() == WETH_MAINNET.lower():
        return await _price_from_feed_direct(w3, ETH_USD_PRICE_FEED, block_number)
    return await _price_from_oracle(w3, comet, base_token_feed, block_number)


def _decode_symbol_bytes32(value: Any) -> str | None:
    if not isinstance(value, (bytes, bytearray)):
        return None
    raw = bytes(value).rstrip(b"\x00")
    if not raw:
        return None
    try:
        return raw.decode("utf-8")
    except Exception:
        return None


async def _token_metadata(
    w3: AsyncWeb3,
    token_address: str,
    block_number: int,
    cache: dict[str, tuple[str | None, int | None]],
) -> tuple[str | None, int | None]:
    key = token_address.lower()
    if key in cache:
        return cache[key]

    checksum = AsyncWeb3.to_checksum_address(token_address)
    symbol: str | None = None
    decimals: int | None = None

    try:
        token = w3.eth.contract(address=checksum, abi=ERC20_METADATA_ABI)
        symbol_res, decimals_res = await asyncio.gather(
            token.functions.symbol().call(block_identifier=block_number),
            token.functions.decimals().call(block_identifier=block_number),
        )
        symbol = str(symbol_res) if symbol_res is not None else None
        decimals = int(decimals_res) if decimals_res is not None else None
    except Exception:
        try:
            token_dec = w3.eth.contract(address=checksum, abi=ERC20_METADATA_ABI)
            decimals_res = await token_dec.functions.decimals().call(
                block_identifier=block_number
            )
            decimals = int(decimals_res)
        except Exception:
            decimals = None
        try:
            token_sym32 = w3.eth.contract(
                address=checksum, abi=ERC20_SYMBOL_BYTES32_ABI
            )
            sym32 = await token_sym32.functions.symbol().call(
                block_identifier=block_number
            )
            symbol = _decode_symbol_bytes32(sym32)
        except Exception:
            symbol = None

    cache[key] = (symbol, decimals)
    return cache[key]


async def _v2_underlying_price_usd(
    w3: AsyncWeb3,
    ctoken_address: str,
    comptroller_address: str,
    underlying_decimals: int,
    block_number: int,
) -> Decimal:
    comptroller = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(comptroller_address),
        abi=COMPTROLLER_V2_ABI,
    )
    oracle_address = await comptroller.functions.oracle().call(
        block_identifier=block_number
    )
    oracle = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(str(oracle_address)),
        abi=COMPOUND_V2_ORACLE_ABI,
    )
    raw_price = await oracle.functions.getUnderlyingPrice(
        AsyncWeb3.to_checksum_address(ctoken_address)
    ).call(block_identifier=block_number)
    price_int = int(raw_price)
    if price_int <= 0:
        return Decimal("0")
    return Decimal(price_int) / (Decimal(10) ** max(0, 36 - underlying_decimals))


async def _collect_v2_market_at_block(
    w3: AsyncWeb3,
    protocol: str,
    market_address: str,
    point_ts: datetime,
    block_number: int,
    metadata_cache: dict[str, tuple[str | None, int | None]],
) -> tuple[MarketSnapshotRow, list[ReserveSnapshotRow]]:
    ctoken = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(market_address),
        abi=CTOKEN_V2_ABI,
    )
    ctoken_checksum = AsyncWeb3.to_checksum_address(market_address)

    (
        ctoken_symbol_raw,
        total_borrow_raw,
        total_reserves_raw,
        borrow_rate_raw,
        supply_rate_raw,
        reserve_factor_raw,
        comptroller_raw,
    ) = await asyncio.gather(
        ctoken.functions.symbol().call(block_identifier=block_number),
        ctoken.functions.totalBorrows().call(block_identifier=block_number),
        ctoken.functions.totalReserves().call(block_identifier=block_number),
        ctoken.functions.borrowRatePerBlock().call(block_identifier=block_number),
        ctoken.functions.supplyRatePerBlock().call(block_identifier=block_number),
        ctoken.functions.reserveFactorMantissa().call(block_identifier=block_number),
        ctoken.functions.comptroller().call(block_identifier=block_number),
    )
    try:
        cash_raw = await ctoken.functions.getCash().call(block_identifier=block_number)
    except Exception:
        # cETH does not expose getCash(); fallback to contract ETH balance.
        cash_raw = await w3.eth.get_balance(
            ctoken_checksum, block_identifier=block_number
        )
    ctoken_symbol = (
        str(ctoken_symbol_raw)
        if ctoken_symbol_raw is not None
        else _resolve_market_name(protocol, market_address)
    )

    # cETH has no underlying() method.
    try:
        underlying_address = str(
            await ctoken.functions.underlying().call(block_identifier=block_number)
        )
        underlying_symbol, underlying_decimals_meta = await _token_metadata(
            w3, underlying_address, block_number, metadata_cache
        )
        underlying_decimals = int(underlying_decimals_meta or 18)
    except Exception:
        underlying_address = WETH_MAINNET
        underlying_symbol = "ETH"
        underlying_decimals = 18

    try:
        price_usd = await _v2_underlying_price_usd(
            w3,
            ctoken_address=market_address,
            comptroller_address=str(comptroller_raw),
            underlying_decimals=underlying_decimals,
            block_number=block_number,
        )
    except Exception as exc:
        # Historical v2 oracle calls can revert for some markets/blocks.
        # Keep the snapshot writable by degrading price lookup behavior.
        if underlying_address.lower() == WETH_MAINNET.lower():
            try:
                price_usd = await _price_from_feed_direct(
                    w3, ETH_USD_PRICE_FEED, block_number
                )
                logger.warning(
                    "v2 oracle price failed, fallback to ETH/USD feed: market=%s block=%s err=%s",
                    market_address,
                    block_number,
                    exc,
                )
            except Exception as feed_exc:
                logger.warning(
                    "v2 price fallback failed, set price_usd=0: market=%s block=%s oracle_err=%s feed_err=%s",
                    market_address,
                    block_number,
                    exc,
                    feed_exc,
                )
                price_usd = Decimal("0")
        else:
            logger.warning(
                "v2 oracle price failed, set price_usd=0: market=%s block=%s err=%s",
                market_address,
                block_number,
                exc,
            )
            price_usd = Decimal("0")

    decimals_scale = Decimal(10) ** underlying_decimals
    total_borrow = Decimal(int(total_borrow_raw)) / decimals_scale
    total_reserves = Decimal(int(total_reserves_raw)) / decimals_scale
    cash = Decimal(int(cash_raw)) / decimals_scale
    total_supply = cash + total_borrow - total_reserves
    if total_supply < 0:
        total_supply = Decimal("0")
    utilization = (total_borrow / total_supply) if total_supply > 0 else Decimal("0")

    borrow_rate_raw_int = int(borrow_rate_raw)
    supply_rate_raw_int = int(supply_rate_raw)
    reserve_factor = Decimal(int(reserve_factor_raw)) / COMET_FACTOR_SCALE
    borrow_rate = (
        Decimal(borrow_rate_raw_int) / COMET_FACTOR_SCALE / SECONDS_PER_BLOCK_V2
    )
    supply_rate_chain = (
        Decimal(supply_rate_raw_int) / COMET_FACTOR_SCALE / SECONDS_PER_BLOCK_V2
    )
    one_minus_reserve_factor = Decimal("1") - reserve_factor
    supply_rate_formula = Decimal("0")
    if borrow_rate > 0 and utilization > 0 and one_minus_reserve_factor > 0:
        supply_rate_formula = borrow_rate * utilization * one_minus_reserve_factor
    # NOTE:
    # Some environments return reserveFactorMantissa=1e18 for v2 markets, which
    # makes on-chain supplyRatePerBlock and the net formula both zero. For market
    # trend visualization we fallback to gross lender rate (borrow * utilization)
    # so the chart does not collapse to a flat zero line.
    supply_rate_gross = (
        borrow_rate * utilization
        if borrow_rate > 0 and utilization > 0
        else Decimal("0")
    )
    if supply_rate_chain > 0:
        supply_rate = supply_rate_chain
    elif supply_rate_formula > 0:
        supply_rate = supply_rate_formula
    else:
        supply_rate = supply_rate_gross
    supply_usd = total_supply * price_usd
    borrow_usd = total_borrow * price_usd
    collateral_usd = cash * price_usd

    market_row = MarketSnapshotRow(
        timestamp=point_ts,
        market=_to_bytes(market_address),
        symbol=ctoken_symbol,
        total_supply=total_supply,
        total_borrow=total_borrow,
        collateral_usd=collateral_usd,
        utilization=utilization,
        borrow_rate=borrow_rate,
        supply_rate=supply_rate,
        price_usd=price_usd,
        supply_usd=supply_usd,
        borrow_usd=borrow_usd,
    )
    reserve_rows = [
        ReserveSnapshotRow(
            timestamp=point_ts,
            market=_to_bytes(market_address),
            reserve=_to_bytes(underlying_address),
            symbol=underlying_symbol or ctoken_symbol,
            decimals=underlying_decimals,
            total_supply=total_supply,
            total_borrow=total_borrow,
            utilization=utilization,
            borrow_rate=borrow_rate,
            supply_rate=supply_rate,
            price_in_base=price_usd,
            price_usd=price_usd,
            supply_usd=supply_usd,
            borrow_usd=borrow_usd,
        )
    ]
    return market_row, reserve_rows


async def _safe_contract_call(fn: Any, *, default: Any = None) -> Any:
    try:
        return await fn()
    except Exception:
        return default


async def _collect_v2_protocol_config_at_block(
    w3: AsyncWeb3,
    comptroller_address: str,
    point_ts: datetime,
    block_number: int,
) -> V2ProtocolConfigVersionRow:
    comptroller = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(comptroller_address),
        abi=COMPTROLLER_V2_ABI,
    )
    (
        oracle_raw,
        close_factor_raw,
        liq_incentive_raw,
        pause_guardian_raw,
    ) = await asyncio.gather(
        _safe_contract_call(
            lambda: comptroller.functions.oracle().call(block_identifier=block_number),
            default=None,
        ),
        _safe_contract_call(
            lambda: comptroller.functions.closeFactorMantissa().call(
                block_identifier=block_number
            ),
            default=None,
        ),
        _safe_contract_call(
            lambda: comptroller.functions.liquidationIncentiveMantissa().call(
                block_identifier=block_number
            ),
            default=None,
        ),
        _safe_contract_call(
            lambda: comptroller.functions.pauseGuardian().call(
                block_identifier=block_number
            ),
            default=None,
        ),
    )
    transfer_paused, seize_paused = await asyncio.gather(
        _safe_contract_call(
            lambda: comptroller.functions.transferGuardianPaused().call(
                block_identifier=block_number
            ),
            default=False,
        ),
        _safe_contract_call(
            lambda: comptroller.functions.seizeGuardianPaused().call(
                block_identifier=block_number
            ),
            default=False,
        ),
    )
    close_factor = (
        Decimal(int(close_factor_raw)) / COMET_FACTOR_SCALE
        if close_factor_raw is not None
        else None
    )
    liq_incentive = (
        Decimal(int(liq_incentive_raw)) / COMET_FACTOR_SCALE
        if liq_incentive_raw is not None
        else None
    )

    payload = {
        "comptroller": _normalize_address_text(comptroller_address),
        "price_oracle": _normalize_address_text(str(oracle_raw))
        if oracle_raw
        else None,
        "close_factor": str(close_factor) if close_factor is not None else None,
        "liquidation_incentive": (
            str(liq_incentive) if liq_incentive is not None else None
        ),
        "pause_guardian": (
            _normalize_address_text(str(pause_guardian_raw))
            if pause_guardian_raw
            else None
        ),
        "transfer_paused": bool(transfer_paused),
        "seize_paused": bool(seize_paused),
    }
    return V2ProtocolConfigVersionRow(
        effective_timestamp=point_ts,
        block_number=block_number,
        config_hash=_governance_config_hash(payload),
        comptroller=_to_bytes(comptroller_address),
        price_oracle=(
            _optional_to_bytes(str(oracle_raw)) if oracle_raw is not None else None
        ),
        close_factor=close_factor,
        liquidation_incentive=liq_incentive,
        pause_guardian=(
            _optional_to_bytes(str(pause_guardian_raw))
            if pause_guardian_raw is not None
            else None
        ),
        transfer_paused=bool(transfer_paused),
        seize_paused=bool(seize_paused),
        mint_paused=False,
        borrow_paused=False,
        raw_config_jsonb=payload,
    )


async def _collect_v2_market_config_at_block(
    w3: AsyncWeb3,
    protocol: str,
    market_address: str,
    point_ts: datetime,
    block_number: int,
    metadata_cache: dict[str, tuple[str | None, int | None]],
) -> tuple[V2MarketConfigVersionRow, V2ProtocolConfigVersionRow]:
    ctoken = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(market_address),
        abi=CTOKEN_V2_ABI,
    )
    (
        symbol_raw,
        comptroller_raw,
        reserve_factor_raw,
        interest_rate_model_raw,
        ctoken_decimals_raw,
    ) = await asyncio.gather(
        _safe_contract_call(
            lambda: ctoken.functions.symbol().call(block_identifier=block_number),
            default=_resolve_market_name(protocol, market_address),
        ),
        ctoken.functions.comptroller().call(block_identifier=block_number),
        _safe_contract_call(
            lambda: ctoken.functions.reserveFactorMantissa().call(
                block_identifier=block_number
            ),
            default=None,
        ),
        _safe_contract_call(
            lambda: ctoken.functions.interestRateModel().call(
                block_identifier=block_number
            ),
            default=None,
        ),
        _safe_contract_call(
            lambda: ctoken.functions.decimals().call(block_identifier=block_number),
            default=None,
        ),
    )
    comptroller_address = str(comptroller_raw)
    comptroller = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(comptroller_address),
        abi=COMPTROLLER_V2_ABI,
    )

    try:
        underlying_address = str(
            await ctoken.functions.underlying().call(block_identifier=block_number)
        )
        underlying_symbol, underlying_decimals_meta = await _token_metadata(
            w3, underlying_address, block_number, metadata_cache
        )
        underlying_decimals = int(underlying_decimals_meta or 18)
    except Exception:
        underlying_address = WETH_MAINNET
        underlying_symbol = "ETH"
        underlying_decimals = 18

    markets_raw = await _safe_contract_call(
        lambda: comptroller.functions.markets(
            AsyncWeb3.to_checksum_address(market_address)
        ).call(block_identifier=block_number),
        default=(False, 0, False),
    )
    is_listed = bool(markets_raw[0])
    collateral_factor = Decimal(int(markets_raw[1])) / COMET_FACTOR_SCALE
    is_comped = bool(markets_raw[2])
    reserve_factor = (
        Decimal(int(reserve_factor_raw)) / COMET_FACTOR_SCALE
        if reserve_factor_raw is not None
        else None
    )

    (
        borrow_cap_raw,
        supply_cap_raw,
        is_deprecated_raw,
        mint_paused_raw,
        borrow_paused_raw,
    ) = await asyncio.gather(
        _safe_contract_call(
            lambda: comptroller.functions.borrowCaps(
                AsyncWeb3.to_checksum_address(market_address)
            ).call(block_identifier=block_number),
            default=None,
        ),
        _safe_contract_call(
            lambda: comptroller.functions.supplyCaps(
                AsyncWeb3.to_checksum_address(market_address)
            ).call(block_identifier=block_number),
            default=None,
        ),
        _safe_contract_call(
            lambda: comptroller.functions.isDeprecated(
                AsyncWeb3.to_checksum_address(market_address)
            ).call(block_identifier=block_number),
            default=False,
        ),
        _safe_contract_call(
            lambda: comptroller.functions.mintGuardianPaused(
                AsyncWeb3.to_checksum_address(market_address)
            ).call(block_identifier=block_number),
            default=False,
        ),
        _safe_contract_call(
            lambda: comptroller.functions.borrowGuardianPaused(
                AsyncWeb3.to_checksum_address(market_address)
            ).call(block_identifier=block_number),
            default=False,
        ),
    )
    cap_scale = Decimal(10) ** underlying_decimals
    borrow_cap = (
        Decimal(int(borrow_cap_raw)) / cap_scale if borrow_cap_raw is not None else None
    )
    supply_cap = (
        Decimal(int(supply_cap_raw)) / cap_scale if supply_cap_raw is not None else None
    )

    protocol_row = await _collect_v2_protocol_config_at_block(
        w3,
        comptroller_address=comptroller_address,
        point_ts=point_ts,
        block_number=block_number,
    )
    protocol_payload = dict(protocol_row.raw_config_jsonb)
    protocol_payload["mint_paused"] = bool(mint_paused_raw)
    protocol_payload["borrow_paused"] = bool(borrow_paused_raw)
    protocol_row.mint_paused = bool(mint_paused_raw)
    protocol_row.borrow_paused = bool(borrow_paused_raw)
    protocol_row.config_hash = _governance_config_hash(protocol_payload)
    protocol_row.raw_config_jsonb = protocol_payload

    market_symbol = str(symbol_raw) if symbol_raw is not None else None
    market_payload = {
        "market": _normalize_address_text(market_address),
        "symbol": market_symbol,
        "comptroller": _normalize_address_text(comptroller_address),
        "interest_rate_model": (
            _normalize_address_text(str(interest_rate_model_raw))
            if interest_rate_model_raw is not None
            else None
        ),
        "underlying": _normalize_address_text(underlying_address),
        "underlying_symbol": underlying_symbol,
        "ctoken_decimals": int(ctoken_decimals_raw) if ctoken_decimals_raw else None,
        "underlying_decimals": underlying_decimals,
        "collateral_factor": str(collateral_factor),
        "reserve_factor": str(reserve_factor) if reserve_factor is not None else None,
        "borrow_cap": str(borrow_cap) if borrow_cap is not None else None,
        "supply_cap": str(supply_cap) if supply_cap is not None else None,
        "is_listed": is_listed,
        "is_comped": is_comped,
        "is_deprecated": bool(is_deprecated_raw),
        "mint_paused": bool(mint_paused_raw),
        "borrow_paused": bool(borrow_paused_raw),
        "protocol_config_hash": protocol_row.config_hash,
    }
    market_row = V2MarketConfigVersionRow(
        market=_to_bytes(market_address),
        symbol=market_symbol,
        effective_timestamp=point_ts,
        block_number=block_number,
        config_hash=_governance_config_hash(market_payload),
        comptroller=_optional_to_bytes(comptroller_address),
        interest_rate_model=(
            _optional_to_bytes(str(interest_rate_model_raw))
            if interest_rate_model_raw is not None
            else None
        ),
        underlying=_optional_to_bytes(underlying_address),
        underlying_symbol=underlying_symbol,
        ctoken_decimals=int(ctoken_decimals_raw) if ctoken_decimals_raw else None,
        underlying_decimals=underlying_decimals,
        collateral_factor=collateral_factor,
        reserve_factor=reserve_factor,
        liquidation_threshold=None,
        borrow_cap=borrow_cap,
        supply_cap=supply_cap,
        is_listed=is_listed,
        is_comped=is_comped,
        is_deprecated=bool(is_deprecated_raw),
        raw_config_jsonb=market_payload,
    )
    return market_row, protocol_row


async def _collect_v3_governance_rows_at_block(
    w3: AsyncWeb3,
    market_address: str,
    point_ts: datetime,
    block_number: int,
    metadata_cache: dict[str, tuple[str | None, int | None]],
) -> tuple[
    MarketConfigVersionRow | None, list[MarketConfigAssetRow], MarketStatusSnapshotRow
]:
    market_checksum = AsyncWeb3.to_checksum_address(market_address)
    market_symbol = _resolve_market_name("v3", market_address)
    comet = w3.eth.contract(address=market_checksum, abi=COMET_ABI)

    totals_basic_raw, base_scale_raw = await asyncio.gather(
        comet.functions.totalsBasic().call(block_identifier=block_number),
        comet.functions.baseScale().call(block_identifier=block_number),
    )
    base_scale = int(base_scale_raw)
    base_decimals = _scale_to_decimals(base_scale)
    status_row = MarketStatusSnapshotRow(
        timestamp=point_ts,
        block_number=block_number,
        market=_to_bytes(market_address),
        symbol=market_symbol,
        pause_flags=int(totals_basic_raw[7]),
        base_supply_index=_scale_factor(totals_basic_raw[0]),
        base_borrow_index=_scale_factor(totals_basic_raw[1]),
        tracking_supply_index=_scale_factor(totals_basic_raw[2]),
        tracking_borrow_index=_scale_factor(totals_basic_raw[3]),
        total_supply_base=Decimal(int(totals_basic_raw[4])) / Decimal(base_scale),
        total_borrow_base=Decimal(int(totals_basic_raw[5])) / Decimal(base_scale),
        last_accrual_time=int(totals_basic_raw[6]),
        raw_status_jsonb={
            "base_supply_index_raw": str(int(totals_basic_raw[0])),
            "base_borrow_index_raw": str(int(totals_basic_raw[1])),
            "tracking_supply_index_raw": str(int(totals_basic_raw[2])),
            "tracking_borrow_index_raw": str(int(totals_basic_raw[3])),
            "total_supply_base_raw": str(int(totals_basic_raw[4])),
            "total_borrow_base_raw": str(int(totals_basic_raw[5])),
            "last_accrual_time": int(totals_basic_raw[6]),
            "pause_flags": int(totals_basic_raw[7]),
        },
    )

    (
        governor_raw,
        pause_guardian_raw,
        base_token_raw,
        base_token_price_feed_raw,
        extension_delegate_raw,
        supply_kink_raw,
        supply_slope_low_raw,
        supply_slope_high_raw,
        supply_base_raw,
        borrow_kink_raw,
        borrow_slope_low_raw,
        borrow_slope_high_raw,
        borrow_base_raw,
        store_front_price_factor_raw,
        tracking_index_scale_raw,
        base_tracking_supply_speed_raw,
        base_tracking_borrow_speed_raw,
        base_min_for_rewards_raw,
        base_borrow_min_raw,
        target_reserves_raw,
        num_assets_raw,
    ) = await asyncio.gather(
        comet.functions.governor().call(block_identifier=block_number),
        comet.functions.pauseGuardian().call(block_identifier=block_number),
        comet.functions.baseToken().call(block_identifier=block_number),
        comet.functions.baseTokenPriceFeed().call(block_identifier=block_number),
        comet.functions.extensionDelegate().call(block_identifier=block_number),
        comet.functions.supplyKink().call(block_identifier=block_number),
        comet.functions.supplyPerSecondInterestRateSlopeLow().call(
            block_identifier=block_number
        ),
        comet.functions.supplyPerSecondInterestRateSlopeHigh().call(
            block_identifier=block_number
        ),
        comet.functions.supplyPerSecondInterestRateBase().call(
            block_identifier=block_number
        ),
        comet.functions.borrowKink().call(block_identifier=block_number),
        comet.functions.borrowPerSecondInterestRateSlopeLow().call(
            block_identifier=block_number
        ),
        comet.functions.borrowPerSecondInterestRateSlopeHigh().call(
            block_identifier=block_number
        ),
        comet.functions.borrowPerSecondInterestRateBase().call(
            block_identifier=block_number
        ),
        comet.functions.storeFrontPriceFactor().call(block_identifier=block_number),
        comet.functions.trackingIndexScale().call(block_identifier=block_number),
        comet.functions.baseTrackingSupplySpeed().call(block_identifier=block_number),
        comet.functions.baseTrackingBorrowSpeed().call(block_identifier=block_number),
        comet.functions.baseMinForRewards().call(block_identifier=block_number),
        comet.functions.baseBorrowMin().call(block_identifier=block_number),
        comet.functions.targetReserves().call(block_identifier=block_number),
        comet.functions.numAssets().call(block_identifier=block_number),
    )

    asset_infos = await asyncio.gather(
        *(
            comet.functions.getAssetInfo(i).call(block_identifier=block_number)
            for i in range(int(num_assets_raw))
        )
    )

    base_token = str(base_token_raw)
    base_token_symbol, _ = await _token_metadata(
        w3, base_token, block_number, metadata_cache
    )

    asset_payloads: list[dict[str, Any]] = []
    asset_rows: list[MarketConfigAssetRow] = []
    for asset_cfg in asset_infos:
        asset_address = str(asset_cfg[1])
        asset_symbol, asset_decimals_meta = await _token_metadata(
            w3, asset_address, block_number, metadata_cache
        )
        decimals = (
            int(asset_decimals_meta)
            if asset_decimals_meta is not None
            else _scale_to_decimals(int(asset_cfg[3]))
        )
        asset_payload = {
            "asset": _normalize_address_text(asset_address),
            "symbol": asset_symbol,
            "price_feed": _normalize_address_text(str(asset_cfg[2])),
            "decimals": decimals,
            "borrow_collateral_factor": str(_scale_factor(asset_cfg[4])),
            "liquidate_collateral_factor": str(_scale_factor(asset_cfg[5])),
            "liquidation_factor": str(_scale_factor(asset_cfg[6])),
            "supply_cap": str(
                Decimal(int(asset_cfg[7])) / (Decimal(10) ** max(0, decimals))
            ),
        }
        asset_payloads.append(asset_payload)

    config_payload = {
        "source": "comet",
        "configurator": None,
        "factory": None,
        "governor": _normalize_address_text(str(governor_raw)),
        "pause_guardian": _normalize_address_text(str(pause_guardian_raw)),
        "base_token": _normalize_address_text(base_token),
        "base_token_symbol": base_token_symbol,
        "base_token_price_feed": _normalize_address_text(
            str(base_token_price_feed_raw)
        ),
        "extension_delegate": _normalize_address_text(str(extension_delegate_raw)),
        "base_scale": str(base_scale),
        "base_decimals": base_decimals,
        "supply_kink": str(_scale_factor(supply_kink_raw)),
        "supply_per_second_interest_rate_slope_low": str(
            _scale_factor(supply_slope_low_raw)
        ),
        "supply_per_second_interest_rate_slope_high": str(
            _scale_factor(supply_slope_high_raw)
        ),
        "supply_per_second_interest_rate_base": str(_scale_factor(supply_base_raw)),
        "supply_per_year_interest_rate_slope_low": str(
            _annualize_factor(supply_slope_low_raw)
        ),
        "supply_per_year_interest_rate_slope_high": str(
            _annualize_factor(supply_slope_high_raw)
        ),
        "supply_per_year_interest_rate_base": str(_annualize_factor(supply_base_raw)),
        "borrow_kink": str(_scale_factor(borrow_kink_raw)),
        "borrow_per_second_interest_rate_slope_low": str(
            _scale_factor(borrow_slope_low_raw)
        ),
        "borrow_per_second_interest_rate_slope_high": str(
            _scale_factor(borrow_slope_high_raw)
        ),
        "borrow_per_second_interest_rate_base": str(_scale_factor(borrow_base_raw)),
        "borrow_per_year_interest_rate_slope_low": str(
            _annualize_factor(borrow_slope_low_raw)
        ),
        "borrow_per_year_interest_rate_slope_high": str(
            _annualize_factor(borrow_slope_high_raw)
        ),
        "borrow_per_year_interest_rate_base": str(_annualize_factor(borrow_base_raw)),
        "store_front_price_factor": str(_scale_factor(store_front_price_factor_raw)),
        "tracking_index_scale": str(_scale_factor(tracking_index_scale_raw)),
        "base_tracking_supply_speed": str(
            _scale_factor(base_tracking_supply_speed_raw)
        ),
        "base_tracking_borrow_speed": str(
            _scale_factor(base_tracking_borrow_speed_raw)
        ),
        "base_min_for_rewards": str(
            Decimal(int(base_min_for_rewards_raw))
            / (Decimal(10) ** max(0, base_decimals))
        ),
        "base_borrow_min": str(
            Decimal(int(base_borrow_min_raw)) / (Decimal(10) ** max(0, base_decimals))
        ),
        "target_reserves": str(
            Decimal(int(target_reserves_raw)) / (Decimal(10) ** max(0, base_decimals))
        ),
        "asset_configs": asset_payloads,
    }
    config_hash = _governance_config_hash(config_payload)

    for asset_cfg, asset_payload in zip(asset_infos, asset_payloads):
        asset_rows.append(
            MarketConfigAssetRow(
                market=_to_bytes(market_address),
                config_hash=config_hash,
                asset=_to_bytes(str(asset_cfg[1])),
                symbol=asset_payload["symbol"],
                price_feed=_optional_to_bytes(str(asset_cfg[2])),
                decimals=int(asset_payload["decimals"]),
                borrow_collateral_factor=Decimal(
                    asset_payload["borrow_collateral_factor"]
                ),
                liquidate_collateral_factor=Decimal(
                    asset_payload["liquidate_collateral_factor"]
                ),
                liquidation_factor=Decimal(asset_payload["liquidation_factor"]),
                supply_cap=Decimal(asset_payload["supply_cap"]),
                raw_config_jsonb=asset_payload,
            )
        )

    config_row = MarketConfigVersionRow(
        market=_to_bytes(market_address),
        symbol=market_symbol,
        effective_timestamp=point_ts,
        block_number=block_number,
        config_hash=config_hash,
        configurator=None,
        factory=None,
        governor=_optional_to_bytes(str(governor_raw)),
        pause_guardian=_optional_to_bytes(str(pause_guardian_raw)),
        base_token=_to_bytes(base_token),
        base_token_symbol=base_token_symbol,
        base_token_price_feed=_optional_to_bytes(str(base_token_price_feed_raw)),
        extension_delegate=_optional_to_bytes(str(extension_delegate_raw)),
        base_scale=base_scale,
        base_decimals=base_decimals,
        supply_kink=Decimal(config_payload["supply_kink"]),
        supply_per_year_interest_rate_slope_low=Decimal(
            config_payload["supply_per_year_interest_rate_slope_low"]
        ),
        supply_per_year_interest_rate_slope_high=Decimal(
            config_payload["supply_per_year_interest_rate_slope_high"]
        ),
        supply_per_year_interest_rate_base=Decimal(
            config_payload["supply_per_year_interest_rate_base"]
        ),
        borrow_kink=Decimal(config_payload["borrow_kink"]),
        borrow_per_year_interest_rate_slope_low=Decimal(
            config_payload["borrow_per_year_interest_rate_slope_low"]
        ),
        borrow_per_year_interest_rate_slope_high=Decimal(
            config_payload["borrow_per_year_interest_rate_slope_high"]
        ),
        borrow_per_year_interest_rate_base=Decimal(
            config_payload["borrow_per_year_interest_rate_base"]
        ),
        store_front_price_factor=Decimal(config_payload["store_front_price_factor"]),
        tracking_index_scale=Decimal(config_payload["tracking_index_scale"]),
        base_tracking_supply_speed=Decimal(
            config_payload["base_tracking_supply_speed"]
        ),
        base_tracking_borrow_speed=Decimal(
            config_payload["base_tracking_borrow_speed"]
        ),
        base_min_for_rewards=Decimal(config_payload["base_min_for_rewards"]),
        base_borrow_min=Decimal(config_payload["base_borrow_min"]),
        target_reserves=Decimal(config_payload["target_reserves"]),
        raw_config_jsonb=config_payload,
    )
    return config_row, asset_rows, status_row


async def _collect_v3_market_at_block(
    w3: AsyncWeb3,
    protocol: str,
    market_address: str,
    point_ts: datetime,
    block_number: int,
    metadata_cache: dict[str, tuple[str | None, int | None]],
) -> tuple[MarketSnapshotRow, list[ReserveSnapshotRow]]:
    comet = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(market_address),
        abi=COMET_ABI,
    )

    market_symbol = _resolve_market_name(protocol, market_address)

    (
        base_scale,
        base_token,
        base_token_feed,
        total_supply_raw,
        total_borrow_raw,
        utilization_raw,
        num_assets,
    ) = await asyncio.gather(
        comet.functions.baseScale().call(block_identifier=block_number),
        comet.functions.baseToken().call(block_identifier=block_number),
        comet.functions.baseTokenPriceFeed().call(block_identifier=block_number),
        comet.functions.totalSupply().call(block_identifier=block_number),
        comet.functions.totalBorrow().call(block_identifier=block_number),
        comet.functions.getUtilization().call(block_identifier=block_number),
        comet.functions.numAssets().call(block_identifier=block_number),
    )

    supply_rate_raw, borrow_rate_raw = await asyncio.gather(
        comet.functions.getSupplyRate(utilization_raw).call(
            block_identifier=block_number
        ),
        comet.functions.getBorrowRate(utilization_raw).call(
            block_identifier=block_number
        ),
    )

    base_price_usd = await _base_token_usd_price(
        w3, comet, base_token, base_token_feed, block_number
    )
    base_symbol, base_decimals_meta = await _token_metadata(
        w3, base_token, block_number, metadata_cache
    )

    base_scale_dec = Decimal(int(base_scale))
    total_supply = Decimal(int(total_supply_raw)) / base_scale_dec
    total_borrow = Decimal(int(total_borrow_raw)) / base_scale_dec
    utilization = Decimal(int(utilization_raw)) / Decimal(10**18)
    supply_rate = Decimal(int(supply_rate_raw)) / Decimal(10**18)
    borrow_rate = Decimal(int(borrow_rate_raw)) / Decimal(10**18)
    supply_usd = total_supply * base_price_usd
    borrow_usd = total_borrow * base_price_usd
    collateral_usd = Decimal("0")

    market_row = MarketSnapshotRow(
        timestamp=point_ts,
        market=_to_bytes(market_address),
        symbol=market_symbol,
        total_supply=total_supply,
        total_borrow=total_borrow,
        collateral_usd=collateral_usd,
        utilization=utilization,
        borrow_rate=borrow_rate,
        supply_rate=supply_rate,
        price_usd=base_price_usd,
        supply_usd=supply_usd,
        borrow_usd=borrow_usd,
    )

    reserve_rows: list[ReserveSnapshotRow] = [
        ReserveSnapshotRow(
            timestamp=point_ts,
            market=_to_bytes(market_address),
            reserve=_to_bytes(base_token),
            symbol=base_symbol or market_symbol,
            decimals=(
                base_decimals_meta
                if base_decimals_meta is not None
                else _scale_to_decimals(int(base_scale))
            ),
            total_supply=total_supply,
            total_borrow=total_borrow,
            utilization=utilization,
            borrow_rate=borrow_rate,
            supply_rate=supply_rate,
            price_in_base=ONE,
            price_usd=base_price_usd,
            supply_usd=supply_usd,
            borrow_usd=borrow_usd,
        )
    ]

    for i in range(int(num_assets)):
        try:
            asset_info = await comet.functions.getAssetInfo(i).call(
                block_identifier=block_number
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch v3 asset info i=%s market=%s block=%s: %s",
                i,
                market_address,
                block_number,
                exc,
            )
            continue

        # tuple: (offset, asset, priceFeed, scale, ...)
        asset_address = asset_info[1]
        asset_price_feed = asset_info[2]
        asset_scale = int(asset_info[3])

        asset_symbol, asset_decimals_meta = await _token_metadata(
            w3, asset_address, block_number, metadata_cache
        )

        try:
            totals_collateral = await comet.functions.totalsCollateral(
                AsyncWeb3.to_checksum_address(asset_address)
            ).call(block_identifier=block_number)
            total_supply_asset_raw = int(totals_collateral[0])
            asset_price_in_base = await _price_from_oracle(
                w3, comet, asset_price_feed, block_number
            )
        except Exception as exc:
            logger.warning(
                "Failed to price v3 collateral asset i=%s asset=%s feed=%s market=%s block=%s: %s",
                i,
                asset_address,
                asset_price_feed,
                market_address,
                block_number,
                exc,
            )
            continue

        asset_supply = Decimal(total_supply_asset_raw) / Decimal(asset_scale)
        asset_price_usd = asset_price_in_base * base_price_usd
        asset_supply_usd = asset_supply * asset_price_usd
        collateral_usd += asset_supply_usd

        reserve_rows.append(
            ReserveSnapshotRow(
                timestamp=point_ts,
                market=_to_bytes(market_address),
                reserve=_to_bytes(asset_address),
                symbol=asset_symbol,
                decimals=(
                    asset_decimals_meta
                    if asset_decimals_meta is not None
                    else _scale_to_decimals(asset_scale)
                ),
                total_supply=asset_supply,
                total_borrow=Decimal("0"),
                utilization=Decimal("0"),
                borrow_rate=Decimal("0"),
                supply_rate=Decimal("0"),
                price_in_base=asset_price_in_base,
                price_usd=asset_price_usd,
                supply_usd=asset_supply_usd,
                borrow_usd=Decimal("0"),
            )
        )

    market_row.collateral_usd = collateral_usd
    return market_row, reserve_rows


async def _collect_v3_markets_at_block(
    cfg: AppConfig,
    w3: AsyncWeb3,
    point_ts: datetime,
    block_number: int,
    markets: Sequence[str],
    metadata_cache: dict[str, tuple[str | None, int | None]],
    deployment_cache: dict[str, dict[str, int]],
) -> tuple[
    list[MarketSnapshotRow],
    list[ReserveSnapshotRow],
    list[MarketConfigVersionRow],
    list[MarketConfigAssetRow],
    list[MarketStatusSnapshotRow],
]:
    sem = asyncio.Semaphore(max(1, cfg.crawler.concurrency))

    async def _one_market(
        market: str,
    ) -> tuple[
        MarketSnapshotRow | None,
        list[ReserveSnapshotRow],
        MarketConfigVersionRow | None,
        list[MarketConfigAssetRow],
        MarketStatusSnapshotRow | None,
    ]:
        async with sem:
            try:
                if market.startswith("0x") and not await _is_contract_deployed_at_block(
                    w3, market, block_number, deployment_cache
                ):
                    logger.info(
                        "Skip undeployed v3 market=%s ts=%s block=%s",
                        market,
                        point_ts.isoformat(),
                        block_number,
                    )
                    return None, [], None, [], None

                market_row, reserve_rows = await _collect_v3_market_at_block(
                    w3,
                    protocol=cfg.protocol,
                    market_address=market,
                    point_ts=point_ts,
                    block_number=block_number,
                    metadata_cache=metadata_cache,
                )
                (
                    config_row,
                    config_asset_rows,
                    status_row,
                ) = await _collect_v3_governance_rows_at_block(
                    w3,
                    market_address=market,
                    point_ts=point_ts,
                    block_number=block_number,
                    metadata_cache=metadata_cache,
                )
                return (
                    market_row,
                    reserve_rows,
                    config_row,
                    config_asset_rows,
                    status_row,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to collect v3 market=%s ts=%s block=%s: %s",
                    market,
                    point_ts.isoformat(),
                    block_number,
                    exc,
                )
                return None, [], None, [], None

    results = await asyncio.gather(*(_one_market(market) for market in markets))
    market_rows: list[MarketSnapshotRow] = []
    reserve_rows: list[ReserveSnapshotRow] = []
    config_rows: list[MarketConfigVersionRow] = []
    config_asset_rows: list[MarketConfigAssetRow] = []
    status_rows: list[MarketStatusSnapshotRow] = []
    for market_row, rows, config_row, asset_rows, status_row in results:
        if market_row is not None:
            market_rows.append(market_row)
            reserve_rows.extend(rows)
        if config_row is not None:
            config_rows.append(config_row)
            config_asset_rows.extend(asset_rows)
        if status_row is not None:
            status_rows.append(status_row)
    return market_rows, reserve_rows, config_rows, config_asset_rows, status_rows


async def _collect_v2_markets_at_block(
    cfg: AppConfig,
    w3: AsyncWeb3,
    point_ts: datetime,
    block_number: int,
    markets: Sequence[str],
    metadata_cache: dict[str, tuple[str | None, int | None]],
    deployment_cache: dict[str, dict[str, int]],
) -> tuple[list[MarketSnapshotRow], list[ReserveSnapshotRow]]:
    sem = asyncio.Semaphore(max(1, cfg.crawler.concurrency))

    async def _one_market(
        market: str,
    ) -> tuple[MarketSnapshotRow | None, list[ReserveSnapshotRow]]:
        async with sem:
            try:
                if market.startswith("0x") and not await _is_contract_deployed_at_block(
                    w3, market, block_number, deployment_cache
                ):
                    logger.info(
                        "Skip undeployed v2 market=%s ts=%s block=%s",
                        market,
                        point_ts.isoformat(),
                        block_number,
                    )
                    return None, []

                market_row, reserve_rows = await _collect_v2_market_at_block(
                    w3,
                    protocol=cfg.protocol,
                    market_address=market,
                    point_ts=point_ts,
                    block_number=block_number,
                    metadata_cache=metadata_cache,
                )
                return market_row, reserve_rows
            except Exception as exc:
                logger.warning(
                    "Failed to collect v2 market=%s ts=%s block=%s: %s",
                    market,
                    point_ts.isoformat(),
                    block_number,
                    exc,
                )
                return None, []

    results = await asyncio.gather(*(_one_market(market) for market in markets))
    market_rows: list[MarketSnapshotRow] = []
    reserve_rows: list[ReserveSnapshotRow] = []
    for market_row, rows in results:
        if market_row is not None:
            market_rows.append(market_row)
            reserve_rows.extend(rows)
    return market_rows, reserve_rows


async def _collect_v2_market_configs_at_block(
    cfg: AppConfig,
    w3: AsyncWeb3,
    point_ts: datetime,
    block_number: int,
    markets: Sequence[str],
    metadata_cache: dict[str, tuple[str | None, int | None]],
    deployment_cache: dict[str, dict[str, int]],
) -> tuple[list[V2MarketConfigVersionRow], list[V2ProtocolConfigVersionRow]]:
    sem = asyncio.Semaphore(max(1, cfg.crawler.concurrency))

    async def _one_market(
        market: str,
    ) -> tuple[V2MarketConfigVersionRow | None, V2ProtocolConfigVersionRow | None]:
        async with sem:
            try:
                if market.startswith("0x") and not await _is_contract_deployed_at_block(
                    w3, market, block_number, deployment_cache
                ):
                    logger.info(
                        "Skip undeployed v2 market config market=%s ts=%s block=%s",
                        market,
                        point_ts.isoformat(),
                        block_number,
                    )
                    return None, None
                return await _collect_v2_market_config_at_block(
                    w3,
                    protocol=cfg.protocol,
                    market_address=market,
                    point_ts=point_ts,
                    block_number=block_number,
                    metadata_cache=metadata_cache,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to collect v2 market config market=%s ts=%s block=%s: %s",
                    market,
                    point_ts.isoformat(),
                    block_number,
                    exc,
                )
                return None, None

    results = await asyncio.gather(*(_one_market(market) for market in markets))
    market_rows: list[V2MarketConfigVersionRow] = []
    protocol_rows_by_hash: dict[str, V2ProtocolConfigVersionRow] = {}
    for market_row, protocol_row in results:
        if market_row is not None:
            market_rows.append(market_row)
        if protocol_row is not None:
            protocol_rows_by_hash[protocol_row.config_hash] = protocol_row
    return market_rows, list(protocol_rows_by_hash.values())


async def _filter_pending_markets(
    cfg: AppConfig,
    pool: asyncpg.Pool,
    protocol: str,
    point_ts: datetime,
    markets: Sequence[str],
    include_market_state: bool,
    include_governance: bool,
) -> tuple[list[str], int]:
    if not markets:
        return [], 0

    market_table = market_table_name(protocol)
    market_keys = [_to_bytes(market) for market in markets if market.startswith("0x")]
    if not market_keys:
        return list(markets), 0

    async with pool.acquire() as conn:
        existing_rows = await conn.fetch(
            f"""
            SELECT market
            FROM loan.{market_table}
            WHERE "timestamp" = $1
              AND market = ANY($2::bytea[])
            """,
            point_ts,
            market_keys,
        )
    existing_market_set = {row["market"] for row in existing_rows}
    existing_status_set: set[bytes] = set()
    existing_config_set: set[bytes] = set()
    if protocol == "v3":
        (
            existing_status_set,
            existing_config_set,
        ) = await fetch_existing_governance_markets(
            pool,
            point_ts,
            market_keys,
        )

    pending: list[str] = []
    skipped = 0
    for market in markets:
        if market.startswith("0x"):
            market_key = _to_bytes(market)
            has_market = not include_market_state or market_key in existing_market_set
            has_status = (
                not include_governance
                or protocol != "v3"
                or market_key in existing_status_set
            )
            has_config = (
                not include_governance
                or protocol != "v3"
                or market_key in existing_config_set
            )
            if has_market and has_status and has_config:
                skipped += 1
                continue
        pending.append(market)
    return pending, skipped


async def _collect_rows_for_point(
    cfg: AppConfig,
    w3: AsyncWeb3 | None,
    point_ts: datetime,
    markets: Sequence[str],
    pool,
    metadata_cache: dict[str, tuple[str | None, int | None]],
    deployment_cache: dict[str, dict[str, int]],
    include_market_state: bool,
    include_governance: bool,
) -> tuple[
    list[MarketSnapshotRow],
    list[ReserveSnapshotRow],
    list[MarketConfigVersionRow],
    list[MarketConfigAssetRow],
    list[MarketStatusSnapshotRow],
]:
    if w3 is None:
        if include_market_state:
            market_rows, reserve_rows = _build_rows_for_point(point_ts, list(markets))
            return market_rows, reserve_rows, [], [], []
        return [], [], [], [], []

    if cfg.protocol == "v2":
        if not include_market_state:
            return [], [], [], [], []
        market_rows, reserve_rows = await _collect_v2_markets_at_block(
            cfg,
            w3,
            point_ts=point_ts,
            block_number=await _block_at_timestamp(
                w3, int(point_ts.timestamp()), pool=pool
            ),
            markets=markets,
            metadata_cache=metadata_cache,
            deployment_cache=deployment_cache,
        )
        return market_rows, reserve_rows, [], [], []

    block_number = await _block_at_timestamp(w3, int(point_ts.timestamp()), pool=pool)
    if include_market_state and include_governance:
        return await _collect_v3_markets_at_block(
            cfg,
            w3,
            point_ts=point_ts,
            block_number=block_number,
            markets=markets,
            metadata_cache=metadata_cache,
            deployment_cache=deployment_cache,
        )

    market_rows: list[MarketSnapshotRow] = []
    reserve_rows: list[ReserveSnapshotRow] = []
    config_rows: list[MarketConfigVersionRow] = []
    config_asset_rows: list[MarketConfigAssetRow] = []
    status_rows: list[MarketStatusSnapshotRow] = []

    sem = asyncio.Semaphore(max(1, cfg.crawler.concurrency))

    async def _one_market(
        market: str,
    ) -> tuple[
        MarketSnapshotRow | None,
        list[ReserveSnapshotRow],
        MarketConfigVersionRow | None,
        list[MarketConfigAssetRow],
        MarketStatusSnapshotRow | None,
    ]:
        async with sem:
            if market.startswith("0x") and not await _is_contract_deployed_at_block(
                w3, market, block_number, deployment_cache
            ):
                logger.info(
                    "Skip undeployed v3 market=%s ts=%s block=%s",
                    market,
                    point_ts.isoformat(),
                    block_number,
                )
                return None, [], None, [], None

            if include_market_state:
                market_row, reserve_rows_local = await _collect_v3_market_at_block(
                    w3,
                    protocol=cfg.protocol,
                    market_address=market,
                    point_ts=point_ts,
                    block_number=block_number,
                    metadata_cache=metadata_cache,
                )
            else:
                market_row = None
                reserve_rows_local = []

            if include_governance:
                (
                    config_row,
                    config_asset_rows_local,
                    status_row,
                ) = await _collect_v3_governance_rows_at_block(
                    w3,
                    market_address=market,
                    point_ts=point_ts,
                    block_number=block_number,
                    metadata_cache=metadata_cache,
                )
            else:
                config_row = None
                config_asset_rows_local = []
                status_row = None

            return (
                market_row,
                reserve_rows_local,
                config_row,
                config_asset_rows_local,
                status_row,
            )

    results = await asyncio.gather(*(_one_market(market) for market in markets))
    for (
        market_row,
        reserve_rows_local,
        config_row,
        config_asset_rows_local,
        status_row,
    ) in results:
        if market_row is not None:
            market_rows.append(market_row)
            reserve_rows.extend(reserve_rows_local)
        if config_row is not None:
            config_rows.append(config_row)
            config_asset_rows.extend(config_asset_rows_local)
        if status_row is not None:
            status_rows.append(status_row)

    return market_rows, reserve_rows, config_rows, config_asset_rows, status_rows


def _build_rows_for_point(
    ts: datetime, markets: list[str]
) -> tuple[list[MarketSnapshotRow], list[ReserveSnapshotRow]]:
    market_rows: list[MarketSnapshotRow] = []
    reserve_rows: list[ReserveSnapshotRow] = []
    zero = Decimal("0")

    for market in markets:
        market_bytes = (
            _to_bytes(market) if market.startswith("0x") else market.encode("utf-8")
        )

        market_rows.append(
            MarketSnapshotRow(
                timestamp=ts,
                market=market_bytes,
                symbol="MARKET",
                total_supply=zero,
                total_borrow=zero,
                collateral_usd=zero,
                utilization=zero,
                borrow_rate=zero,
                supply_rate=zero,
                price_usd=zero,
                supply_usd=zero,
                borrow_usd=zero,
            )
        )
        # 先写一条 reserve 明细占位记录，后续接入真实链上 reserve 清单时直接替换。
        reserve_rows.append(
            ReserveSnapshotRow(
                timestamp=ts,
                market=market_bytes,
                reserve=market_bytes,
                symbol=_resolve_market_name("v2", market),
                decimals=18,
                total_supply=zero,
                total_borrow=zero,
                utilization=zero,
                borrow_rate=zero,
                supply_rate=zero,
                price_in_base=zero,
                price_usd=zero,
                supply_usd=zero,
                borrow_usd=zero,
            )
        )
    return market_rows, reserve_rows


async def _writer_loop(
    cfg: AppConfig,
    pool: asyncpg.Pool,
    queue: asyncio.Queue[
        tuple[
            list[MarketSnapshotRow],
            list[ReserveSnapshotRow],
            list[MarketConfigVersionRow],
            list[MarketConfigAssetRow],
            list[MarketStatusSnapshotRow],
        ]
        | None
    ],
    totals: dict[str, int],
    dry_run: bool,
) -> None:
    while True:
        item = await queue.get()
        try:
            if item is None:
                return
            (
                market_rows,
                reserve_rows,
                config_rows,
                config_asset_rows,
                status_rows,
            ) = item
            if dry_run:
                totals["market"] += len(market_rows)
                totals["reserve"] += len(reserve_rows)
                totals["config"] += len(config_rows)
                totals["config_asset"] += len(config_asset_rows)
                totals["status"] += len(status_rows)
                continue

            inserted_market = await upsert_market_snapshots(
                pool, cfg.protocol, market_rows
            )
            inserted_reserve = await upsert_reserve_snapshots(
                pool, cfg.protocol, reserve_rows
            )
            inserted_config = await upsert_market_config_versions(pool, config_rows)
            inserted_config_asset = await upsert_market_config_asset_rows(
                pool, config_asset_rows
            )
            inserted_status = await upsert_market_status_snapshots(pool, status_rows)
            totals["market"] += inserted_market
            totals["reserve"] += inserted_reserve
            totals["config"] += inserted_config
            totals["config_asset"] += inserted_config_asset
            totals["status"] += inserted_status
        finally:
            queue.task_done()


async def run_crawler(
    cfg: AppConfig,
    pool,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    interval_hours: int = 1,
    skip_existing: bool = False,
    dry_run: bool = False,
    include_market_state: bool = True,
    include_governance: bool = True,
) -> None:
    await ensure_market_state_tables(
        pool,
        protocol=cfg.protocol,
        use_timescaledb=cfg.market_state.use_timescaledb,
    )

    # 默认采集当前小时；若传入区间，则按配置间隔逐点采集。
    now_utc = datetime.now(timezone.utc)
    interval = timedelta(hours=interval_hours)

    if start_at is None and end_at is None:
        start = now_utc.replace(minute=0, second=0, microsecond=0)
        end = start
    else:
        start = start_at or end_at or now_utc
        end = end_at or start_at or start
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

    if start > end:
        raise ValueError("end_at must be greater than or equal to start_at")

    points: list[datetime] = []
    cursor = start
    while cursor <= end:
        points.append(cursor)
        cursor = cursor + interval

    logger.info(
        "Compound market_state crawl invoked: protocol=%s dry_run=%s skip_existing=%s include_market_state=%s include_governance=%s start=%s end=%s interval_hours=%s points=%s",
        cfg.protocol,
        dry_run,
        skip_existing,
        include_market_state,
        include_governance,
        start.isoformat(),
        end.isoformat(),
        interval_hours,
        len(points),
    )

    markets = _market_addresses(cfg)
    totals: dict[str, int] = {
        "market": 0,
        "reserve": 0,
        "config": 0,
        "config_asset": 0,
        "status": 0,
    }
    w3: AsyncWeb3 | None = None
    if cfg.protocol in ("v2", "v3"):
        w3 = await _build_web3(cfg)

    metadata_cache: dict[str, tuple[str | None, int | None]] = {}
    deployment_cache: dict[str, dict[str, int]] = {}

    write_queue: asyncio.Queue[
        tuple[
            list[MarketSnapshotRow],
            list[ReserveSnapshotRow],
            list[MarketConfigVersionRow],
            list[MarketConfigAssetRow],
            list[MarketStatusSnapshotRow],
        ]
        | None
    ] = asyncio.Queue(maxsize=max(1, cfg.crawler.batch_size))
    writer_task = asyncio.create_task(
        _writer_loop(cfg, pool, write_queue, totals=totals, dry_run=dry_run)
    )

    point_sem = asyncio.Semaphore(max(1, min(4, cfg.crawler.concurrency // 2 or 1)))

    async def _process_point(ts: datetime) -> None:
        async with point_sem:
            logger.debug("market_state point scheduled: %s", ts.isoformat())
            point_markets = list(markets)
            if skip_existing:
                point_markets, skipped_market = await _filter_pending_markets(
                    cfg,
                    pool,
                    cfg.protocol,
                    point_ts=ts,
                    markets=point_markets,
                    include_market_state=include_market_state,
                    include_governance=include_governance,
                )
                if skipped_market:
                    logger.info(
                        "Skipped existing market snapshots before RPC at %s: market=%s",
                        ts.isoformat(),
                        skipped_market,
                    )
            if not point_markets:
                return

            (
                market_rows,
                reserve_rows,
                config_rows,
                config_asset_rows,
                status_rows,
            ) = await _collect_rows_for_point(
                cfg,
                w3,
                point_ts=ts,
                markets=point_markets,
                pool=pool,
                metadata_cache=metadata_cache,
                deployment_cache=deployment_cache,
                include_market_state=include_market_state,
                include_governance=include_governance,
            )
            if (
                not market_rows
                and not reserve_rows
                and not config_rows
                and not config_asset_rows
                and not status_rows
            ):
                return
            await write_queue.put(
                (
                    market_rows,
                    reserve_rows,
                    config_rows,
                    config_asset_rows,
                    status_rows,
                )
            )

    try:
        await asyncio.gather(*(_process_point(ts) for ts in points))
    finally:
        await write_queue.put(None)
        await write_queue.join()
        await writer_task
        await close_web3(w3)

    logger.info(
        "Compound market_state crawl done: protocol=%s dry_run=%s market_rows=%s reserve_rows=%s config_rows=%s config_asset_rows=%s status_rows=%s",
        cfg.protocol,
        dry_run,
        totals["market"],
        totals["reserve"],
        totals["config"],
        totals["config_asset"],
        totals["status"],
    )


async def run_v2_market_config_crawler(
    cfg: AppConfig,
    pool,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    interval_hours: int = 1,
    skip_existing: bool = False,
    dry_run: bool = False,
) -> None:
    if cfg.protocol != "v2":
        raise ValueError("run_v2_market_config_crawler only supports protocol=v2")
    await ensure_market_state_tables(
        pool,
        protocol="v2",
        use_timescaledb=cfg.market_state.use_timescaledb,
    )
    now_utc = datetime.now(timezone.utc)
    interval = timedelta(hours=interval_hours)
    if start_at is None and end_at is None:
        start = now_utc.replace(minute=0, second=0, microsecond=0)
        end = start
    else:
        start = start_at or end_at or now_utc
        end = end_at or start_at or start
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
    if start > end:
        raise ValueError("end_at must be greater than or equal to start_at")

    points: list[datetime] = []
    cursor = start
    while cursor <= end:
        points.append(cursor)
        cursor += interval

    markets = _market_addresses(cfg)
    w3 = await _build_web3(cfg)
    metadata_cache: dict[str, tuple[str | None, int | None]] = {}
    deployment_cache: dict[str, dict[str, int]] = {}
    total_market_config = 0
    total_protocol_config = 0

    logger.info(
        "Compound v2 market config crawl invoked: dry_run=%s skip_existing=%s start=%s end=%s interval_hours=%s points=%s",
        dry_run,
        skip_existing,
        start.isoformat(),
        end.isoformat(),
        interval_hours,
        len(points),
    )
    try:
        for point_ts in points:
            point_markets = list(markets)
            if skip_existing:
                existing = await fetch_existing_v2_config_markets(
                    pool,
                    point_ts=point_ts,
                    markets=[_to_bytes(m) for m in point_markets if m.startswith("0x")],
                )
                point_markets = [
                    m
                    for m in point_markets
                    if not m.startswith("0x") or _to_bytes(m) not in existing
                ]
                if not point_markets:
                    continue

            block_number = await _block_at_timestamp(
                w3, int(point_ts.timestamp()), pool=pool
            )
            market_rows, protocol_rows = await _collect_v2_market_configs_at_block(
                cfg,
                w3,
                point_ts=point_ts,
                block_number=block_number,
                markets=point_markets,
                metadata_cache=metadata_cache,
                deployment_cache=deployment_cache,
            )
            if dry_run:
                total_market_config += len(market_rows)
                total_protocol_config += len(protocol_rows)
                continue
            total_market_config += await upsert_v2_market_config_versions(
                pool, market_rows
            )
            total_protocol_config += await upsert_v2_protocol_config_versions(
                pool, protocol_rows
            )
    finally:
        await close_web3(w3)

    logger.info(
        "Compound v2 market config crawl done: dry_run=%s market_config_rows=%s protocol_config_rows=%s",
        dry_run,
        total_market_config,
        total_protocol_config,
    )
