"""Database helpers for Compound crawler."""

from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from datetime import datetime
from datetime import date as date_type
from decimal import Decimal
from collections import defaultdict
from typing import Any

import asyncpg
from crawler_shared.config import PostgresConfig
from crawler_shared.postgres import create_pool as create_asyncpg_pool
from sqlalchemy import inspect

from .orm_models import Base, CompoundV3UserPosition

logger = logging.getLogger(__name__)


_MARKET_TABLES = {
    "v2": "compound_v2_market_snapshots",
    "v3": "compound_v3_market_snapshots",
}

_RESERVE_TABLES = {
    "v2": "compound_v2_market_snapshot_reserves",
    "v3": "compound_v3_market_snapshot_reserves",
}


@dataclass
class MarketSnapshotRow:
    timestamp: datetime
    market: bytes
    symbol: str | None
    total_supply: Decimal
    total_borrow: Decimal
    collateral_usd: Decimal
    utilization: Decimal
    borrow_rate: Decimal
    supply_rate: Decimal
    price_usd: Decimal
    supply_usd: Decimal
    borrow_usd: Decimal


@dataclass
class ReserveSnapshotRow:
    timestamp: datetime
    market: bytes
    reserve: bytes
    symbol: str | None
    decimals: int | None
    total_supply: Decimal
    total_borrow: Decimal
    utilization: Decimal
    borrow_rate: Decimal
    supply_rate: Decimal
    price_in_base: Decimal
    price_usd: Decimal
    supply_usd: Decimal
    borrow_usd: Decimal


@dataclass
class UserPositionSnapshotRow:
    timestamp: datetime
    block_number: int
    market: bytes
    symbol: str | None
    user_address: bytes
    has_open_position: bool
    is_liquidatable: bool
    base_token: bytes
    base_symbol: str | None
    base_price_usd: Decimal
    eth_price_usd: Decimal
    total_collateral_usd: Decimal
    total_debt_usd: Decimal
    discounted_collateral_usd: Decimal
    liquidation_buffer_usd: Decimal
    health_factor: Decimal
    eth_sensitive_collateral_usd: Decimal
    eth_sensitive_debt_usd: Decimal
    net_eth_exposure_usd: Decimal
    non_eth_collateral_usd: Decimal
    non_eth_debt_usd: Decimal
    basis_risk_collateral_usd: Decimal
    eth_down_liq_price_usd: Decimal | None
    eth_up_liq_price_usd: Decimal | None
    eth_liq_mode: str
    dominant_risk: str
    assets_jsonb: list[dict[str, Any]]


@dataclass
class UserPositionAssetRow:
    timestamp: datetime
    block_number: int
    market: bytes
    user_address: bytes
    asset: bytes
    symbol: str | None
    side: str
    decimals: int | None
    amount: Decimal
    price_in_base: Decimal | None
    price_usd: Decimal
    value_usd: Decimal
    discounted_value_usd: Decimal
    borrow_collateral_factor: Decimal | None
    liquidate_collateral_factor: Decimal | None
    liquidation_factor: Decimal | None
    beta_to_eth: Decimal
    is_eth_correlated: bool
    is_basis_risk_asset: bool


@dataclass
class CompoundV2ActiveUserRow:
    user_address: bytes
    is_active: bool
    activated_at: datetime | None
    last_event_at: datetime | None
    last_snapshot_at: datetime | None
    deactivated_at: datetime | None
    deactivate_reason: str | None
    last_total_collateral_usd: Decimal
    last_total_debt_usd: Decimal
    last_health_factor: Decimal


@dataclass
class CompoundEventPositionSnapshotRow:
    user_address: bytes
    protocol: str
    market: bytes
    symbol: str | None
    block_number: int
    tx_hash: str
    block_timestamp: datetime
    has_open_position: bool
    is_liquidatable: bool
    base_token: bytes | None
    base_symbol: str | None
    base_price_usd: Decimal | None
    eth_price_usd: Decimal
    total_collateral_usd: Decimal
    total_debt_usd: Decimal
    discounted_collateral_usd: Decimal
    liquidation_buffer_usd: Decimal
    health_factor: Decimal
    eth_sensitive_collateral_usd: Decimal
    eth_sensitive_debt_usd: Decimal
    net_eth_exposure_usd: Decimal
    non_eth_collateral_usd: Decimal
    non_eth_debt_usd: Decimal
    basis_risk_collateral_usd: Decimal
    eth_down_liq_price_usd: Decimal | None
    eth_up_liq_price_usd: Decimal | None
    eth_liq_mode: str
    dominant_risk: str
    assets_jsonb: list[dict[str, Any]]
    brief: str = ""


@dataclass
class CompoundCurrentPositionRow:
    market: bytes
    user_address: bytes
    symbol: str | None
    last_block_number: int
    last_block_timestamp: datetime
    last_tx_hash: str | None
    has_open_position: bool
    is_liquidatable: bool
    base_token: bytes | None
    base_symbol: str | None
    base_price_usd: Decimal | None
    eth_price_usd: Decimal
    total_collateral_usd: Decimal
    total_debt_usd: Decimal
    discounted_collateral_usd: Decimal
    liquidation_buffer_usd: Decimal
    health_factor: Decimal
    eth_sensitive_collateral_usd: Decimal
    eth_sensitive_debt_usd: Decimal
    net_eth_exposure_usd: Decimal
    non_eth_collateral_usd: Decimal
    non_eth_debt_usd: Decimal
    basis_risk_collateral_usd: Decimal
    eth_down_liq_price_usd: Decimal | None
    eth_up_liq_price_usd: Decimal | None
    eth_liq_mode: str
    dominant_risk: str
    assets_jsonb: list[dict[str, Any]]
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class CompoundCurrentPositionAssetRow:
    market: bytes
    user_address: bytes
    asset: bytes
    side: str
    symbol: str | None
    decimals: int | None
    amount: Decimal
    price_in_base: Decimal | None
    price_usd: Decimal
    value_usd: Decimal
    discounted_value_usd: Decimal
    borrow_collateral_factor: Decimal | None
    liquidate_collateral_factor: Decimal | None
    liquidation_factor: Decimal | None
    beta_to_eth: Decimal
    is_eth_correlated: bool
    is_basis_risk_asset: bool
    last_block_number: int
    last_block_timestamp: datetime
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class MarketConfigVersionRow:
    market: bytes
    symbol: str | None
    effective_timestamp: datetime
    block_number: int
    config_hash: str
    configurator: bytes | None
    factory: bytes | None
    governor: bytes | None
    pause_guardian: bytes | None
    base_token: bytes
    base_token_symbol: str | None
    base_token_price_feed: bytes | None
    extension_delegate: bytes | None
    base_scale: int
    base_decimals: int
    supply_kink: Decimal
    supply_per_year_interest_rate_slope_low: Decimal
    supply_per_year_interest_rate_slope_high: Decimal
    supply_per_year_interest_rate_base: Decimal
    borrow_kink: Decimal
    borrow_per_year_interest_rate_slope_low: Decimal
    borrow_per_year_interest_rate_slope_high: Decimal
    borrow_per_year_interest_rate_base: Decimal
    store_front_price_factor: Decimal
    tracking_index_scale: Decimal
    base_tracking_supply_speed: Decimal
    base_tracking_borrow_speed: Decimal
    base_min_for_rewards: Decimal
    base_borrow_min: Decimal
    target_reserves: Decimal
    raw_config_jsonb: dict[str, Any]


@dataclass
class MarketConfigAssetRow:
    market: bytes
    config_hash: str
    asset: bytes
    symbol: str | None
    price_feed: bytes | None
    decimals: int | None
    borrow_collateral_factor: Decimal
    liquidate_collateral_factor: Decimal
    liquidation_factor: Decimal
    supply_cap: Decimal
    raw_config_jsonb: dict[str, Any]


@dataclass
class MarketStatusSnapshotRow:
    timestamp: datetime
    block_number: int
    market: bytes
    symbol: str | None
    pause_flags: int
    base_supply_index: Decimal
    base_borrow_index: Decimal
    tracking_supply_index: Decimal
    tracking_borrow_index: Decimal
    total_supply_base: Decimal
    total_borrow_base: Decimal
    last_accrual_time: int
    raw_status_jsonb: dict[str, Any]


@dataclass
class V2MarketConfigVersionRow:
    market: bytes
    symbol: str | None
    effective_timestamp: datetime
    block_number: int
    config_hash: str
    comptroller: bytes | None
    interest_rate_model: bytes | None
    underlying: bytes | None
    underlying_symbol: str | None
    ctoken_decimals: int | None
    underlying_decimals: int | None
    collateral_factor: Decimal | None
    reserve_factor: Decimal | None
    liquidation_threshold: Decimal | None
    borrow_cap: Decimal | None
    supply_cap: Decimal | None
    is_listed: bool
    is_comped: bool
    is_deprecated: bool
    raw_config_jsonb: dict[str, Any]


@dataclass
class V2ProtocolConfigVersionRow:
    effective_timestamp: datetime
    block_number: int
    config_hash: str
    comptroller: bytes
    price_oracle: bytes | None
    close_factor: Decimal | None
    liquidation_incentive: Decimal | None
    pause_guardian: bytes | None
    transfer_paused: bool
    seize_paused: bool
    mint_paused: bool
    borrow_paused: bool
    raw_config_jsonb: dict[str, Any]


_DDL_MARKET = """
CREATE TABLE IF NOT EXISTS loan.{table_name} (
    "timestamp"    TIMESTAMPTZ     NOT NULL,
    market         BYTEA           NOT NULL,
    symbol         TEXT            NULL,
    total_supply   NUMERIC(38, 18) NOT NULL,
    total_borrow   NUMERIC(38, 18) NOT NULL,
    collateral_usd NUMERIC(30, 8)  NOT NULL,
    utilization    NUMERIC(20, 18) NOT NULL,
    borrow_rate    NUMERIC(38, 18) NOT NULL,
    supply_rate    NUMERIC(38, 18) NOT NULL,
    price_usd      NUMERIC(30, 8)  NOT NULL,
    supply_usd     NUMERIC(30, 8)  NOT NULL,
    borrow_usd     NUMERIC(30, 8)  NOT NULL,
    created_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("timestamp", market)
);
"""


_DDL_MARKET_INDEX_TS = """
CREATE INDEX IF NOT EXISTS {index_name}
    ON loan.{table_name} ("timestamp" DESC);
"""


_DDL_MARKET_INDEX_MARKET = """
CREATE INDEX IF NOT EXISTS {index_name}
    ON loan.{table_name} (market, "timestamp" DESC);
"""


_DDL_RESERVE = """
CREATE TABLE IF NOT EXISTS loan.{table_name} (
    "timestamp"    TIMESTAMPTZ     NOT NULL,
    market         BYTEA           NOT NULL,
    reserve        BYTEA           NOT NULL,
    symbol         TEXT            NULL,
    decimals       INTEGER         NULL,
    total_supply   NUMERIC(38, 18) NOT NULL,
    total_borrow   NUMERIC(38, 18) NOT NULL,
    utilization    NUMERIC(20, 18) NOT NULL,
    borrow_rate    NUMERIC(38, 18) NOT NULL,
    supply_rate    NUMERIC(38, 18) NOT NULL,
    price_in_base  NUMERIC(30, 8)  NOT NULL,
    price_usd      NUMERIC(30, 8)  NOT NULL,
    supply_usd     NUMERIC(30, 8)  NOT NULL,
    borrow_usd     NUMERIC(30, 8)  NOT NULL,
    created_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("timestamp", market, reserve)
);
"""


_DDL_RESERVE_INDEX_MARKET_TS = """
CREATE INDEX IF NOT EXISTS {index_name}
    ON loan.{table_name} (market, "timestamp" DESC);
"""


_DDL_RESERVE_INDEX_RESERVE_TS = """
CREATE INDEX IF NOT EXISTS {index_name}
    ON loan.{table_name} (reserve, "timestamp" DESC);
"""


_UPSERT_MARKET = """
INSERT INTO loan.{table_name} (
    "timestamp", market,
    symbol, total_supply, total_borrow, collateral_usd, utilization,
    borrow_rate, supply_rate, price_usd,
    supply_usd, borrow_usd
) VALUES (
    $1, $2,
    $3, $4, $5, $6, $7,
    $8, $9, $10,
    $11, $12
)
ON CONFLICT ("timestamp", market) DO UPDATE SET
    symbol = EXCLUDED.symbol,
    total_supply = EXCLUDED.total_supply,
    total_borrow = EXCLUDED.total_borrow,
    collateral_usd = EXCLUDED.collateral_usd,
    utilization = EXCLUDED.utilization,
    borrow_rate = EXCLUDED.borrow_rate,
    supply_rate = EXCLUDED.supply_rate,
    price_usd = EXCLUDED.price_usd,
    supply_usd = EXCLUDED.supply_usd,
    borrow_usd = EXCLUDED.borrow_usd,
    created_at = NOW();
"""


_UPSERT_RESERVE = """
INSERT INTO loan.{table_name} (
    "timestamp", market, reserve,
    symbol, decimals,
    total_supply, total_borrow, utilization,
    borrow_rate, supply_rate, price_in_base, price_usd,
    supply_usd, borrow_usd
) VALUES (
    $1, $2, $3,
    $4, $5,
    $6, $7, $8,
    $9, $10, $11, $12,
    $13, $14
)
ON CONFLICT ("timestamp", market, reserve) DO UPDATE SET
    symbol = EXCLUDED.symbol,
    decimals = EXCLUDED.decimals,
    total_supply = EXCLUDED.total_supply,
    total_borrow = EXCLUDED.total_borrow,
    utilization = EXCLUDED.utilization,
    borrow_rate = EXCLUDED.borrow_rate,
    supply_rate = EXCLUDED.supply_rate,
    price_in_base = EXCLUDED.price_in_base,
    price_usd = EXCLUDED.price_usd,
    supply_usd = EXCLUDED.supply_usd,
    borrow_usd = EXCLUDED.borrow_usd,
    created_at = NOW();
"""


_UPSERT_RESERVE_V2 = """
INSERT INTO loan.{table_name} (
    "timestamp", market, reserve,
    symbol, decimals,
    total_supply, total_borrow, utilization,
    borrow_rate, supply_rate, price_usd,
    supply_usd, borrow_usd
) VALUES (
    $1, $2, $3,
    $4, $5,
    $6, $7, $8,
    $9, $10, $11,
    $12, $13
)
ON CONFLICT ("timestamp", market, reserve) DO UPDATE SET
    symbol = EXCLUDED.symbol,
    decimals = EXCLUDED.decimals,
    total_supply = EXCLUDED.total_supply,
    total_borrow = EXCLUDED.total_borrow,
    utilization = EXCLUDED.utilization,
    borrow_rate = EXCLUDED.borrow_rate,
    supply_rate = EXCLUDED.supply_rate,
    price_usd = EXCLUDED.price_usd,
    supply_usd = EXCLUDED.supply_usd,
    borrow_usd = EXCLUDED.borrow_usd,
    created_at = NOW();
"""


_MARKET_CONFIG_TABLE = "compound_v3_market_config_versions"
_MARKET_CONFIG_ASSET_TABLE = "compound_v3_market_config_assets"
_MARKET_STATUS_TABLE = "compound_v3_market_status_snapshots"
_V2_MARKET_CONFIG_TABLE = "compound_v2_market_config_versions"
_V2_PROTOCOL_CONFIG_TABLE = "compound_v2_protocol_config_versions"
_COMPOUND_EVENT_SNAPSHOT_TABLE = "compound_position_snapshots"

_DDL_MARKET_CONFIG = f"""
CREATE TABLE IF NOT EXISTS loan.{_MARKET_CONFIG_TABLE} (
    market                                 BYTEA           NOT NULL,
    symbol                                 TEXT            NULL,
    effective_timestamp                    TIMESTAMPTZ     NOT NULL,
    block_number                           BIGINT          NOT NULL,
    config_hash                            TEXT            NOT NULL,
    configurator                           BYTEA           NULL,
    factory                                BYTEA           NULL,
    governor                               BYTEA           NULL,
    pause_guardian                         BYTEA           NULL,
    base_token                             BYTEA           NOT NULL,
    base_token_symbol                      TEXT            NULL,
    base_token_price_feed                  BYTEA           NULL,
    extension_delegate                     BYTEA           NULL,
    base_scale                             NUMERIC(38, 0)  NOT NULL,
    base_decimals                          INTEGER         NOT NULL,
    supply_kink                            NUMERIC(38, 18) NOT NULL,
    supply_per_year_interest_rate_slope_low  NUMERIC(38, 18) NOT NULL,
    supply_per_year_interest_rate_slope_high NUMERIC(38, 18) NOT NULL,
    supply_per_year_interest_rate_base       NUMERIC(38, 18) NOT NULL,
    borrow_kink                            NUMERIC(38, 18) NOT NULL,
    borrow_per_year_interest_rate_slope_low  NUMERIC(38, 18) NOT NULL,
    borrow_per_year_interest_rate_slope_high NUMERIC(38, 18) NOT NULL,
    borrow_per_year_interest_rate_base       NUMERIC(38, 18) NOT NULL,
    store_front_price_factor               NUMERIC(38, 18) NOT NULL,
    tracking_index_scale                   NUMERIC(38, 18) NOT NULL,
    base_tracking_supply_speed             NUMERIC(38, 18) NOT NULL,
    base_tracking_borrow_speed             NUMERIC(38, 18) NOT NULL,
    base_min_for_rewards                   NUMERIC(38, 18) NOT NULL,
    base_borrow_min                        NUMERIC(38, 18) NOT NULL,
    target_reserves                        NUMERIC(38, 18) NOT NULL,
    raw_config_jsonb                       JSONB           NOT NULL,
    created_at                             TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, config_hash)
);
"""

_DDL_MARKET_CONFIG_INDEX_TS = f"""
CREATE INDEX IF NOT EXISTS idx_{_MARKET_CONFIG_TABLE}_market_effective_ts
    ON loan.{_MARKET_CONFIG_TABLE} (market, effective_timestamp DESC);
"""

_DDL_MARKET_CONFIG_ASSET = f"""
CREATE TABLE IF NOT EXISTS loan.{_MARKET_CONFIG_ASSET_TABLE} (
    market                       BYTEA           NOT NULL,
    config_hash                  TEXT            NOT NULL,
    asset                        BYTEA           NOT NULL,
    symbol                       TEXT            NULL,
    price_feed                   BYTEA           NULL,
    decimals                     INTEGER         NULL,
    borrow_collateral_factor     NUMERIC(38, 18) NOT NULL,
    liquidate_collateral_factor  NUMERIC(38, 18) NOT NULL,
    liquidation_factor           NUMERIC(38, 18) NOT NULL,
    supply_cap                   NUMERIC(38, 18) NOT NULL,
    raw_config_jsonb             JSONB           NOT NULL,
    created_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, config_hash, asset)
);
"""

_DDL_MARKET_CONFIG_ASSET_INDEX = f"""
CREATE INDEX IF NOT EXISTS idx_{_MARKET_CONFIG_ASSET_TABLE}_market_hash
    ON loan.{_MARKET_CONFIG_ASSET_TABLE} (market, config_hash);
"""

_DDL_MARKET_STATUS = f"""
CREATE TABLE IF NOT EXISTS loan.{_MARKET_STATUS_TABLE} (
    "timestamp"           TIMESTAMPTZ     NOT NULL,
    block_number          BIGINT          NOT NULL,
    market                BYTEA           NOT NULL,
    symbol                TEXT            NULL,
    pause_flags           INTEGER         NOT NULL,
    base_supply_index     NUMERIC(38, 18) NOT NULL,
    base_borrow_index     NUMERIC(38, 18) NOT NULL,
    tracking_supply_index NUMERIC(38, 18) NOT NULL,
    tracking_borrow_index NUMERIC(38, 18) NOT NULL,
    total_supply_base     NUMERIC(38, 18) NOT NULL,
    total_borrow_base     NUMERIC(38, 18) NOT NULL,
    last_accrual_time     BIGINT          NOT NULL,
    raw_status_jsonb      JSONB           NOT NULL,
    created_at            TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("timestamp", market)
);
"""

_DDL_MARKET_STATUS_INDEX = f"""
CREATE INDEX IF NOT EXISTS idx_{_MARKET_STATUS_TABLE}_market_ts
    ON loan.{_MARKET_STATUS_TABLE} (market, "timestamp" DESC);
"""

_UPSERT_MARKET_CONFIG = f"""
INSERT INTO loan.{_MARKET_CONFIG_TABLE} (
    market, symbol, effective_timestamp, block_number, config_hash,
    configurator, factory, governor, pause_guardian,
    base_token, base_token_symbol, base_token_price_feed, extension_delegate,
    base_scale, base_decimals,
    supply_kink,
    supply_per_year_interest_rate_slope_low,
    supply_per_year_interest_rate_slope_high,
    supply_per_year_interest_rate_base,
    borrow_kink,
    borrow_per_year_interest_rate_slope_low,
    borrow_per_year_interest_rate_slope_high,
    borrow_per_year_interest_rate_base,
    store_front_price_factor,
    tracking_index_scale,
    base_tracking_supply_speed,
    base_tracking_borrow_speed,
    base_min_for_rewards,
    base_borrow_min,
    target_reserves,
    raw_config_jsonb
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7, $8, $9,
    $10, $11, $12, $13,
    $14, $15,
    $16, $17, $18, $19,
    $20, $21, $22, $23,
    $24, $25, $26, $27,
    $28, $29, $30, $31
)
ON CONFLICT (market, config_hash) DO UPDATE SET
    symbol = EXCLUDED.symbol,
    effective_timestamp = LEAST(
        loan.compound_v3_market_config_versions.effective_timestamp,
        EXCLUDED.effective_timestamp
    ),
    block_number = CASE
        WHEN EXCLUDED.effective_timestamp
           < loan.compound_v3_market_config_versions.effective_timestamp
        THEN EXCLUDED.block_number
        ELSE loan.compound_v3_market_config_versions.block_number
    END,
    configurator = EXCLUDED.configurator,
    factory = EXCLUDED.factory,
    governor = EXCLUDED.governor,
    pause_guardian = EXCLUDED.pause_guardian,
    base_token = EXCLUDED.base_token,
    base_token_symbol = EXCLUDED.base_token_symbol,
    base_token_price_feed = EXCLUDED.base_token_price_feed,
    extension_delegate = EXCLUDED.extension_delegate,
    base_scale = EXCLUDED.base_scale,
    base_decimals = EXCLUDED.base_decimals,
    supply_kink = EXCLUDED.supply_kink,
    supply_per_year_interest_rate_slope_low = EXCLUDED.supply_per_year_interest_rate_slope_low,
    supply_per_year_interest_rate_slope_high = EXCLUDED.supply_per_year_interest_rate_slope_high,
    supply_per_year_interest_rate_base = EXCLUDED.supply_per_year_interest_rate_base,
    borrow_kink = EXCLUDED.borrow_kink,
    borrow_per_year_interest_rate_slope_low = EXCLUDED.borrow_per_year_interest_rate_slope_low,
    borrow_per_year_interest_rate_slope_high = EXCLUDED.borrow_per_year_interest_rate_slope_high,
    borrow_per_year_interest_rate_base = EXCLUDED.borrow_per_year_interest_rate_base,
    store_front_price_factor = EXCLUDED.store_front_price_factor,
    tracking_index_scale = EXCLUDED.tracking_index_scale,
    base_tracking_supply_speed = EXCLUDED.base_tracking_supply_speed,
    base_tracking_borrow_speed = EXCLUDED.base_tracking_borrow_speed,
    base_min_for_rewards = EXCLUDED.base_min_for_rewards,
    base_borrow_min = EXCLUDED.base_borrow_min,
    target_reserves = EXCLUDED.target_reserves,
    raw_config_jsonb = EXCLUDED.raw_config_jsonb,
    created_at = NOW();
"""

_UPSERT_MARKET_CONFIG_ASSET = f"""
INSERT INTO loan.{_MARKET_CONFIG_ASSET_TABLE} (
    market, config_hash, asset, symbol, price_feed, decimals,
    borrow_collateral_factor, liquidate_collateral_factor, liquidation_factor,
    supply_cap, raw_config_jsonb
) VALUES (
    $1, $2, $3, $4, $5, $6,
    $7, $8, $9, $10, $11
)
ON CONFLICT (market, config_hash, asset) DO UPDATE SET
    symbol = EXCLUDED.symbol,
    price_feed = EXCLUDED.price_feed,
    decimals = EXCLUDED.decimals,
    borrow_collateral_factor = EXCLUDED.borrow_collateral_factor,
    liquidate_collateral_factor = EXCLUDED.liquidate_collateral_factor,
    liquidation_factor = EXCLUDED.liquidation_factor,
    supply_cap = EXCLUDED.supply_cap,
    raw_config_jsonb = EXCLUDED.raw_config_jsonb,
    created_at = NOW();
"""

_UPSERT_MARKET_STATUS = f"""
INSERT INTO loan.{_MARKET_STATUS_TABLE} (
    "timestamp", block_number, market, symbol, pause_flags,
    base_supply_index, base_borrow_index, tracking_supply_index, tracking_borrow_index,
    total_supply_base, total_borrow_base, last_accrual_time, raw_status_jsonb
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7, $8, $9,
    $10, $11, $12, $13
)
ON CONFLICT ("timestamp", market) DO UPDATE SET
    block_number = EXCLUDED.block_number,
    symbol = EXCLUDED.symbol,
    pause_flags = EXCLUDED.pause_flags,
    base_supply_index = EXCLUDED.base_supply_index,
    base_borrow_index = EXCLUDED.base_borrow_index,
    tracking_supply_index = EXCLUDED.tracking_supply_index,
    tracking_borrow_index = EXCLUDED.tracking_borrow_index,
    total_supply_base = EXCLUDED.total_supply_base,
    total_borrow_base = EXCLUDED.total_borrow_base,
    last_accrual_time = EXCLUDED.last_accrual_time,
    raw_status_jsonb = EXCLUDED.raw_status_jsonb,
    created_at = NOW();
"""


_DDL_V2_MARKET_CONFIG = f"""
CREATE TABLE IF NOT EXISTS loan.{_V2_MARKET_CONFIG_TABLE} (
    market                 BYTEA           NOT NULL,
    symbol                 TEXT            NULL,
    effective_timestamp    TIMESTAMPTZ     NOT NULL,
    block_number           BIGINT          NOT NULL,
    config_hash            TEXT            NOT NULL,
    comptroller            BYTEA           NULL,
    interest_rate_model    BYTEA           NULL,
    underlying             BYTEA           NULL,
    underlying_symbol      TEXT            NULL,
    ctoken_decimals        INTEGER         NULL,
    underlying_decimals    INTEGER         NULL,
    collateral_factor      NUMERIC(20, 18) NULL,
    reserve_factor         NUMERIC(20, 18) NULL,
    liquidation_threshold  NUMERIC(20, 18) NULL,
    borrow_cap             NUMERIC(38, 18) NULL,
    supply_cap             NUMERIC(38, 18) NULL,
    is_listed              BOOLEAN         NOT NULL DEFAULT TRUE,
    is_comped              BOOLEAN         NOT NULL DEFAULT FALSE,
    is_deprecated          BOOLEAN         NOT NULL DEFAULT FALSE,
    raw_config_jsonb       JSONB           NOT NULL,
    created_at             TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, config_hash)
);
"""

_DDL_V2_MARKET_CONFIG_INDEX = f"""
CREATE INDEX IF NOT EXISTS idx_{_V2_MARKET_CONFIG_TABLE}_market_effective_ts
    ON loan.{_V2_MARKET_CONFIG_TABLE} (market, effective_timestamp DESC);
"""

_DDL_V2_PROTOCOL_CONFIG = f"""
CREATE TABLE IF NOT EXISTS loan.{_V2_PROTOCOL_CONFIG_TABLE} (
    effective_timestamp    TIMESTAMPTZ     NOT NULL,
    block_number           BIGINT          NOT NULL,
    config_hash            TEXT            NOT NULL PRIMARY KEY,
    comptroller            BYTEA           NOT NULL,
    price_oracle           BYTEA           NULL,
    close_factor           NUMERIC(20, 18) NULL,
    liquidation_incentive  NUMERIC(20, 18) NULL,
    pause_guardian         BYTEA           NULL,
    transfer_paused        BOOLEAN         NOT NULL DEFAULT FALSE,
    seize_paused           BOOLEAN         NOT NULL DEFAULT FALSE,
    mint_paused            BOOLEAN         NOT NULL DEFAULT FALSE,
    borrow_paused          BOOLEAN         NOT NULL DEFAULT FALSE,
    raw_config_jsonb       JSONB           NOT NULL,
    created_at             TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
"""

_DDL_V2_PROTOCOL_CONFIG_INDEX = f"""
CREATE INDEX IF NOT EXISTS idx_{_V2_PROTOCOL_CONFIG_TABLE}_effective_ts
    ON loan.{_V2_PROTOCOL_CONFIG_TABLE} (effective_timestamp DESC);
"""

_UPSERT_V2_MARKET_CONFIG = f"""
INSERT INTO loan.{_V2_MARKET_CONFIG_TABLE} (
    market, symbol, effective_timestamp, block_number, config_hash,
    comptroller, interest_rate_model, underlying, underlying_symbol,
    ctoken_decimals, underlying_decimals, collateral_factor, reserve_factor,
    liquidation_threshold, borrow_cap, supply_cap, is_listed, is_comped, is_deprecated,
    raw_config_jsonb
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7, $8, $9,
    $10, $11, $12, $13,
    $14, $15, $16, $17, $18, $19,
    $20
)
ON CONFLICT (market, config_hash) DO UPDATE SET
    symbol = EXCLUDED.symbol,
    effective_timestamp = LEAST(loan.compound_v2_market_config_versions.effective_timestamp, EXCLUDED.effective_timestamp),
    block_number = CASE
        WHEN EXCLUDED.effective_timestamp < loan.compound_v2_market_config_versions.effective_timestamp
        THEN EXCLUDED.block_number
        ELSE loan.compound_v2_market_config_versions.block_number
    END,
    comptroller = EXCLUDED.comptroller,
    interest_rate_model = EXCLUDED.interest_rate_model,
    underlying = EXCLUDED.underlying,
    underlying_symbol = EXCLUDED.underlying_symbol,
    ctoken_decimals = EXCLUDED.ctoken_decimals,
    underlying_decimals = EXCLUDED.underlying_decimals,
    collateral_factor = EXCLUDED.collateral_factor,
    reserve_factor = EXCLUDED.reserve_factor,
    liquidation_threshold = EXCLUDED.liquidation_threshold,
    borrow_cap = EXCLUDED.borrow_cap,
    supply_cap = EXCLUDED.supply_cap,
    is_listed = EXCLUDED.is_listed,
    is_comped = EXCLUDED.is_comped,
    is_deprecated = EXCLUDED.is_deprecated,
    raw_config_jsonb = EXCLUDED.raw_config_jsonb,
    created_at = NOW();
"""

_UPSERT_V2_PROTOCOL_CONFIG = f"""
INSERT INTO loan.{_V2_PROTOCOL_CONFIG_TABLE} (
    effective_timestamp, block_number, config_hash, comptroller, price_oracle,
    close_factor, liquidation_incentive, pause_guardian, transfer_paused, seize_paused,
    mint_paused, borrow_paused, raw_config_jsonb
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7, $8, $9, $10,
    $11, $12, $13
)
ON CONFLICT (config_hash) DO UPDATE SET
    effective_timestamp = LEAST(loan.compound_v2_protocol_config_versions.effective_timestamp, EXCLUDED.effective_timestamp),
    block_number = CASE
        WHEN EXCLUDED.effective_timestamp < loan.compound_v2_protocol_config_versions.effective_timestamp
        THEN EXCLUDED.block_number
        ELSE loan.compound_v2_protocol_config_versions.block_number
    END,
    comptroller = EXCLUDED.comptroller,
    price_oracle = EXCLUDED.price_oracle,
    close_factor = EXCLUDED.close_factor,
    liquidation_incentive = EXCLUDED.liquidation_incentive,
    pause_guardian = EXCLUDED.pause_guardian,
    transfer_paused = EXCLUDED.transfer_paused,
    seize_paused = EXCLUDED.seize_paused,
    mint_paused = EXCLUDED.mint_paused,
    borrow_paused = EXCLUDED.borrow_paused,
    raw_config_jsonb = EXCLUDED.raw_config_jsonb,
    created_at = NOW();
"""


_DDL_COMPOUND_EVENT_SNAPSHOT = f"""
CREATE TABLE IF NOT EXISTS loan.{_COMPOUND_EVENT_SNAPSHOT_TABLE} (
    id                           BIGSERIAL        PRIMARY KEY,
    user_address                 BYTEA            NOT NULL,
    protocol                     TEXT             NOT NULL,
    market                       BYTEA            NOT NULL,
    symbol                       TEXT             NULL,
    block_number                 BIGINT           NOT NULL,
    tx_hash                      TEXT             NOT NULL,
    block_timestamp              TIMESTAMPTZ      NOT NULL,
    has_open_position            BOOLEAN          NOT NULL,
    is_liquidatable              BOOLEAN          NOT NULL,
    base_token                   BYTEA            NULL,
    base_symbol                  TEXT             NULL,
    base_price_usd               NUMERIC(30, 8)   NULL,
    eth_price_usd                NUMERIC(30, 8)   NOT NULL,
    total_collateral_usd         NUMERIC(30, 8)   NOT NULL,
    total_debt_usd               NUMERIC(30, 8)   NOT NULL,
    discounted_collateral_usd    NUMERIC(30, 8)   NOT NULL,
    liquidation_buffer_usd       NUMERIC(30, 8)   NOT NULL,
    health_factor                NUMERIC(40, 18)  NOT NULL,
    eth_sensitive_collateral_usd NUMERIC(30, 8)   NOT NULL,
    eth_sensitive_debt_usd       NUMERIC(30, 8)   NOT NULL,
    net_eth_exposure_usd         NUMERIC(30, 8)   NOT NULL,
    non_eth_collateral_usd       NUMERIC(30, 8)   NOT NULL,
    non_eth_debt_usd             NUMERIC(30, 8)   NOT NULL,
    basis_risk_collateral_usd    NUMERIC(30, 8)   NOT NULL,
    eth_down_liq_price_usd       NUMERIC(30, 8)   NULL,
    eth_up_liq_price_usd         NUMERIC(30, 8)   NULL,
    eth_liq_mode                 TEXT             NOT NULL,
    dominant_risk                TEXT             NOT NULL,
    assets_jsonb                 JSONB            NOT NULL DEFAULT '[]',
    brief                        TEXT             NOT NULL DEFAULT '',
    cached_at                    TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    UNIQUE (user_address, protocol, market, tx_hash)
);
"""

_DDL_COMPOUND_EVENT_SNAPSHOT_INDEXES = f"""
CREATE INDEX IF NOT EXISTS idx_{_COMPOUND_EVENT_SNAPSHOT_TABLE}_user_market_ts
    ON loan.{_COMPOUND_EVENT_SNAPSHOT_TABLE} (user_address, protocol, market, block_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_{_COMPOUND_EVENT_SNAPSHOT_TABLE}_block
    ON loan.{_COMPOUND_EVENT_SNAPSHOT_TABLE} (block_number);
"""

_SQL_UPSERT_COMPOUND_EVENT_SNAPSHOT = f"""
INSERT INTO loan.{_COMPOUND_EVENT_SNAPSHOT_TABLE} (
    user_address, protocol, market, symbol, block_number, tx_hash, block_timestamp,
    has_open_position, is_liquidatable, base_token, base_symbol, base_price_usd,
    eth_price_usd, total_collateral_usd, total_debt_usd, discounted_collateral_usd,
    liquidation_buffer_usd, health_factor, eth_sensitive_collateral_usd, eth_sensitive_debt_usd,
    net_eth_exposure_usd, non_eth_collateral_usd, non_eth_debt_usd, basis_risk_collateral_usd,
    eth_down_liq_price_usd, eth_up_liq_price_usd, eth_liq_mode, dominant_risk,
    assets_jsonb, brief
) VALUES (
    $1,$2,$3,$4,$5,$6,$7,
    $8,$9,$10,$11,$12,
    $13,$14,$15,$16,
    $17,$18,$19,$20,
    $21,$22,$23,$24,
    $25,$26,$27,$28,
    $29,$30
)
ON CONFLICT (user_address, protocol, market, tx_hash) DO UPDATE SET
    symbol = EXCLUDED.symbol,
    block_number = EXCLUDED.block_number,
    block_timestamp = EXCLUDED.block_timestamp,
    has_open_position = EXCLUDED.has_open_position,
    is_liquidatable = EXCLUDED.is_liquidatable,
    base_token = EXCLUDED.base_token,
    base_symbol = EXCLUDED.base_symbol,
    base_price_usd = EXCLUDED.base_price_usd,
    eth_price_usd = EXCLUDED.eth_price_usd,
    total_collateral_usd = EXCLUDED.total_collateral_usd,
    total_debt_usd = EXCLUDED.total_debt_usd,
    discounted_collateral_usd = EXCLUDED.discounted_collateral_usd,
    liquidation_buffer_usd = EXCLUDED.liquidation_buffer_usd,
    health_factor = EXCLUDED.health_factor,
    eth_sensitive_collateral_usd = EXCLUDED.eth_sensitive_collateral_usd,
    eth_sensitive_debt_usd = EXCLUDED.eth_sensitive_debt_usd,
    net_eth_exposure_usd = EXCLUDED.net_eth_exposure_usd,
    non_eth_collateral_usd = EXCLUDED.non_eth_collateral_usd,
    non_eth_debt_usd = EXCLUDED.non_eth_debt_usd,
    basis_risk_collateral_usd = EXCLUDED.basis_risk_collateral_usd,
    eth_down_liq_price_usd = EXCLUDED.eth_down_liq_price_usd,
    eth_up_liq_price_usd = EXCLUDED.eth_up_liq_price_usd,
    eth_liq_mode = EXCLUDED.eth_liq_mode,
    dominant_risk = EXCLUDED.dominant_risk,
    assets_jsonb = EXCLUDED.assets_jsonb,
    brief = EXCLUDED.brief,
    cached_at = NOW();
"""

_SQL_GET_COMPOUND_EVENT_SNAPSHOTS = f"""
SELECT
    id, user_address, protocol, market, symbol, block_number, tx_hash, block_timestamp,
    has_open_position, is_liquidatable, base_token, base_symbol, base_price_usd,
    eth_price_usd, total_collateral_usd, total_debt_usd, discounted_collateral_usd,
    liquidation_buffer_usd, health_factor, eth_sensitive_collateral_usd, eth_sensitive_debt_usd,
    net_eth_exposure_usd, non_eth_collateral_usd, non_eth_debt_usd, basis_risk_collateral_usd,
    eth_down_liq_price_usd, eth_up_liq_price_usd, eth_liq_mode, dominant_risk,
    assets_jsonb, brief, cached_at
FROM loan.{_COMPOUND_EVENT_SNAPSHOT_TABLE}
WHERE user_address = $1
  AND protocol = $2
  AND market = $3
  AND block_timestamp BETWEEN $4 AND $5
ORDER BY block_timestamp ASC
"""


_CANDIDATE_HISTORY_TIME_COLUMNS = (
    "block_timestamp",
    "timestamp",
    "block_time",
    "event_time",
    "created_at",
)
_CANDIDATE_HISTORY_BLOCK_COLUMNS = ("block_number", "block_num")
_CANDIDATE_HISTORY_TX_COLUMNS = ("tx_hash", "transaction_hash", "hash")
_CANDIDATE_HISTORY_MARKET_COLUMNS = (
    "market",
    "market_address",
    "comet",
    "ctoken",
    "to_address",
)
_CANDIDATE_HISTORY_USER_COLUMNS = (
    "from_address",
    "target_user_address",
    "user_address",
    "account",
    "on_behalf_of",
)
_CANDIDATE_HISTORY_VERSION_COLUMNS = ("version", "protocol_version")
_CANDIDATE_HISTORY_STATUS_COLUMNS = ("tx_status", "status")


def _first_existing_column(
    available_columns: dict[str, str],
    candidates: tuple[str, ...],
) -> str | None:
    for name in candidates:
        if name in available_columns:
            return name
    return None


def _sql_value_expr_by_type(column_name: str, data_type: str, param_index: int) -> str:
    if data_type == "bytea":
        return f"{column_name} = ${param_index}::bytea"
    return f"lower({column_name}::text) = lower(${param_index}::text)"


async def fetch_compound_user_tx_history(
    pool: asyncpg.Pool,
    *,
    user_address: bytes,
    protocol: str,
    from_dt: datetime,
    to_dt: datetime,
    market: bytes | None = None,
    only_success: bool = True,
    user_column: str | None = None,
) -> list[Any]:
    protocol_version = "3" if protocol == "v3" else "2"
    async with pool.acquire() as conn:
        col_rows = await conn.fetch(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'compound'
              AND table_name = 'compound_history'
            """
        )
        if not col_rows:
            raise RuntimeError("compound.compound_history not found")

        column_types: dict[str, str] = {
            str(row["column_name"]): str(row["data_type"]) for row in col_rows
        }
        time_col = _first_existing_column(column_types, _CANDIDATE_HISTORY_TIME_COLUMNS)
        block_col = _first_existing_column(
            column_types, _CANDIDATE_HISTORY_BLOCK_COLUMNS
        )
        tx_col = _first_existing_column(column_types, _CANDIDATE_HISTORY_TX_COLUMNS)
        market_col = _first_existing_column(
            column_types, _CANDIDATE_HISTORY_MARKET_COLUMNS
        )
        version_col = _first_existing_column(
            column_types, _CANDIDATE_HISTORY_VERSION_COLUMNS
        )
        status_col = _first_existing_column(
            column_types, _CANDIDATE_HISTORY_STATUS_COLUMNS
        )
        selected_user_col = user_column if user_column in column_types else None
        if selected_user_col is None:
            selected_user_col = _first_existing_column(
                column_types, _CANDIDATE_HISTORY_USER_COLUMNS
            )

        if not time_col or not block_col or not tx_col or not selected_user_col:
            raise RuntimeError(
                "compound.compound_history missing required columns "
                f"(time={time_col}, block={block_col}, tx={tx_col}, user={selected_user_col})"
            )

        where_clauses: list[str] = []
        bind_values: list[Any] = []

        if version_col is not None:
            bind_values.append(protocol_version)
            where_clauses.append(f"{version_col}::text = ${len(bind_values)}")
        if only_success and status_col is not None:
            bind_values.append(1)
            where_clauses.append(f"{status_col} = ${len(bind_values)}")

        bind_values.append(from_dt)
        where_clauses.append(f"{time_col} >= ${len(bind_values)}::timestamptz")
        bind_values.append(to_dt)
        where_clauses.append(f"{time_col} <= ${len(bind_values)}::timestamptz")

        bind_values.append(user_address)
        where_clauses.append(
            _sql_value_expr_by_type(
                selected_user_col,
                column_types[selected_user_col],
                len(bind_values),
            )
        )

        if market is not None and market_col is not None:
            bind_values.append(market)
            where_clauses.append(
                _sql_value_expr_by_type(
                    market_col,
                    column_types[market_col],
                    len(bind_values),
                )
            )

        select_market = market_col if market_col is not None else "NULL"
        select_method_id = "method_id" if "method_id" in column_types else "NULL"
        sql = f"""
            SELECT
                {tx_col} AS tx_hash,
                {block_col} AS block_number,
                {time_col} AS block_timestamp,
                {select_market} AS market,
                {select_method_id} AS method_id
            FROM compound.compound_history
            WHERE {" AND ".join(where_clauses)}
            ORDER BY {time_col} ASC, {block_col} ASC
        """
        return await conn.fetch(sql, *bind_values)


async def fetch_compound_cached_event_keys(
    pool: asyncpg.Pool,
    *,
    user_address: bytes,
    protocol: str,
    from_dt: datetime,
    to_dt: datetime,
    market: bytes | None = None,
) -> set[tuple[bytes, str]]:
    sql = f"""
        SELECT market, tx_hash
        FROM loan.{_COMPOUND_EVENT_SNAPSHOT_TABLE}
        WHERE user_address = $1
          AND protocol = $2
          AND block_timestamp BETWEEN $3 AND $4
    """
    args: list[Any] = [user_address, protocol, from_dt, to_dt]
    if market is not None:
        sql += " AND market = $5"
        args.append(market)
    rows = await pool.fetch(sql, *args)
    return {
        (
            bytes(row["market"]),
            str(row["tx_hash"]).strip().lower(),
        )
        for row in rows
    }


_USER_POSITION_TABLES = {
    "v2": "compound_v2_user_position_snapshots",
    "v3": "compound_v3_user_position_snapshots",
}

_USER_POSITION_ASSET_TABLES = {
    "v2": "compound_v2_user_position_snapshot_assets",
    "v3": "compound_v3_user_position_snapshot_assets",
}

_V3_CURRENT_POSITION_TABLE = "compound_v3_current_positions"
_V3_CURRENT_POSITION_ASSET_TABLE = "compound_v3_current_position_assets"
_V2_CURRENT_POSITION_TABLE = "compound_v2_current_positions"
_V2_CURRENT_POSITION_ASSET_TABLE = "compound_v2_current_position_assets"
_V2_ACTIVE_USER_TABLE = "compound_v2_active_users"
_V2_ACTIVE_RUN_STATE_TABLE = "compound_v2_active_run_state"

_DDL_USER_POSITION = """
CREATE TABLE IF NOT EXISTS loan.{table_name} (
    "timestamp"                  TIMESTAMPTZ     NOT NULL,
    block_number                 BIGINT          NOT NULL,
    market                       BYTEA           NOT NULL,
    symbol                       TEXT            NULL,
    user_address                 BYTEA           NOT NULL,
    has_open_position            BOOLEAN         NOT NULL,
    is_liquidatable              BOOLEAN         NOT NULL,
    base_token                   BYTEA           NULL,
    base_symbol                  TEXT            NULL,
    base_price_usd               NUMERIC(30, 8)  NULL,
    eth_price_usd                NUMERIC(30, 8)  NOT NULL,
    total_collateral_usd         NUMERIC(30, 8)  NOT NULL,
    total_debt_usd               NUMERIC(30, 8)  NOT NULL,
    discounted_collateral_usd    NUMERIC(30, 8)  NOT NULL,
    liquidation_buffer_usd       NUMERIC(30, 8)  NOT NULL,
    health_factor                NUMERIC(40, 18) NOT NULL,
    eth_sensitive_collateral_usd NUMERIC(30, 8)  NOT NULL,
    eth_sensitive_debt_usd       NUMERIC(30, 8)  NOT NULL,
    net_eth_exposure_usd         NUMERIC(30, 8)  NOT NULL,
    non_eth_collateral_usd       NUMERIC(30, 8)  NOT NULL,
    non_eth_debt_usd             NUMERIC(30, 8)  NOT NULL,
    basis_risk_collateral_usd    NUMERIC(30, 8)  NOT NULL,
    eth_down_liq_price_usd       NUMERIC(30, 8)  NULL,
    eth_up_liq_price_usd         NUMERIC(30, 8)  NULL,
    eth_liq_mode                 TEXT            NOT NULL,
    dominant_risk                TEXT            NOT NULL,
    assets_jsonb                 JSONB           NOT NULL,
    created_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("timestamp", market, user_address)
);
"""

_DDL_USER_POSITION_INDEX_MARKET_TS = """
CREATE INDEX IF NOT EXISTS {index_name}
    ON loan.{table_name} (market, "timestamp" DESC);
"""

_DDL_USER_POSITION_INDEX_USER_TS = """
CREATE INDEX IF NOT EXISTS {index_name}
    ON loan.{table_name} (user_address, "timestamp" DESC);
"""

_DDL_USER_POSITION_ASSET = """
CREATE TABLE IF NOT EXISTS loan.{table_name} (
    "timestamp"                  TIMESTAMPTZ     NOT NULL,
    block_number                 BIGINT          NOT NULL,
    market                       BYTEA           NOT NULL,
    user_address                 BYTEA           NOT NULL,
    asset                        BYTEA           NOT NULL,
    symbol                       TEXT            NULL,
    side                         TEXT            NOT NULL,
    decimals                     INTEGER         NULL,
    amount                       NUMERIC(38, 18) NOT NULL,
    price_in_base                NUMERIC(30, 8)  NULL,
    price_usd                    NUMERIC(30, 8)  NOT NULL,
    value_usd                    NUMERIC(30, 8)  NOT NULL,
    discounted_value_usd         NUMERIC(30, 8)  NOT NULL,
    borrow_collateral_factor     NUMERIC(20, 18) NULL,
    liquidate_collateral_factor  NUMERIC(20, 18) NULL,
    liquidation_factor           NUMERIC(20, 18) NULL,
    beta_to_eth                  NUMERIC(20, 8)  NOT NULL,
    is_eth_correlated            BOOLEAN         NOT NULL,
    is_basis_risk_asset          BOOLEAN         NOT NULL,
    created_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("timestamp", market, user_address, asset, side)
);
"""

_DDL_USER_POSITION_ASSET_INDEX_USER_TS = """
CREATE INDEX IF NOT EXISTS {index_name}
    ON loan.{table_name} (user_address, "timestamp" DESC);
"""

_DDL_USER_POSITION_ASSET_INDEX_MARKET_TS = """
CREATE INDEX IF NOT EXISTS {index_name}
    ON loan.{table_name} (market, "timestamp" DESC);
"""

_DDL_V3_CURRENT_POSITION = f"""
CREATE TABLE IF NOT EXISTS loan.{_V3_CURRENT_POSITION_TABLE} (
    market                       BYTEA           NOT NULL,
    user_address                 BYTEA           NOT NULL,
    symbol                       TEXT            NULL,
    last_block_number            BIGINT          NOT NULL,
    last_block_timestamp         TIMESTAMPTZ     NOT NULL,
    last_tx_hash                 TEXT            NULL,
    has_open_position            BOOLEAN         NOT NULL,
    is_liquidatable              BOOLEAN         NOT NULL,
    base_token                   BYTEA           NULL,
    base_symbol                  TEXT            NULL,
    base_price_usd               NUMERIC(30, 8)  NULL,
    eth_price_usd                NUMERIC(30, 8)  NOT NULL,
    total_collateral_usd         NUMERIC(30, 8)  NOT NULL,
    total_debt_usd               NUMERIC(30, 8)  NOT NULL,
    discounted_collateral_usd    NUMERIC(30, 8)  NOT NULL,
    liquidation_buffer_usd       NUMERIC(30, 8)  NOT NULL,
    health_factor                NUMERIC(40, 18) NOT NULL,
    eth_sensitive_collateral_usd NUMERIC(30, 8)  NOT NULL,
    eth_sensitive_debt_usd       NUMERIC(30, 8)  NOT NULL,
    net_eth_exposure_usd         NUMERIC(30, 8)  NOT NULL,
    non_eth_collateral_usd       NUMERIC(30, 8)  NOT NULL,
    non_eth_debt_usd             NUMERIC(30, 8)  NOT NULL,
    basis_risk_collateral_usd    NUMERIC(30, 8)  NOT NULL,
    eth_down_liq_price_usd       NUMERIC(30, 8)  NULL,
    eth_up_liq_price_usd         NUMERIC(30, 8)  NULL,
    eth_liq_mode                 TEXT            NOT NULL,
    dominant_risk                TEXT            NOT NULL,
    assets_jsonb                 JSONB           NOT NULL DEFAULT '[]',
    created_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, user_address)
);
"""

_DDL_V3_CURRENT_POSITION_INDEX_USER = f"""
CREATE INDEX IF NOT EXISTS idx_{_V3_CURRENT_POSITION_TABLE}_user
    ON loan.{_V3_CURRENT_POSITION_TABLE} (user_address, last_block_timestamp DESC);
"""

_DDL_V3_CURRENT_POSITION_INDEX_UPDATED = f"""
CREATE INDEX IF NOT EXISTS idx_{_V3_CURRENT_POSITION_TABLE}_updated
    ON loan.{_V3_CURRENT_POSITION_TABLE} (updated_at DESC);
"""

_DDL_V3_CURRENT_POSITION_ASSET = f"""
CREATE TABLE IF NOT EXISTS loan.{_V3_CURRENT_POSITION_ASSET_TABLE} (
    market                       BYTEA           NOT NULL,
    user_address                 BYTEA           NOT NULL,
    asset                        BYTEA           NOT NULL,
    side                         TEXT            NOT NULL,
    symbol                       TEXT            NULL,
    decimals                     INTEGER         NULL,
    amount                       NUMERIC(38, 18) NOT NULL,
    price_in_base                NUMERIC(30, 8)  NULL,
    price_usd                    NUMERIC(30, 8)  NOT NULL,
    value_usd                    NUMERIC(30, 8)  NOT NULL,
    discounted_value_usd         NUMERIC(30, 8)  NOT NULL,
    borrow_collateral_factor     NUMERIC(20, 18) NULL,
    liquidate_collateral_factor  NUMERIC(20, 18) NULL,
    liquidation_factor           NUMERIC(20, 18) NULL,
    beta_to_eth                  NUMERIC(20, 8)  NOT NULL,
    is_eth_correlated            BOOLEAN         NOT NULL,
    is_basis_risk_asset          BOOLEAN         NOT NULL,
    last_block_number            BIGINT          NOT NULL,
    last_block_timestamp         TIMESTAMPTZ     NOT NULL,
    created_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, user_address, asset, side)
);
"""

_DDL_V3_CURRENT_POSITION_ASSET_INDEX_USER = f"""
CREATE INDEX IF NOT EXISTS idx_{_V3_CURRENT_POSITION_ASSET_TABLE}_user
    ON loan.{_V3_CURRENT_POSITION_ASSET_TABLE} (user_address, last_block_timestamp DESC);
"""

_DDL_V3_CURRENT_POSITION_ASSET_INDEX_UPDATED = f"""
CREATE INDEX IF NOT EXISTS idx_{_V3_CURRENT_POSITION_ASSET_TABLE}_updated
    ON loan.{_V3_CURRENT_POSITION_ASSET_TABLE} (updated_at DESC);
"""

_DDL_V2_CURRENT_POSITION = f"""
CREATE TABLE IF NOT EXISTS loan.{_V2_CURRENT_POSITION_TABLE} (
    market                       BYTEA           NOT NULL,
    user_address                 BYTEA           NOT NULL,
    symbol                       TEXT            NULL,
    last_block_number            BIGINT          NOT NULL,
    last_block_timestamp         TIMESTAMPTZ     NOT NULL,
    last_tx_hash                 TEXT            NULL,
    has_open_position            BOOLEAN         NOT NULL,
    is_liquidatable              BOOLEAN         NOT NULL,
    base_token                   BYTEA           NULL,
    base_symbol                  TEXT            NULL,
    base_price_usd               NUMERIC(30, 8)  NULL,
    eth_price_usd                NUMERIC(30, 8)  NOT NULL,
    total_collateral_usd         NUMERIC(30, 8)  NOT NULL,
    total_debt_usd               NUMERIC(30, 8)  NOT NULL,
    discounted_collateral_usd    NUMERIC(30, 8)  NOT NULL,
    liquidation_buffer_usd       NUMERIC(30, 8)  NOT NULL,
    health_factor                NUMERIC(40, 18) NOT NULL,
    eth_sensitive_collateral_usd NUMERIC(30, 8)  NOT NULL,
    eth_sensitive_debt_usd       NUMERIC(30, 8)  NOT NULL,
    net_eth_exposure_usd         NUMERIC(30, 8)  NOT NULL,
    non_eth_collateral_usd       NUMERIC(30, 8)  NOT NULL,
    non_eth_debt_usd             NUMERIC(30, 8)  NOT NULL,
    basis_risk_collateral_usd    NUMERIC(30, 8)  NOT NULL,
    eth_down_liq_price_usd       NUMERIC(30, 8)  NULL,
    eth_up_liq_price_usd         NUMERIC(30, 8)  NULL,
    eth_liq_mode                 TEXT            NOT NULL,
    dominant_risk                TEXT            NOT NULL,
    assets_jsonb                 JSONB           NOT NULL DEFAULT '[]',
    created_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, user_address)
);
"""

_DDL_V2_CURRENT_POSITION_INDEX_USER = f"""
CREATE INDEX IF NOT EXISTS idx_{_V2_CURRENT_POSITION_TABLE}_user
    ON loan.{_V2_CURRENT_POSITION_TABLE} (user_address, last_block_timestamp DESC);
"""

_DDL_V2_CURRENT_POSITION_INDEX_UPDATED = f"""
CREATE INDEX IF NOT EXISTS idx_{_V2_CURRENT_POSITION_TABLE}_updated
    ON loan.{_V2_CURRENT_POSITION_TABLE} (updated_at DESC);
"""

_DDL_V2_CURRENT_POSITION_ASSET = f"""
CREATE TABLE IF NOT EXISTS loan.{_V2_CURRENT_POSITION_ASSET_TABLE} (
    market                       BYTEA           NOT NULL,
    user_address                 BYTEA           NOT NULL,
    asset                        BYTEA           NOT NULL,
    side                         TEXT            NOT NULL,
    symbol                       TEXT            NULL,
    decimals                     INTEGER         NULL,
    amount                       NUMERIC(38, 18) NOT NULL,
    price_in_base                NUMERIC(30, 8)  NULL,
    price_usd                    NUMERIC(30, 8)  NOT NULL,
    value_usd                    NUMERIC(30, 8)  NOT NULL,
    discounted_value_usd         NUMERIC(30, 8)  NOT NULL,
    borrow_collateral_factor     NUMERIC(20, 18) NULL,
    liquidate_collateral_factor  NUMERIC(20, 18) NULL,
    liquidation_factor           NUMERIC(20, 18) NULL,
    beta_to_eth                  NUMERIC(20, 8)  NOT NULL,
    is_eth_correlated            BOOLEAN         NOT NULL,
    is_basis_risk_asset          BOOLEAN         NOT NULL,
    last_block_number            BIGINT          NOT NULL,
    last_block_timestamp         TIMESTAMPTZ     NOT NULL,
    created_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, user_address, asset, side)
);
"""

_DDL_V2_CURRENT_POSITION_ASSET_INDEX_USER = f"""
CREATE INDEX IF NOT EXISTS idx_{_V2_CURRENT_POSITION_ASSET_TABLE}_user
    ON loan.{_V2_CURRENT_POSITION_ASSET_TABLE} (user_address, last_block_timestamp DESC);
"""

_DDL_V2_CURRENT_POSITION_ASSET_INDEX_UPDATED = f"""
CREATE INDEX IF NOT EXISTS idx_{_V2_CURRENT_POSITION_ASSET_TABLE}_updated
    ON loan.{_V2_CURRENT_POSITION_ASSET_TABLE} (updated_at DESC);
"""

_UPSERT_V3_CURRENT_POSITION = f"""
INSERT INTO loan.{_V3_CURRENT_POSITION_TABLE} (
    market, user_address, symbol, last_block_number, last_block_timestamp, last_tx_hash,
    has_open_position, is_liquidatable, base_token, base_symbol, base_price_usd,
    eth_price_usd, total_collateral_usd, total_debt_usd, discounted_collateral_usd,
    liquidation_buffer_usd, health_factor, eth_sensitive_collateral_usd, eth_sensitive_debt_usd,
    net_eth_exposure_usd, non_eth_collateral_usd, non_eth_debt_usd, basis_risk_collateral_usd,
    eth_down_liq_price_usd, eth_up_liq_price_usd, eth_liq_mode, dominant_risk, assets_jsonb
) VALUES (
    $1, $2, $3, $4, $5, $6,
    $7, $8, $9, $10, $11,
    $12, $13, $14, $15,
    $16, $17, $18, $19,
    $20, $21, $22, $23,
    $24, $25, $26, $27, $28
)
ON CONFLICT (market, user_address) DO UPDATE SET
    symbol = EXCLUDED.symbol,
    last_block_number = EXCLUDED.last_block_number,
    last_block_timestamp = EXCLUDED.last_block_timestamp,
    last_tx_hash = EXCLUDED.last_tx_hash,
    has_open_position = EXCLUDED.has_open_position,
    is_liquidatable = EXCLUDED.is_liquidatable,
    base_token = EXCLUDED.base_token,
    base_symbol = EXCLUDED.base_symbol,
    base_price_usd = EXCLUDED.base_price_usd,
    eth_price_usd = EXCLUDED.eth_price_usd,
    total_collateral_usd = EXCLUDED.total_collateral_usd,
    total_debt_usd = EXCLUDED.total_debt_usd,
    discounted_collateral_usd = EXCLUDED.discounted_collateral_usd,
    liquidation_buffer_usd = EXCLUDED.liquidation_buffer_usd,
    health_factor = EXCLUDED.health_factor,
    eth_sensitive_collateral_usd = EXCLUDED.eth_sensitive_collateral_usd,
    eth_sensitive_debt_usd = EXCLUDED.eth_sensitive_debt_usd,
    net_eth_exposure_usd = EXCLUDED.net_eth_exposure_usd,
    non_eth_collateral_usd = EXCLUDED.non_eth_collateral_usd,
    non_eth_debt_usd = EXCLUDED.non_eth_debt_usd,
    basis_risk_collateral_usd = EXCLUDED.basis_risk_collateral_usd,
    eth_down_liq_price_usd = EXCLUDED.eth_down_liq_price_usd,
    eth_up_liq_price_usd = EXCLUDED.eth_up_liq_price_usd,
    eth_liq_mode = EXCLUDED.eth_liq_mode,
    dominant_risk = EXCLUDED.dominant_risk,
    assets_jsonb = EXCLUDED.assets_jsonb,
    updated_at = NOW();
"""

_UPSERT_V3_CURRENT_POSITION_ASSET = f"""
INSERT INTO loan.{_V3_CURRENT_POSITION_ASSET_TABLE} (
    market, user_address, asset, side, symbol, decimals, amount, price_in_base, price_usd,
    value_usd, discounted_value_usd, borrow_collateral_factor, liquidate_collateral_factor,
    liquidation_factor, beta_to_eth, is_eth_correlated, is_basis_risk_asset,
    last_block_number, last_block_timestamp
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9,
    $10, $11, $12, $13,
    $14, $15, $16, $17,
    $18, $19
)
ON CONFLICT (market, user_address, asset, side) DO UPDATE SET
    symbol = EXCLUDED.symbol,
    decimals = EXCLUDED.decimals,
    amount = EXCLUDED.amount,
    price_in_base = EXCLUDED.price_in_base,
    price_usd = EXCLUDED.price_usd,
    value_usd = EXCLUDED.value_usd,
    discounted_value_usd = EXCLUDED.discounted_value_usd,
    borrow_collateral_factor = EXCLUDED.borrow_collateral_factor,
    liquidate_collateral_factor = EXCLUDED.liquidate_collateral_factor,
    liquidation_factor = EXCLUDED.liquidation_factor,
    beta_to_eth = EXCLUDED.beta_to_eth,
    is_eth_correlated = EXCLUDED.is_eth_correlated,
    is_basis_risk_asset = EXCLUDED.is_basis_risk_asset,
    last_block_number = EXCLUDED.last_block_number,
    last_block_timestamp = EXCLUDED.last_block_timestamp,
    updated_at = NOW();
"""

_UPSERT_V2_CURRENT_POSITION = f"""
INSERT INTO loan.{_V2_CURRENT_POSITION_TABLE} (
    market, user_address, symbol, last_block_number, last_block_timestamp, last_tx_hash,
    has_open_position, is_liquidatable, base_token, base_symbol, base_price_usd,
    eth_price_usd, total_collateral_usd, total_debt_usd, discounted_collateral_usd,
    liquidation_buffer_usd, health_factor, eth_sensitive_collateral_usd, eth_sensitive_debt_usd,
    net_eth_exposure_usd, non_eth_collateral_usd, non_eth_debt_usd, basis_risk_collateral_usd,
    eth_down_liq_price_usd, eth_up_liq_price_usd, eth_liq_mode, dominant_risk, assets_jsonb
) VALUES (
    $1, $2, $3, $4, $5, $6,
    $7, $8, $9, $10, $11,
    $12, $13, $14, $15,
    $16, $17, $18, $19,
    $20, $21, $22, $23,
    $24, $25, $26, $27, $28
)
ON CONFLICT (market, user_address) DO UPDATE SET
    symbol = EXCLUDED.symbol,
    last_block_number = EXCLUDED.last_block_number,
    last_block_timestamp = EXCLUDED.last_block_timestamp,
    last_tx_hash = EXCLUDED.last_tx_hash,
    has_open_position = EXCLUDED.has_open_position,
    is_liquidatable = EXCLUDED.is_liquidatable,
    base_token = EXCLUDED.base_token,
    base_symbol = EXCLUDED.base_symbol,
    base_price_usd = EXCLUDED.base_price_usd,
    eth_price_usd = EXCLUDED.eth_price_usd,
    total_collateral_usd = EXCLUDED.total_collateral_usd,
    total_debt_usd = EXCLUDED.total_debt_usd,
    discounted_collateral_usd = EXCLUDED.discounted_collateral_usd,
    liquidation_buffer_usd = EXCLUDED.liquidation_buffer_usd,
    health_factor = EXCLUDED.health_factor,
    eth_sensitive_collateral_usd = EXCLUDED.eth_sensitive_collateral_usd,
    eth_sensitive_debt_usd = EXCLUDED.eth_sensitive_debt_usd,
    net_eth_exposure_usd = EXCLUDED.net_eth_exposure_usd,
    non_eth_collateral_usd = EXCLUDED.non_eth_collateral_usd,
    non_eth_debt_usd = EXCLUDED.non_eth_debt_usd,
    basis_risk_collateral_usd = EXCLUDED.basis_risk_collateral_usd,
    eth_down_liq_price_usd = EXCLUDED.eth_down_liq_price_usd,
    eth_up_liq_price_usd = EXCLUDED.eth_up_liq_price_usd,
    eth_liq_mode = EXCLUDED.eth_liq_mode,
    dominant_risk = EXCLUDED.dominant_risk,
    assets_jsonb = EXCLUDED.assets_jsonb,
    updated_at = NOW();
"""

_UPSERT_V2_CURRENT_POSITION_ASSET = f"""
INSERT INTO loan.{_V2_CURRENT_POSITION_ASSET_TABLE} (
    market, user_address, asset, side, symbol, decimals, amount, price_in_base, price_usd,
    value_usd, discounted_value_usd, borrow_collateral_factor, liquidate_collateral_factor,
    liquidation_factor, beta_to_eth, is_eth_correlated, is_basis_risk_asset,
    last_block_number, last_block_timestamp
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9,
    $10, $11, $12, $13,
    $14, $15, $16, $17,
    $18, $19
)
ON CONFLICT (market, user_address, asset, side) DO UPDATE SET
    symbol = EXCLUDED.symbol,
    decimals = EXCLUDED.decimals,
    amount = EXCLUDED.amount,
    price_in_base = EXCLUDED.price_in_base,
    price_usd = EXCLUDED.price_usd,
    value_usd = EXCLUDED.value_usd,
    discounted_value_usd = EXCLUDED.discounted_value_usd,
    borrow_collateral_factor = EXCLUDED.borrow_collateral_factor,
    liquidate_collateral_factor = EXCLUDED.liquidate_collateral_factor,
    liquidation_factor = EXCLUDED.liquidation_factor,
    beta_to_eth = EXCLUDED.beta_to_eth,
    is_eth_correlated = EXCLUDED.is_eth_correlated,
    is_basis_risk_asset = EXCLUDED.is_basis_risk_asset,
    last_block_number = EXCLUDED.last_block_number,
    last_block_timestamp = EXCLUDED.last_block_timestamp,
    updated_at = NOW();
"""

_DDL_V2_ACTIVE_USER = f"""
CREATE TABLE IF NOT EXISTS loan.{_V2_ACTIVE_USER_TABLE} (
    user_address               BYTEA            PRIMARY KEY,
    is_active                  BOOLEAN          NOT NULL DEFAULT TRUE,
    activated_at               TIMESTAMPTZ      NULL,
    last_event_at              TIMESTAMPTZ      NULL,
    last_snapshot_at           TIMESTAMPTZ      NULL,
    deactivated_at             TIMESTAMPTZ      NULL,
    deactivate_reason          TEXT             NULL,
    last_total_collateral_usd  NUMERIC(30, 8)   NOT NULL DEFAULT 0,
    last_total_debt_usd        NUMERIC(30, 8)   NOT NULL DEFAULT 0,
    last_health_factor         NUMERIC(40, 18)  NOT NULL DEFAULT 0,
    created_at                 TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);
"""

_DDL_V2_ACTIVE_USER_INDEXES = f"""
CREATE INDEX IF NOT EXISTS idx_{_V2_ACTIVE_USER_TABLE}_active
    ON loan.{_V2_ACTIVE_USER_TABLE} (is_active, last_event_at DESC NULLS LAST);
"""

_DDL_V2_ACTIVE_RUN_STATE = f"""
CREATE TABLE IF NOT EXISTS loan.{_V2_ACTIVE_RUN_STATE_TABLE} (
    runner_name           TEXT            PRIMARY KEY,
    last_processed_date   DATE            NOT NULL,
    updated_at            TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
"""

_UPSERT_V2_ACTIVE_USER = f"""
INSERT INTO loan.{_V2_ACTIVE_USER_TABLE} (
    user_address, is_active, activated_at, last_event_at, last_snapshot_at,
    deactivated_at, deactivate_reason, last_total_collateral_usd,
    last_total_debt_usd, last_health_factor
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7, $8,
    $9, $10
)
ON CONFLICT (user_address) DO UPDATE SET
    is_active = EXCLUDED.is_active,
    activated_at = COALESCE(
        loan.compound_v2_active_users.activated_at,
        EXCLUDED.activated_at
    ),
    last_event_at = COALESCE(
        GREATEST(
            loan.compound_v2_active_users.last_event_at,
            EXCLUDED.last_event_at
        ),
        loan.compound_v2_active_users.last_event_at,
        EXCLUDED.last_event_at
    ),
    last_snapshot_at = COALESCE(
        GREATEST(
            loan.compound_v2_active_users.last_snapshot_at,
            EXCLUDED.last_snapshot_at
        ),
        loan.compound_v2_active_users.last_snapshot_at,
        EXCLUDED.last_snapshot_at
    ),
    deactivated_at = EXCLUDED.deactivated_at,
    deactivate_reason = EXCLUDED.deactivate_reason,
    last_total_collateral_usd = EXCLUDED.last_total_collateral_usd,
    last_total_debt_usd = EXCLUDED.last_total_debt_usd,
    last_health_factor = EXCLUDED.last_health_factor,
    updated_at = NOW();
"""

_UPSERT_V2_ACTIVE_RUN_STATE = f"""
INSERT INTO loan.{_V2_ACTIVE_RUN_STATE_TABLE} (
    runner_name, last_processed_date
) VALUES (
    $1, $2
)
ON CONFLICT (runner_name) DO UPDATE SET
    last_processed_date = EXCLUDED.last_processed_date,
    updated_at = NOW();
"""

_UPSERT_USER_POSITION = """
INSERT INTO loan.{table_name} (
    "timestamp", block_number, market, symbol, user_address,
    has_open_position, is_liquidatable,
    base_token, base_symbol, base_price_usd, eth_price_usd,
    total_collateral_usd, total_debt_usd, discounted_collateral_usd,
    liquidation_buffer_usd, health_factor,
    eth_sensitive_collateral_usd, eth_sensitive_debt_usd, net_eth_exposure_usd,
    non_eth_collateral_usd, non_eth_debt_usd, basis_risk_collateral_usd,
    eth_down_liq_price_usd, eth_up_liq_price_usd,
    eth_liq_mode, dominant_risk, assets_jsonb
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7,
    $8, $9, $10, $11,
    $12, $13, $14,
    $15, $16,
    $17, $18, $19,
    $20, $21, $22,
    $23, $24,
    $25, $26, $27
)
ON CONFLICT ("timestamp", market, user_address) DO UPDATE SET
    block_number = EXCLUDED.block_number,
    symbol = EXCLUDED.symbol,
    has_open_position = EXCLUDED.has_open_position,
    is_liquidatable = EXCLUDED.is_liquidatable,
    base_token = EXCLUDED.base_token,
    base_symbol = EXCLUDED.base_symbol,
    base_price_usd = EXCLUDED.base_price_usd,
    eth_price_usd = EXCLUDED.eth_price_usd,
    total_collateral_usd = EXCLUDED.total_collateral_usd,
    total_debt_usd = EXCLUDED.total_debt_usd,
    discounted_collateral_usd = EXCLUDED.discounted_collateral_usd,
    liquidation_buffer_usd = EXCLUDED.liquidation_buffer_usd,
    health_factor = EXCLUDED.health_factor,
    eth_sensitive_collateral_usd = EXCLUDED.eth_sensitive_collateral_usd,
    eth_sensitive_debt_usd = EXCLUDED.eth_sensitive_debt_usd,
    net_eth_exposure_usd = EXCLUDED.net_eth_exposure_usd,
    non_eth_collateral_usd = EXCLUDED.non_eth_collateral_usd,
    non_eth_debt_usd = EXCLUDED.non_eth_debt_usd,
    basis_risk_collateral_usd = EXCLUDED.basis_risk_collateral_usd,
    eth_down_liq_price_usd = EXCLUDED.eth_down_liq_price_usd,
    eth_up_liq_price_usd = EXCLUDED.eth_up_liq_price_usd,
    eth_liq_mode = EXCLUDED.eth_liq_mode,
    dominant_risk = EXCLUDED.dominant_risk,
    assets_jsonb = EXCLUDED.assets_jsonb,
    created_at = NOW();
"""

_UPSERT_USER_POSITION_ASSET = """
INSERT INTO loan.{table_name} (
    "timestamp", block_number, market, user_address, asset, symbol, side, decimals,
    amount, price_in_base, price_usd, value_usd, discounted_value_usd,
    borrow_collateral_factor, liquidate_collateral_factor, liquidation_factor,
    beta_to_eth, is_eth_correlated, is_basis_risk_asset
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8,
    $9, $10, $11, $12, $13,
    $14, $15, $16,
    $17, $18, $19
)
ON CONFLICT ("timestamp", market, user_address, asset, side) DO UPDATE SET
    block_number = EXCLUDED.block_number,
    symbol = EXCLUDED.symbol,
    decimals = EXCLUDED.decimals,
    amount = EXCLUDED.amount,
    price_in_base = EXCLUDED.price_in_base,
    price_usd = EXCLUDED.price_usd,
    value_usd = EXCLUDED.value_usd,
    discounted_value_usd = EXCLUDED.discounted_value_usd,
    borrow_collateral_factor = EXCLUDED.borrow_collateral_factor,
    liquidate_collateral_factor = EXCLUDED.liquidate_collateral_factor,
    liquidation_factor = EXCLUDED.liquidation_factor,
    beta_to_eth = EXCLUDED.beta_to_eth,
    is_eth_correlated = EXCLUDED.is_eth_correlated,
    is_basis_risk_asset = EXCLUDED.is_basis_risk_asset,
    created_at = NOW();
"""

_USER_POSITION_COLUMNS = (
    "timestamp",
    "block_number",
    "market",
    "symbol",
    "user_address",
    "has_open_position",
    "is_liquidatable",
    "base_token",
    "base_symbol",
    "base_price_usd",
    "eth_price_usd",
    "total_collateral_usd",
    "total_debt_usd",
    "discounted_collateral_usd",
    "liquidation_buffer_usd",
    "health_factor",
    "eth_sensitive_collateral_usd",
    "eth_sensitive_debt_usd",
    "net_eth_exposure_usd",
    "non_eth_collateral_usd",
    "non_eth_debt_usd",
    "basis_risk_collateral_usd",
    "eth_down_liq_price_usd",
    "eth_up_liq_price_usd",
    "eth_liq_mode",
    "dominant_risk",
    "assets_jsonb",
)

_USER_POSITION_ASSET_COLUMNS = (
    "timestamp",
    "block_number",
    "market",
    "user_address",
    "asset",
    "symbol",
    "side",
    "decimals",
    "amount",
    "price_in_base",
    "price_usd",
    "value_usd",
    "discounted_value_usd",
    "borrow_collateral_factor",
    "liquidate_collateral_factor",
    "liquidation_factor",
    "beta_to_eth",
    "is_eth_correlated",
    "is_basis_risk_asset",
)


async def create_pool(pg: PostgresConfig) -> asyncpg.Pool:
    return await create_asyncpg_pool(pg, min_size=1, max_size=10)


async def _try_enable_hypertable(conn: Any, table_name: str) -> None:
    """在 TimescaleDB 可用时将表升级为 hypertable；不可用则静默降级。"""
    await conn.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_extension
                WHERE extname = 'timescaledb'
            ) THEN
                PERFORM create_hypertable(
                    'loan.{table_name}',
                    'timestamp',
                    if_not_exists => TRUE,
                    migrate_data => TRUE
                );
            END IF;
        EXCEPTION
            WHEN undefined_function THEN
                -- timescaledb 未安装或版本函数签名不兼容，保持普通表
                NULL;
        END;
        $$;
        """
    )


async def _ensure_market_columns(conn: Any, table_name: str) -> None:
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ADD COLUMN IF NOT EXISTS symbol TEXT;
        """
    )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ADD COLUMN IF NOT EXISTS collateral_usd NUMERIC(30, 8);
        """
    )
    await conn.execute(
        f"""
        UPDATE loan.{table_name}
        SET collateral_usd = 0
        WHERE collateral_usd IS NULL;
        """
    )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ALTER COLUMN collateral_usd SET NOT NULL;
        """
    )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        DROP COLUMN IF EXISTS price_in_base;
        """
    )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ADD COLUMN IF NOT EXISTS price_usd NUMERIC(30, 8);
        """
    )
    await conn.execute(
        f"""
        UPDATE loan.{table_name}
        SET price_usd = CASE
            WHEN total_supply <> 0 THEN ROUND(supply_usd / total_supply, 8)
            WHEN total_borrow <> 0 THEN ROUND(borrow_usd / total_borrow, 8)
            ELSE 0
        END
        WHERE price_usd IS NULL;
        """
    )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ALTER COLUMN price_usd SET NOT NULL;
        """
    )


async def _ensure_reserve_columns(
    conn: Any, table_name: str, *, include_price_in_base: bool
) -> None:
    if include_price_in_base:
        await conn.execute(
            f"""
            ALTER TABLE loan.{table_name}
            ADD COLUMN IF NOT EXISTS price_in_base NUMERIC(30, 8);
            """
        )
    else:
        await conn.execute(
            f"""
            ALTER TABLE loan.{table_name}
            DROP COLUMN IF EXISTS price_in_base;
            """
        )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ADD COLUMN IF NOT EXISTS price_usd NUMERIC(30, 8);
        """
    )
    if include_price_in_base:
        await conn.execute(
            f"""
            UPDATE loan.{table_name}
            SET price_in_base = price_usd
            WHERE price_in_base IS NULL
              AND price_usd IS NOT NULL;
            """
        )
    await conn.execute(
        f"""
        UPDATE loan.{table_name}
        SET price_usd = CASE
            WHEN total_supply <> 0 THEN ROUND(supply_usd / total_supply, 8)
            WHEN total_borrow <> 0 THEN ROUND(borrow_usd / total_borrow, 8)
            ELSE 0
        END
        WHERE price_usd IS NULL;
        """
    )
    if include_price_in_base:
        await conn.execute(
            f"""
            ALTER TABLE loan.{table_name}
            ALTER COLUMN price_in_base SET NOT NULL;
            """
        )
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ALTER COLUMN price_usd SET NOT NULL;
        """
    )


async def ensure_market_state_tables(
    pool: asyncpg.Pool,
    protocol: str | None = None,
    use_timescaledb: bool = False,
) -> None:
    """创建 Compound market_state 表与 reserve 明细表。"""
    if protocol is None or protocol == "all":
        protocols = ["v2", "v3"]
    else:
        protocol = protocol.lower()
        if protocol not in ("v2", "v3"):
            raise ValueError(f"Unsupported protocol: {protocol}")
        protocols = [protocol]

    async with pool.acquire() as conn:
        for p in protocols:
            market_table = _MARKET_TABLES[p]
            reserve_table = _RESERVE_TABLES[p]

            await conn.execute(_DDL_MARKET.format(table_name=market_table))
            await _ensure_market_columns(conn, market_table)
            await conn.execute(
                _DDL_MARKET_INDEX_TS.format(
                    index_name=f"idx_{market_table}_ts",
                    table_name=market_table,
                )
            )
            await conn.execute(
                _DDL_MARKET_INDEX_MARKET.format(
                    index_name=f"idx_{market_table}_market_ts",
                    table_name=market_table,
                )
            )

            await conn.execute(_DDL_RESERVE.format(table_name=reserve_table))
            await _ensure_reserve_columns(
                conn, reserve_table, include_price_in_base=(p == "v3")
            )
            await conn.execute(
                _DDL_RESERVE_INDEX_MARKET_TS.format(
                    index_name=f"idx_{reserve_table}_market_ts",
                    table_name=reserve_table,
                )
            )
            await conn.execute(
                _DDL_RESERVE_INDEX_RESERVE_TS.format(
                    index_name=f"idx_{reserve_table}_reserve_ts",
                    table_name=reserve_table,
                )
            )

            if p == "v3":
                await conn.execute(_DDL_MARKET_CONFIG)
                await conn.execute(_DDL_MARKET_CONFIG_INDEX_TS)
                await conn.execute(_DDL_MARKET_CONFIG_ASSET)
                await conn.execute(_DDL_MARKET_CONFIG_ASSET_INDEX)
                await conn.execute(_DDL_MARKET_STATUS)
                await conn.execute(_DDL_MARKET_STATUS_INDEX)
            if p == "v2":
                await conn.execute(_DDL_V2_MARKET_CONFIG)
                await conn.execute(_DDL_V2_MARKET_CONFIG_INDEX)
                await conn.execute(_DDL_V2_PROTOCOL_CONFIG)
                await conn.execute(_DDL_V2_PROTOCOL_CONFIG_INDEX)

            if use_timescaledb:
                await _try_enable_hypertable(conn, market_table)
                await _try_enable_hypertable(conn, reserve_table)
                if p == "v3":
                    await _try_enable_hypertable(conn, _MARKET_STATUS_TABLE)

            logger.info(
                "Compound market_state tables ready: %s, %s (timescaledb=%s)",
                market_table,
                reserve_table,
                use_timescaledb,
            )
            if p == "v3":
                logger.info(
                    "Compound governance tables ready: %s, %s, %s",
                    _MARKET_CONFIG_TABLE,
                    _MARKET_CONFIG_ASSET_TABLE,
                    _MARKET_STATUS_TABLE,
                )
            if p == "v2":
                logger.info(
                    "Compound v2 config tables ready: %s, %s",
                    _V2_MARKET_CONFIG_TABLE,
                    _V2_PROTOCOL_CONFIG_TABLE,
                )


def market_table_name(protocol: str) -> str:
    p = protocol.lower()
    if p not in _MARKET_TABLES:
        raise ValueError(f"Unsupported protocol: {protocol}")
    return _MARKET_TABLES[p]


def reserve_table_name(protocol: str) -> str:
    p = protocol.lower()
    if p not in _RESERVE_TABLES:
        raise ValueError(f"Unsupported protocol: {protocol}")
    return _RESERVE_TABLES[p]


def user_position_table_name(protocol: str) -> str:
    p = protocol.lower()
    if p not in _USER_POSITION_TABLES:
        raise ValueError(f"Unsupported protocol: {protocol}")
    return _USER_POSITION_TABLES[p]


def user_position_asset_table_name(protocol: str) -> str:
    p = protocol.lower()
    if p not in _USER_POSITION_ASSET_TABLES:
        raise ValueError(f"Unsupported protocol: {protocol}")
    return _USER_POSITION_ASSET_TABLES[p]


async def upsert_market_snapshots(
    pool: asyncpg.Pool,
    protocol: str,
    rows: list[MarketSnapshotRow],
) -> int:
    if not rows:
        return 0
    table_name = market_table_name(protocol)
    sql = _UPSERT_MARKET.format(table_name=table_name)
    values = [
        (
            r.timestamp,
            r.market,
            r.symbol,
            r.total_supply,
            r.total_borrow,
            r.collateral_usd,
            r.utilization,
            r.borrow_rate,
            r.supply_rate,
            r.price_usd,
            r.supply_usd,
            r.borrow_usd,
        )
        for r in rows
    ]
    async with pool.acquire() as conn:
        await conn.executemany(sql, values)
    return len(rows)


async def upsert_reserve_snapshots(
    pool: asyncpg.Pool,
    protocol: str,
    rows: list[ReserveSnapshotRow],
) -> int:
    if not rows:
        return 0
    p = protocol.lower()
    table_name = reserve_table_name(p)
    if p == "v2":
        sql = _UPSERT_RESERVE_V2.format(table_name=table_name)
        values = [
            (
                r.timestamp,
                r.market,
                r.reserve,
                r.symbol,
                r.decimals,
                r.total_supply,
                r.total_borrow,
                r.utilization,
                r.borrow_rate,
                r.supply_rate,
                r.price_usd,
                r.supply_usd,
                r.borrow_usd,
            )
            for r in rows
        ]
    else:
        sql = _UPSERT_RESERVE.format(table_name=table_name)
        values = [
            (
                r.timestamp,
                r.market,
                r.reserve,
                r.symbol,
                r.decimals,
                r.total_supply,
                r.total_borrow,
                r.utilization,
                r.borrow_rate,
                r.supply_rate,
                r.price_in_base,
                r.price_usd,
                r.supply_usd,
                r.borrow_usd,
            )
            for r in rows
        ]
    async with pool.acquire() as conn:
        await conn.executemany(sql, values)
    return len(rows)


async def fetch_existing_governance_markets(
    pool: asyncpg.Pool,
    point_ts: datetime,
    markets: list[bytes],
) -> tuple[set[bytes], set[bytes]]:
    if not markets:
        return set(), set()
    async with pool.acquire() as conn:
        status_rows = await conn.fetch(
            f"""
            SELECT market
            FROM loan.{_MARKET_STATUS_TABLE}
            WHERE "timestamp" = $1
              AND market = ANY($2::bytea[])
            """,
            point_ts,
            markets,
        )
        config_rows = await conn.fetch(
            f"""
            SELECT DISTINCT market
            FROM loan.{_MARKET_CONFIG_TABLE}
            WHERE market = ANY($1::bytea[])
              AND effective_timestamp <= $2
            """,
            markets,
            point_ts,
        )
    return (
        {bytes(row["market"]) for row in status_rows},
        {bytes(row["market"]) for row in config_rows},
    )


async def fetch_existing_v2_config_markets(
    pool: asyncpg.Pool,
    point_ts: datetime,
    markets: list[bytes],
) -> set[bytes]:
    if not markets:
        return set()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT DISTINCT market
            FROM loan.{_V2_MARKET_CONFIG_TABLE}
            WHERE market = ANY($1::bytea[])
              AND effective_timestamp <= $2
            """,
            markets,
            point_ts,
        )
    return {bytes(row["market"]) for row in rows}


async def upsert_market_config_versions(
    pool: asyncpg.Pool,
    rows: list[MarketConfigVersionRow],
) -> int:
    if not rows:
        return 0
    values = [
        (
            r.market,
            r.symbol,
            r.effective_timestamp,
            r.block_number,
            r.config_hash,
            r.configurator,
            r.factory,
            r.governor,
            r.pause_guardian,
            r.base_token,
            r.base_token_symbol,
            r.base_token_price_feed,
            r.extension_delegate,
            r.base_scale,
            r.base_decimals,
            r.supply_kink,
            r.supply_per_year_interest_rate_slope_low,
            r.supply_per_year_interest_rate_slope_high,
            r.supply_per_year_interest_rate_base,
            r.borrow_kink,
            r.borrow_per_year_interest_rate_slope_low,
            r.borrow_per_year_interest_rate_slope_high,
            r.borrow_per_year_interest_rate_base,
            r.store_front_price_factor,
            r.tracking_index_scale,
            r.base_tracking_supply_speed,
            r.base_tracking_borrow_speed,
            r.base_min_for_rewards,
            r.base_borrow_min,
            r.target_reserves,
            json.dumps(r.raw_config_jsonb, ensure_ascii=False),
        )
        for r in rows
    ]
    async with pool.acquire() as conn:
        await conn.executemany(_UPSERT_MARKET_CONFIG, values)
    return len(rows)


async def upsert_market_config_asset_rows(
    pool: asyncpg.Pool,
    rows: list[MarketConfigAssetRow],
) -> int:
    if not rows:
        return 0
    values = [
        (
            r.market,
            r.config_hash,
            r.asset,
            r.symbol,
            r.price_feed,
            r.decimals,
            r.borrow_collateral_factor,
            r.liquidate_collateral_factor,
            r.liquidation_factor,
            r.supply_cap,
            json.dumps(r.raw_config_jsonb, ensure_ascii=False),
        )
        for r in rows
    ]
    async with pool.acquire() as conn:
        await conn.executemany(_UPSERT_MARKET_CONFIG_ASSET, values)
    return len(rows)


async def upsert_market_status_snapshots(
    pool: asyncpg.Pool,
    rows: list[MarketStatusSnapshotRow],
) -> int:
    if not rows:
        return 0
    values = [
        (
            r.timestamp,
            r.block_number,
            r.market,
            r.symbol,
            r.pause_flags,
            r.base_supply_index,
            r.base_borrow_index,
            r.tracking_supply_index,
            r.tracking_borrow_index,
            r.total_supply_base,
            r.total_borrow_base,
            r.last_accrual_time,
            json.dumps(r.raw_status_jsonb, ensure_ascii=False),
        )
        for r in rows
    ]
    async with pool.acquire() as conn:
        await conn.executemany(_UPSERT_MARKET_STATUS, values)
    return len(rows)


async def upsert_v2_market_config_versions(
    pool: asyncpg.Pool,
    rows: list[V2MarketConfigVersionRow],
) -> int:
    if not rows:
        return 0
    values = [
        (
            r.market,
            r.symbol,
            r.effective_timestamp,
            r.block_number,
            r.config_hash,
            r.comptroller,
            r.interest_rate_model,
            r.underlying,
            r.underlying_symbol,
            r.ctoken_decimals,
            r.underlying_decimals,
            r.collateral_factor,
            r.reserve_factor,
            r.liquidation_threshold,
            r.borrow_cap,
            r.supply_cap,
            r.is_listed,
            r.is_comped,
            r.is_deprecated,
            json.dumps(r.raw_config_jsonb, ensure_ascii=False),
        )
        for r in rows
    ]
    async with pool.acquire() as conn:
        await conn.executemany(_UPSERT_V2_MARKET_CONFIG, values)
    return len(rows)


async def upsert_v2_protocol_config_versions(
    pool: asyncpg.Pool,
    rows: list[V2ProtocolConfigVersionRow],
) -> int:
    if not rows:
        return 0
    values = [
        (
            r.effective_timestamp,
            r.block_number,
            r.config_hash,
            r.comptroller,
            r.price_oracle,
            r.close_factor,
            r.liquidation_incentive,
            r.pause_guardian,
            r.transfer_paused,
            r.seize_paused,
            r.mint_paused,
            r.borrow_paused,
            json.dumps(r.raw_config_jsonb, ensure_ascii=False),
        )
        for r in rows
    ]
    async with pool.acquire() as conn:
        await conn.executemany(_UPSERT_V2_PROTOCOL_CONFIG, values)
    return len(rows)


async def ensure_user_position_snapshot_tables(
    pool: asyncpg.Pool,
    protocol: str = "v3",
    use_timescaledb: bool = False,
) -> None:
    user_table = user_position_table_name(protocol)
    user_asset_table = user_position_asset_table_name(protocol)
    async with pool.acquire() as conn:
        await conn.execute(_DDL_USER_POSITION.format(table_name=user_table))
        await conn.execute(
            _DDL_USER_POSITION_INDEX_MARKET_TS.format(
                index_name=f"idx_{user_table}_market_ts",
                table_name=user_table,
            )
        )
        await conn.execute(
            _DDL_USER_POSITION_INDEX_USER_TS.format(
                index_name=f"idx_{user_table}_user_ts",
                table_name=user_table,
            )
        )

        await conn.execute(_DDL_USER_POSITION_ASSET.format(table_name=user_asset_table))
        await conn.execute(
            _DDL_USER_POSITION_ASSET_INDEX_USER_TS.format(
                index_name=f"idx_{user_asset_table}_user_ts",
                table_name=user_asset_table,
            )
        )
        await conn.execute(
            _DDL_USER_POSITION_ASSET_INDEX_MARKET_TS.format(
                index_name=f"idx_{user_asset_table}_market_ts",
                table_name=user_asset_table,
            )
        )

        if use_timescaledb:
            await _try_enable_hypertable(conn, user_table)
            await _try_enable_hypertable(conn, user_asset_table)

    logger.info(
        "Compound user position snapshot tables ready: %s, %s (timescaledb=%s)",
        user_table,
        user_asset_table,
        use_timescaledb,
    )


async def ensure_compound_v3_current_position_tables(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_DDL_V3_CURRENT_POSITION)
        await conn.execute(_DDL_V3_CURRENT_POSITION_INDEX_USER)
        await conn.execute(_DDL_V3_CURRENT_POSITION_INDEX_UPDATED)
        await conn.execute(_DDL_V3_CURRENT_POSITION_ASSET)
        await conn.execute(_DDL_V3_CURRENT_POSITION_ASSET_INDEX_USER)
        await conn.execute(_DDL_V3_CURRENT_POSITION_ASSET_INDEX_UPDATED)
    logger.info(
        "Compound v3 current position tables ready: %s, %s",
        _V3_CURRENT_POSITION_TABLE,
        _V3_CURRENT_POSITION_ASSET_TABLE,
    )


async def ensure_compound_v2_current_position_tables(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_DDL_V2_CURRENT_POSITION)
        await conn.execute(_DDL_V2_CURRENT_POSITION_INDEX_USER)
        await conn.execute(_DDL_V2_CURRENT_POSITION_INDEX_UPDATED)
        await conn.execute(_DDL_V2_CURRENT_POSITION_ASSET)
        await conn.execute(_DDL_V2_CURRENT_POSITION_ASSET_INDEX_USER)
        await conn.execute(_DDL_V2_CURRENT_POSITION_ASSET_INDEX_UPDATED)
    logger.info(
        "Compound v2 current position tables ready: %s, %s",
        _V2_CURRENT_POSITION_TABLE,
        _V2_CURRENT_POSITION_ASSET_TABLE,
    )


async def ensure_compound_v2_active_user_table(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_DDL_V2_ACTIVE_USER)
        await conn.execute(_DDL_V2_ACTIVE_USER_INDEXES)
    logger.info(
        "Compound v2 active user table ready: loan.%s",
        _V2_ACTIVE_USER_TABLE,
    )


async def ensure_compound_v2_active_run_state_table(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_DDL_V2_ACTIVE_RUN_STATE)
    logger.info(
        "Compound v2 run-state table ready: loan.%s",
        _V2_ACTIVE_RUN_STATE_TABLE,
    )


async def fetch_compound_v2_active_users(
    pool: asyncpg.Pool,
    *,
    include_inactive: bool = False,
) -> list[bytes]:
    where_clause = "" if include_inactive else "WHERE is_active = TRUE"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT user_address
            FROM loan.{_V2_ACTIVE_USER_TABLE}
            {where_clause}
            ORDER BY last_event_at DESC NULLS LAST, user_address
            """
        )
    return [bytes(row["user_address"]) for row in rows]


async def activate_compound_v2_users(
    pool: asyncpg.Pool,
    user_addresses: list[bytes],
    *,
    event_timestamp: datetime | None = None,
) -> int:
    unique_addresses = list(dict.fromkeys(user_addresses))
    if not unique_addresses:
        return 0
    rows = [
        (
            user_address,
            True,
            event_timestamp,
            event_timestamp,
            None,
            None,
            None,
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
        )
        for user_address in unique_addresses
    ]
    async with pool.acquire() as conn:
        await conn.executemany(_UPSERT_V2_ACTIVE_USER, rows)
    return len(unique_addresses)


async def activate_compound_v2_users_with_event_rows(
    pool: asyncpg.Pool,
    event_rows: list[tuple[bytes, datetime]],
) -> int:
    if not event_rows:
        return 0
    # Deduplicate by user and keep latest event time per day-window.
    latest_event_by_user: dict[bytes, datetime] = {}
    for user_address, event_timestamp in event_rows:
        existing = latest_event_by_user.get(user_address)
        if existing is None or event_timestamp > existing:
            latest_event_by_user[user_address] = event_timestamp

    rows = [
        (
            user_address,
            True,
            event_timestamp,
            event_timestamp,
            None,
            None,
            None,
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
        )
        for user_address, event_timestamp in latest_event_by_user.items()
    ]
    async with pool.acquire() as conn:
        await conn.executemany(_UPSERT_V2_ACTIVE_USER, rows)
    return len(rows)


async def fetch_compound_v2_users_from_history_day(
    pool: asyncpg.Pool,
    *,
    day_start: datetime,
    day_end: datetime,
) -> list[tuple[bytes, datetime]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT from_address AS user_address, MAX(block_timestamp) AS last_event_at
            FROM compound.compound_history
            WHERE version = 2
              AND from_address IS NOT NULL
              AND block_timestamp >= $1
              AND block_timestamp <= $2
            GROUP BY from_address
            ORDER BY last_event_at DESC
            """,
            day_start,
            day_end,
        )
    return [
        (bytes(row["user_address"]), row["last_event_at"])
        for row in rows
        if row["user_address"] is not None
        and isinstance(row["last_event_at"], datetime)
    ]


async def refresh_compound_v2_active_users_from_snapshots(
    pool: asyncpg.Pool,
    snapshot_rows: list[UserPositionSnapshotRow],
    *,
    point_ts: datetime,
    dust_threshold_usd: Decimal = Decimal("1"),
) -> int:
    if not snapshot_rows:
        return 0

    aggregated: dict[bytes, tuple[bool, Decimal, Decimal, Decimal]] = {}
    for row in snapshot_rows:
        total_collateral = Decimal(row.total_collateral_usd)
        total_debt = Decimal(row.total_debt_usd)
        health_factor = Decimal(row.health_factor)
        is_active = bool(
            row.has_open_position
            and (
                total_collateral > dust_threshold_usd or total_debt > dust_threshold_usd
            )
        )
        existing = aggregated.get(row.user_address)
        if existing is None:
            aggregated[row.user_address] = (
                is_active,
                total_collateral,
                total_debt,
                health_factor,
            )
            continue
        aggregated[row.user_address] = (
            existing[0] or is_active,
            max(existing[1], total_collateral),
            max(existing[2], total_debt),
            max(existing[3], health_factor),
        )

    upsert_rows = []
    for user_address, (
        is_active,
        total_collateral,
        total_debt,
        health_factor,
    ) in aggregated.items():
        upsert_rows.append(
            (
                user_address,
                is_active,
                point_ts if is_active else None,
                None,
                point_ts,
                None if is_active else point_ts,
                None if is_active else "closed_after_snapshot",
                total_collateral,
                total_debt,
                health_factor,
            )
        )

    async with pool.acquire() as conn:
        await conn.executemany(_UPSERT_V2_ACTIVE_USER, upsert_rows)
    return len(upsert_rows)


_SELECT_V2_AFFECTED_USERS_FROM_EVENTS = """
WITH affected AS (
    SELECT minter AS user_address, block_timestamp
    FROM compound.compound_mint
    WHERE version = 2
      AND block_timestamp >= $1
      AND block_timestamp <= $2
    UNION ALL
    SELECT redeemer AS user_address, block_timestamp
    FROM compound.compound_redeem
    WHERE version = 2
      AND block_timestamp >= $1
      AND block_timestamp <= $2
    UNION ALL
    SELECT borrower AS user_address, block_timestamp
    FROM compound.compound_borrow
    WHERE version = 2
      AND block_timestamp >= $1
      AND block_timestamp <= $2
    UNION ALL
    SELECT borrower AS user_address, block_timestamp
    FROM compound.compound_repay
    WHERE version = 2
      AND block_timestamp >= $1
      AND block_timestamp <= $2
    UNION ALL
    SELECT payer AS user_address, block_timestamp
    FROM compound.compound_repay
    WHERE version = 2
      AND block_timestamp >= $1
      AND block_timestamp <= $2
    UNION ALL
    SELECT borrower AS user_address, block_timestamp
    FROM compound.compound_liquidate
    WHERE version = 2
      AND block_timestamp >= $1
      AND block_timestamp <= $2
    UNION ALL
    SELECT liquidator AS user_address, block_timestamp
    FROM compound.compound_liquidate
    WHERE version = 2
      AND block_timestamp >= $1
      AND block_timestamp <= $2
)
SELECT user_address, MAX(block_timestamp) AS last_event_at
FROM affected
WHERE user_address IS NOT NULL
GROUP BY user_address
"""


async def activate_compound_v2_users_from_events(
    pool: asyncpg.Pool,
    *,
    from_dt: datetime,
    to_dt: datetime,
) -> int:
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SELECT_V2_AFFECTED_USERS_FROM_EVENTS, from_dt, to_dt)
    if not rows:
        return 0
    upsert_rows = [
        (
            bytes(row["user_address"]),
            True,
            row["last_event_at"],
            row["last_event_at"],
            None,
            None,
            None,
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
        )
        for row in rows
    ]
    async with pool.acquire() as conn:
        await conn.executemany(_UPSERT_V2_ACTIVE_USER, upsert_rows)
    return len(upsert_rows)


async def fetch_compound_v2_users_affected_by_events(
    pool: asyncpg.Pool,
    *,
    from_dt: datetime,
    to_dt: datetime,
) -> list[bytes]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SELECT_V2_AFFECTED_USERS_FROM_EVENTS, from_dt, to_dt)
    return [
        bytes(row["user_address"]) for row in rows if row["user_address"] is not None
    ]


async def fetch_compound_v2_users_from_detail_tables_day(
    pool: asyncpg.Pool,
    *,
    day_start: datetime,
    day_end: datetime,
) -> list[tuple[bytes, datetime]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            _SELECT_V2_AFFECTED_USERS_FROM_EVENTS,
            day_start,
            day_end,
        )
    return [
        (bytes(row["user_address"]), row["last_event_at"])
        for row in rows
        if row["user_address"] is not None
        and isinstance(row["last_event_at"], datetime)
    ]


async def fetch_existing_user_position_addresses(
    pool: asyncpg.Pool,
    point_ts: datetime,
    market: bytes,
    user_addresses: list[bytes],
    protocol: str = "v3",
) -> set[bytes]:
    if not user_addresses:
        return set()
    user_table = user_position_table_name(protocol)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT user_address
            FROM loan.{user_table}
            WHERE "timestamp" = $1
              AND market = $2
              AND user_address = ANY($3::bytea[])
            """,
            point_ts,
            market,
            user_addresses,
        )
    return {bytes(row["user_address"]) for row in rows}


async def fetch_user_position_snapshots_at_timestamp(
    pool: asyncpg.Pool,
    *,
    point_ts: datetime,
    protocol: str = "v3",
) -> list[UserPositionSnapshotRow]:
    user_table = user_position_table_name(protocol)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT *
            FROM loan.{user_table}
            WHERE "timestamp" = $1
            ORDER BY market, user_address
            """,
            point_ts,
        )
    return [
        UserPositionSnapshotRow(
            timestamp=row["timestamp"],
            block_number=int(row["block_number"]),
            market=bytes(row["market"]),
            symbol=row["symbol"],
            user_address=bytes(row["user_address"]),
            has_open_position=bool(row["has_open_position"]),
            is_liquidatable=bool(row["is_liquidatable"]),
            base_token=bytes(row["base_token"])
            if row["base_token"] is not None
            else b"",
            base_symbol=row["base_symbol"],
            base_price_usd=Decimal(row["base_price_usd"] or 0),
            eth_price_usd=Decimal(row["eth_price_usd"]),
            total_collateral_usd=Decimal(row["total_collateral_usd"]),
            total_debt_usd=Decimal(row["total_debt_usd"]),
            discounted_collateral_usd=Decimal(row["discounted_collateral_usd"]),
            liquidation_buffer_usd=Decimal(row["liquidation_buffer_usd"]),
            health_factor=Decimal(row["health_factor"]),
            eth_sensitive_collateral_usd=Decimal(row["eth_sensitive_collateral_usd"]),
            eth_sensitive_debt_usd=Decimal(row["eth_sensitive_debt_usd"]),
            net_eth_exposure_usd=Decimal(row["net_eth_exposure_usd"]),
            non_eth_collateral_usd=Decimal(row["non_eth_collateral_usd"]),
            non_eth_debt_usd=Decimal(row["non_eth_debt_usd"]),
            basis_risk_collateral_usd=Decimal(row["basis_risk_collateral_usd"]),
            eth_down_liq_price_usd=(
                Decimal(row["eth_down_liq_price_usd"])
                if row["eth_down_liq_price_usd"] is not None
                else None
            ),
            eth_up_liq_price_usd=(
                Decimal(row["eth_up_liq_price_usd"])
                if row["eth_up_liq_price_usd"] is not None
                else None
            ),
            eth_liq_mode=str(row["eth_liq_mode"]),
            dominant_risk=str(row["dominant_risk"]),
            assets_jsonb=(
                json.loads(row["assets_jsonb"])
                if isinstance(row["assets_jsonb"], str)
                else list(row["assets_jsonb"])
            ),
        )
        for row in rows
    ]


async def fetch_latest_user_position_snapshot_timestamp(
    pool: asyncpg.Pool,
    *,
    protocol: str = "v3",
) -> datetime | None:
    user_table = user_position_table_name(protocol)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f'SELECT MAX("timestamp") AS max_ts FROM loan.{user_table}'
        )
    value = row["max_ts"] if row is not None else None
    return value if isinstance(value, datetime) else None


async def fetch_earliest_compound_event_timestamp(
    pool: asyncpg.Pool,
    *,
    protocol: str,
) -> datetime | None:
    version = 2 if protocol == "v2" else 3
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT MIN(block_timestamp) AS min_ts
            FROM compound.compound_history
            WHERE version = $1
            """,
            version,
        )
    value = row["min_ts"] if row is not None else None
    return value if isinstance(value, datetime) else None


async def fetch_compound_v2_run_watermark(
    pool: asyncpg.Pool,
    *,
    runner_name: str,
) -> date_type | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT last_processed_date
            FROM loan.{_V2_ACTIVE_RUN_STATE_TABLE}
            WHERE runner_name = $1
            """,
            runner_name,
        )
    value = row["last_processed_date"] if row is not None else None
    return value if isinstance(value, date_type) else None


async def upsert_compound_v2_run_watermark(
    pool: asyncpg.Pool,
    *,
    runner_name: str,
    processed_date: date_type,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            _UPSERT_V2_ACTIVE_RUN_STATE,
            runner_name,
            processed_date,
        )


async def upsert_user_position_snapshots(
    pool: asyncpg.Pool,
    rows: list[UserPositionSnapshotRow],
    protocol: str = "v3",
) -> int:
    if not rows:
        return 0
    user_table = user_position_table_name(protocol)
    values = [
        (
            r.timestamp,
            r.block_number,
            r.market,
            r.symbol,
            r.user_address,
            r.has_open_position,
            r.is_liquidatable,
            r.base_token,
            r.base_symbol,
            r.base_price_usd,
            r.eth_price_usd,
            r.total_collateral_usd,
            r.total_debt_usd,
            r.discounted_collateral_usd,
            r.liquidation_buffer_usd,
            r.health_factor,
            r.eth_sensitive_collateral_usd,
            r.eth_sensitive_debt_usd,
            r.net_eth_exposure_usd,
            r.non_eth_collateral_usd,
            r.non_eth_debt_usd,
            r.basis_risk_collateral_usd,
            r.eth_down_liq_price_usd,
            r.eth_up_liq_price_usd,
            r.eth_liq_mode,
            r.dominant_risk,
            json.dumps(r.assets_jsonb, ensure_ascii=False),
        )
        for r in rows
    ]

    delete_groups: dict[tuple[datetime, bytes], list[bytes]] = defaultdict(list)
    for row in rows:
        delete_groups[(row.timestamp, row.market)].append(row.user_address)

    async with pool.acquire() as conn:
        async with conn.transaction():
            for (timestamp, market), user_addresses in delete_groups.items():
                await conn.execute(
                    f"""
                    DELETE FROM loan.{user_table}
                    WHERE "timestamp" = $1
                      AND market = $2
                      AND user_address = ANY($3::bytea[])
                    """,
                    timestamp,
                    market,
                    user_addresses,
                )
            await conn.copy_records_to_table(
                user_table,
                schema_name="loan",
                records=values,
                columns=list(_USER_POSITION_COLUMNS),
            )
    return len(rows)


async def upsert_user_position_asset_rows(
    pool: asyncpg.Pool,
    rows: list[UserPositionAssetRow],
    protocol: str = "v3",
) -> int:
    if not rows:
        return 0
    user_asset_table = user_position_asset_table_name(protocol)
    values = [
        (
            r.timestamp,
            r.block_number,
            r.market,
            r.user_address,
            r.asset,
            r.symbol,
            r.side,
            r.decimals,
            r.amount,
            r.price_in_base,
            r.price_usd,
            r.value_usd,
            r.discounted_value_usd,
            r.borrow_collateral_factor,
            r.liquidate_collateral_factor,
            r.liquidation_factor,
            r.beta_to_eth,
            r.is_eth_correlated,
            r.is_basis_risk_asset,
        )
        for r in rows
    ]

    delete_groups: dict[tuple[datetime, bytes], list[bytes]] = defaultdict(list)
    for row in rows:
        delete_groups[(row.timestamp, row.market)].append(row.user_address)

    async with pool.acquire() as conn:
        async with conn.transaction():
            for (timestamp, market), user_addresses in delete_groups.items():
                await conn.execute(
                    f"""
                    DELETE FROM loan.{user_asset_table}
                    WHERE "timestamp" = $1
                      AND market = $2
                      AND user_address = ANY($3::bytea[])
                    """,
                    timestamp,
                    market,
                    user_addresses,
                )
            await conn.copy_records_to_table(
                user_asset_table,
                schema_name="loan",
                records=values,
                columns=list(_USER_POSITION_ASSET_COLUMNS),
            )
    return len(rows)


def _current_position_key(
    market: bytes,
    user_address: bytes,
) -> tuple[bytes, bytes]:
    return market, user_address


def _is_newer_current_state(
    *,
    existing_block_number: int | None,
    existing_block_timestamp: datetime | None,
    incoming_block_number: int,
    incoming_block_timestamp: datetime,
) -> bool:
    if existing_block_number is None:
        return True
    if incoming_block_number > existing_block_number:
        return True
    if incoming_block_number < existing_block_number:
        return False
    if existing_block_timestamp is None:
        return True
    return incoming_block_timestamp >= existing_block_timestamp


async def refresh_compound_v3_current_positions(
    pool: asyncpg.Pool,
    snapshot_rows: list[UserPositionSnapshotRow],
    asset_rows: list[UserPositionAssetRow],
    *,
    tx_hash_by_key: dict[tuple[bytes, bytes], str] | None = None,
) -> int:
    if not snapshot_rows:
        return 0

    latest_snapshots: dict[tuple[bytes, bytes], UserPositionSnapshotRow] = {}
    for row in snapshot_rows:
        key = _current_position_key(row.market, row.user_address)
        existing = latest_snapshots.get(key)
        if existing is None or _is_newer_current_state(
            existing_block_number=existing.block_number,
            existing_block_timestamp=existing.timestamp,
            incoming_block_number=row.block_number,
            incoming_block_timestamp=row.timestamp,
        ):
            latest_snapshots[key] = row

    latest_asset_groups: dict[tuple[bytes, bytes], list[UserPositionAssetRow]] = (
        defaultdict(list)
    )
    for row in asset_rows:
        key = _current_position_key(row.market, row.user_address)
        snapshot = latest_snapshots.get(key)
        if snapshot is None:
            continue
        if (
            row.block_number != snapshot.block_number
            or row.timestamp != snapshot.timestamp
        ):
            continue
        latest_asset_groups[key].append(row)

    markets = [key[0] for key in latest_snapshots]
    users = [key[1] for key in latest_snapshots]
    async with pool.acquire() as conn:
        existing_rows = await conn.fetch(
            f"""
            SELECT market, user_address, last_block_number, last_block_timestamp
            FROM loan.{_V3_CURRENT_POSITION_TABLE}
            WHERE market = ANY($1::bytea[])
              AND user_address = ANY($2::bytea[])
            """,
            markets,
            users,
        )

        existing_map = {
            _current_position_key(bytes(row["market"]), bytes(row["user_address"])): (
                int(row["last_block_number"]),
                row["last_block_timestamp"],
            )
            for row in existing_rows
        }

        accepted_snapshots: dict[tuple[bytes, bytes], UserPositionSnapshotRow] = {}
        for key, row in latest_snapshots.items():
            existing_meta = existing_map.get(key)
            if _is_newer_current_state(
                existing_block_number=(
                    existing_meta[0] if existing_meta is not None else None
                ),
                existing_block_timestamp=(
                    existing_meta[1] if existing_meta is not None else None
                ),
                incoming_block_number=row.block_number,
                incoming_block_timestamp=row.timestamp,
            ):
                accepted_snapshots[key] = row

        if not accepted_snapshots:
            return 0

        open_position_values: list[tuple[object, ...]] = []
        open_asset_values: list[tuple[object, ...]] = []
        tx_hash_map = tx_hash_by_key or {}

        async with conn.transaction():
            for key, row in accepted_snapshots.items():
                await conn.execute(
                    f"""
                    DELETE FROM loan.{_V3_CURRENT_POSITION_ASSET_TABLE}
                    WHERE market = $1 AND user_address = $2
                    """,
                    row.market,
                    row.user_address,
                )
                if not row.has_open_position:
                    await conn.execute(
                        f"""
                        DELETE FROM loan.{_V3_CURRENT_POSITION_TABLE}
                        WHERE market = $1 AND user_address = $2
                        """,
                        row.market,
                        row.user_address,
                    )
                    continue

                open_position_values.append(
                    (
                        row.market,
                        row.user_address,
                        row.symbol,
                        row.block_number,
                        row.timestamp,
                        tx_hash_map.get(key),
                        row.has_open_position,
                        row.is_liquidatable,
                        row.base_token or None,
                        row.base_symbol,
                        row.base_price_usd,
                        row.eth_price_usd,
                        row.total_collateral_usd,
                        row.total_debt_usd,
                        row.discounted_collateral_usd,
                        row.liquidation_buffer_usd,
                        row.health_factor,
                        row.eth_sensitive_collateral_usd,
                        row.eth_sensitive_debt_usd,
                        row.net_eth_exposure_usd,
                        row.non_eth_collateral_usd,
                        row.non_eth_debt_usd,
                        row.basis_risk_collateral_usd,
                        row.eth_down_liq_price_usd,
                        row.eth_up_liq_price_usd,
                        row.eth_liq_mode,
                        row.dominant_risk,
                        json.dumps(row.assets_jsonb, ensure_ascii=False),
                    )
                )

                for asset_row in latest_asset_groups.get(key, []):
                    open_asset_values.append(
                        (
                            asset_row.market,
                            asset_row.user_address,
                            asset_row.asset,
                            asset_row.side,
                            asset_row.symbol,
                            asset_row.decimals,
                            asset_row.amount,
                            asset_row.price_in_base,
                            asset_row.price_usd,
                            asset_row.value_usd,
                            asset_row.discounted_value_usd,
                            asset_row.borrow_collateral_factor,
                            asset_row.liquidate_collateral_factor,
                            asset_row.liquidation_factor,
                            asset_row.beta_to_eth,
                            asset_row.is_eth_correlated,
                            asset_row.is_basis_risk_asset,
                            asset_row.block_number,
                            asset_row.timestamp,
                        )
                    )

            if open_position_values:
                await conn.executemany(
                    _UPSERT_V3_CURRENT_POSITION,
                    open_position_values,
                )
            if open_asset_values:
                await conn.executemany(
                    _UPSERT_V3_CURRENT_POSITION_ASSET,
                    open_asset_values,
                )

    return len(accepted_snapshots)


async def refresh_compound_v2_current_positions(
    pool: asyncpg.Pool,
    snapshot_rows: list[UserPositionSnapshotRow],
    asset_rows: list[UserPositionAssetRow],
    *,
    tx_hash_by_key: dict[tuple[bytes, bytes], str] | None = None,
) -> int:
    if not snapshot_rows:
        return 0

    latest_snapshots: dict[tuple[bytes, bytes], UserPositionSnapshotRow] = {}
    for row in snapshot_rows:
        key = _current_position_key(row.market, row.user_address)
        existing = latest_snapshots.get(key)
        if existing is None or _is_newer_current_state(
            existing_block_number=existing.block_number,
            existing_block_timestamp=existing.timestamp,
            incoming_block_number=row.block_number,
            incoming_block_timestamp=row.timestamp,
        ):
            latest_snapshots[key] = row

    latest_asset_groups: dict[tuple[bytes, bytes], list[UserPositionAssetRow]] = (
        defaultdict(list)
    )
    for row in asset_rows:
        key = _current_position_key(row.market, row.user_address)
        snapshot = latest_snapshots.get(key)
        if snapshot is None:
            continue
        if (
            row.block_number != snapshot.block_number
            or row.timestamp != snapshot.timestamp
        ):
            continue
        latest_asset_groups[key].append(row)

    markets = [key[0] for key in latest_snapshots]
    users = [key[1] for key in latest_snapshots]
    async with pool.acquire() as conn:
        existing_rows = await conn.fetch(
            f"""
            SELECT market, user_address, last_block_number, last_block_timestamp
            FROM loan.{_V2_CURRENT_POSITION_TABLE}
            WHERE market = ANY($1::bytea[])
              AND user_address = ANY($2::bytea[])
            """,
            markets,
            users,
        )

        existing_map = {
            _current_position_key(bytes(row["market"]), bytes(row["user_address"])): (
                int(row["last_block_number"]),
                row["last_block_timestamp"],
            )
            for row in existing_rows
        }

        accepted_snapshots: dict[tuple[bytes, bytes], UserPositionSnapshotRow] = {}
        for key, row in latest_snapshots.items():
            existing_meta = existing_map.get(key)
            if _is_newer_current_state(
                existing_block_number=(
                    existing_meta[0] if existing_meta is not None else None
                ),
                existing_block_timestamp=(
                    existing_meta[1] if existing_meta is not None else None
                ),
                incoming_block_number=row.block_number,
                incoming_block_timestamp=row.timestamp,
            ):
                accepted_snapshots[key] = row

        if not accepted_snapshots:
            return 0

        open_position_values: list[tuple[object, ...]] = []
        open_asset_values: list[tuple[object, ...]] = []
        tx_hash_map = tx_hash_by_key or {}

        async with conn.transaction():
            for key, row in accepted_snapshots.items():
                await conn.execute(
                    f"""
                    DELETE FROM loan.{_V2_CURRENT_POSITION_ASSET_TABLE}
                    WHERE market = $1 AND user_address = $2
                    """,
                    row.market,
                    row.user_address,
                )
                if not row.has_open_position:
                    await conn.execute(
                        f"""
                        DELETE FROM loan.{_V2_CURRENT_POSITION_TABLE}
                        WHERE market = $1 AND user_address = $2
                        """,
                        row.market,
                        row.user_address,
                    )
                    continue

                open_position_values.append(
                    (
                        row.market,
                        row.user_address,
                        row.symbol,
                        row.block_number,
                        row.timestamp,
                        tx_hash_map.get(key),
                        row.has_open_position,
                        row.is_liquidatable,
                        row.base_token or None,
                        row.base_symbol,
                        row.base_price_usd,
                        row.eth_price_usd,
                        row.total_collateral_usd,
                        row.total_debt_usd,
                        row.discounted_collateral_usd,
                        row.liquidation_buffer_usd,
                        row.health_factor,
                        row.eth_sensitive_collateral_usd,
                        row.eth_sensitive_debt_usd,
                        row.net_eth_exposure_usd,
                        row.non_eth_collateral_usd,
                        row.non_eth_debt_usd,
                        row.basis_risk_collateral_usd,
                        row.eth_down_liq_price_usd,
                        row.eth_up_liq_price_usd,
                        row.eth_liq_mode,
                        row.dominant_risk,
                        json.dumps(row.assets_jsonb, ensure_ascii=False),
                    )
                )

                for asset_row in latest_asset_groups.get(key, []):
                    open_asset_values.append(
                        (
                            asset_row.market,
                            asset_row.user_address,
                            asset_row.asset,
                            asset_row.side,
                            asset_row.symbol,
                            asset_row.decimals,
                            asset_row.amount,
                            asset_row.price_in_base,
                            asset_row.price_usd,
                            asset_row.value_usd,
                            asset_row.discounted_value_usd,
                            asset_row.borrow_collateral_factor,
                            asset_row.liquidate_collateral_factor,
                            asset_row.liquidation_factor,
                            asset_row.beta_to_eth,
                            asset_row.is_eth_correlated,
                            asset_row.is_basis_risk_asset,
                            asset_row.block_number,
                            asset_row.timestamp,
                        )
                    )

            if open_position_values:
                await conn.executemany(
                    _UPSERT_V2_CURRENT_POSITION,
                    open_position_values,
                )
            if open_asset_values:
                await conn.executemany(
                    _UPSERT_V2_CURRENT_POSITION_ASSET,
                    open_asset_values,
                )

    return len(accepted_snapshots)


async def fetch_compound_v3_current_positions(
    pool: asyncpg.Pool,
    *,
    user_address: bytes | None = None,
    market: bytes | None = None,
) -> list[CompoundCurrentPositionRow]:
    where_clauses: list[str] = []
    args: list[Any] = []
    if user_address is not None:
        args.append(user_address)
        where_clauses.append(f"user_address = ${len(args)}")
    if market is not None:
        args.append(market)
        where_clauses.append(f"market = ${len(args)}")
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT *
            FROM loan.{_V3_CURRENT_POSITION_TABLE}
            {where_sql}
            ORDER BY last_block_timestamp DESC, market, user_address
            """,
            *args,
        )
    return [
        CompoundCurrentPositionRow(
            market=bytes(row["market"]),
            user_address=bytes(row["user_address"]),
            symbol=row["symbol"],
            last_block_number=int(row["last_block_number"]),
            last_block_timestamp=row["last_block_timestamp"],
            last_tx_hash=row["last_tx_hash"],
            has_open_position=bool(row["has_open_position"]),
            is_liquidatable=bool(row["is_liquidatable"]),
            base_token=bytes(row["base_token"])
            if row["base_token"] is not None
            else None,
            base_symbol=row["base_symbol"],
            base_price_usd=(
                Decimal(row["base_price_usd"])
                if row["base_price_usd"] is not None
                else None
            ),
            eth_price_usd=Decimal(row["eth_price_usd"]),
            total_collateral_usd=Decimal(row["total_collateral_usd"]),
            total_debt_usd=Decimal(row["total_debt_usd"]),
            discounted_collateral_usd=Decimal(row["discounted_collateral_usd"]),
            liquidation_buffer_usd=Decimal(row["liquidation_buffer_usd"]),
            health_factor=Decimal(row["health_factor"]),
            eth_sensitive_collateral_usd=Decimal(row["eth_sensitive_collateral_usd"]),
            eth_sensitive_debt_usd=Decimal(row["eth_sensitive_debt_usd"]),
            net_eth_exposure_usd=Decimal(row["net_eth_exposure_usd"]),
            non_eth_collateral_usd=Decimal(row["non_eth_collateral_usd"]),
            non_eth_debt_usd=Decimal(row["non_eth_debt_usd"]),
            basis_risk_collateral_usd=Decimal(row["basis_risk_collateral_usd"]),
            eth_down_liq_price_usd=(
                Decimal(row["eth_down_liq_price_usd"])
                if row["eth_down_liq_price_usd"] is not None
                else None
            ),
            eth_up_liq_price_usd=(
                Decimal(row["eth_up_liq_price_usd"])
                if row["eth_up_liq_price_usd"] is not None
                else None
            ),
            eth_liq_mode=str(row["eth_liq_mode"]),
            dominant_risk=str(row["dominant_risk"]),
            assets_jsonb=(
                json.loads(row["assets_jsonb"])
                if isinstance(row["assets_jsonb"], str)
                else list(row["assets_jsonb"])
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


async def fetch_compound_v2_current_positions(
    pool: asyncpg.Pool,
    *,
    user_address: bytes | None = None,
    market: bytes | None = None,
) -> list[CompoundCurrentPositionRow]:
    where_clauses: list[str] = []
    args: list[Any] = []
    if user_address is not None:
        args.append(user_address)
        where_clauses.append(f"user_address = ${len(args)}")
    if market is not None:
        args.append(market)
        where_clauses.append(f"market = ${len(args)}")
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT *
            FROM loan.{_V2_CURRENT_POSITION_TABLE}
            {where_sql}
            ORDER BY last_block_timestamp DESC, market, user_address
            """,
            *args,
        )
    return [
        CompoundCurrentPositionRow(
            market=bytes(row["market"]),
            user_address=bytes(row["user_address"]),
            symbol=row["symbol"],
            last_block_number=int(row["last_block_number"]),
            last_block_timestamp=row["last_block_timestamp"],
            last_tx_hash=row["last_tx_hash"],
            has_open_position=bool(row["has_open_position"]),
            is_liquidatable=bool(row["is_liquidatable"]),
            base_token=bytes(row["base_token"])
            if row["base_token"] is not None
            else None,
            base_symbol=row["base_symbol"],
            base_price_usd=(
                Decimal(row["base_price_usd"])
                if row["base_price_usd"] is not None
                else None
            ),
            eth_price_usd=Decimal(row["eth_price_usd"]),
            total_collateral_usd=Decimal(row["total_collateral_usd"]),
            total_debt_usd=Decimal(row["total_debt_usd"]),
            discounted_collateral_usd=Decimal(row["discounted_collateral_usd"]),
            liquidation_buffer_usd=Decimal(row["liquidation_buffer_usd"]),
            health_factor=Decimal(row["health_factor"]),
            eth_sensitive_collateral_usd=Decimal(row["eth_sensitive_collateral_usd"]),
            eth_sensitive_debt_usd=Decimal(row["eth_sensitive_debt_usd"]),
            net_eth_exposure_usd=Decimal(row["net_eth_exposure_usd"]),
            non_eth_collateral_usd=Decimal(row["non_eth_collateral_usd"]),
            non_eth_debt_usd=Decimal(row["non_eth_debt_usd"]),
            basis_risk_collateral_usd=Decimal(row["basis_risk_collateral_usd"]),
            eth_down_liq_price_usd=(
                Decimal(row["eth_down_liq_price_usd"])
                if row["eth_down_liq_price_usd"] is not None
                else None
            ),
            eth_up_liq_price_usd=(
                Decimal(row["eth_up_liq_price_usd"])
                if row["eth_up_liq_price_usd"] is not None
                else None
            ),
            eth_liq_mode=str(row["eth_liq_mode"]),
            dominant_risk=str(row["dominant_risk"]),
            assets_jsonb=(
                json.loads(row["assets_jsonb"])
                if isinstance(row["assets_jsonb"], str)
                else list(row["assets_jsonb"])
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


async def fetch_compound_v3_current_position_assets(
    pool: asyncpg.Pool,
    *,
    user_address: bytes | None = None,
    market: bytes | None = None,
) -> list[CompoundCurrentPositionAssetRow]:
    where_clauses: list[str] = []
    args: list[Any] = []
    if user_address is not None:
        args.append(user_address)
        where_clauses.append(f"user_address = ${len(args)}")
    if market is not None:
        args.append(market)
        where_clauses.append(f"market = ${len(args)}")
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT *
            FROM loan.{_V3_CURRENT_POSITION_ASSET_TABLE}
            {where_sql}
            ORDER BY last_block_timestamp DESC, market, user_address, asset, side
            """,
            *args,
        )
    return [
        CompoundCurrentPositionAssetRow(
            market=bytes(row["market"]),
            user_address=bytes(row["user_address"]),
            asset=bytes(row["asset"]),
            side=str(row["side"]),
            symbol=row["symbol"],
            decimals=row["decimals"],
            amount=Decimal(row["amount"]),
            price_in_base=(
                Decimal(row["price_in_base"])
                if row["price_in_base"] is not None
                else None
            ),
            price_usd=Decimal(row["price_usd"]),
            value_usd=Decimal(row["value_usd"]),
            discounted_value_usd=Decimal(row["discounted_value_usd"]),
            borrow_collateral_factor=(
                Decimal(row["borrow_collateral_factor"])
                if row["borrow_collateral_factor"] is not None
                else None
            ),
            liquidate_collateral_factor=(
                Decimal(row["liquidate_collateral_factor"])
                if row["liquidate_collateral_factor"] is not None
                else None
            ),
            liquidation_factor=(
                Decimal(row["liquidation_factor"])
                if row["liquidation_factor"] is not None
                else None
            ),
            beta_to_eth=Decimal(row["beta_to_eth"]),
            is_eth_correlated=bool(row["is_eth_correlated"]),
            is_basis_risk_asset=bool(row["is_basis_risk_asset"]),
            last_block_number=int(row["last_block_number"]),
            last_block_timestamp=row["last_block_timestamp"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


async def ensure_compound_event_snapshot_table(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_DDL_COMPOUND_EVENT_SNAPSHOT)
        await conn.execute(_DDL_COMPOUND_EVENT_SNAPSHOT_INDEXES)
    logger.info(
        "Compound event-driven snapshot table ready: loan.%s",
        _COMPOUND_EVENT_SNAPSHOT_TABLE,
    )


async def upsert_compound_event_snapshots(
    pool: asyncpg.Pool,
    rows: list[CompoundEventPositionSnapshotRow],
) -> int:
    if not rows:
        return 0
    values = [
        (
            r.user_address,
            r.protocol,
            r.market,
            r.symbol,
            r.block_number,
            r.tx_hash,
            r.block_timestamp,
            r.has_open_position,
            r.is_liquidatable,
            r.base_token,
            r.base_symbol,
            r.base_price_usd,
            r.eth_price_usd,
            r.total_collateral_usd,
            r.total_debt_usd,
            r.discounted_collateral_usd,
            r.liquidation_buffer_usd,
            r.health_factor,
            r.eth_sensitive_collateral_usd,
            r.eth_sensitive_debt_usd,
            r.net_eth_exposure_usd,
            r.non_eth_collateral_usd,
            r.non_eth_debt_usd,
            r.basis_risk_collateral_usd,
            r.eth_down_liq_price_usd,
            r.eth_up_liq_price_usd,
            r.eth_liq_mode,
            r.dominant_risk,
            json.dumps(r.assets_jsonb, ensure_ascii=False),
            r.brief,
        )
        for r in rows
    ]
    async with pool.acquire() as conn:
        await conn.executemany(_SQL_UPSERT_COMPOUND_EVENT_SNAPSHOT, values)
    return len(rows)


async def get_compound_event_snapshots(
    pool: asyncpg.Pool,
    *,
    user_address: bytes,
    protocol: str,
    market: bytes,
    from_ts: datetime,
    to_ts: datetime,
) -> list[Any]:
    return await pool.fetch(
        _SQL_GET_COMPOUND_EVENT_SNAPSHOTS,
        user_address,
        protocol,
        market,
        from_ts,
        to_ts,
    )


def ensure_compound_v3_user_positions_table(engine):
    inspector = inspect(engine)
    if not inspector.has_table("compound_v3_user_positions", schema="loan"):
        Base.metadata.create_all(engine, tables=[CompoundV3UserPosition.__table__])
