"""Database helpers for Compound crawler."""

from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from datetime import datetime
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


_MARKET_CONFIG_TABLE = "compound_v3_market_config_versions"
_MARKET_CONFIG_ASSET_TABLE = "compound_v3_market_config_assets"
_MARKET_STATUS_TABLE = "compound_v3_market_status_snapshots"

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


_USER_POSITION_TABLE = "compound_v3_user_position_snapshots"
_USER_POSITION_ASSET_TABLE = "compound_v3_user_position_snapshot_assets"

_DDL_USER_POSITION = f"""
CREATE TABLE IF NOT EXISTS loan.{_USER_POSITION_TABLE} (
    "timestamp"                  TIMESTAMPTZ     NOT NULL,
    block_number                 BIGINT          NOT NULL,
    market                       BYTEA           NOT NULL,
    symbol                       TEXT            NULL,
    user_address                 BYTEA           NOT NULL,
    has_open_position            BOOLEAN         NOT NULL,
    is_liquidatable              BOOLEAN         NOT NULL,
    base_token                   BYTEA           NOT NULL,
    base_symbol                  TEXT            NULL,
    base_price_usd               NUMERIC(30, 8)  NOT NULL,
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

_DDL_USER_POSITION_INDEX_MARKET_TS = f"""
CREATE INDEX IF NOT EXISTS idx_{_USER_POSITION_TABLE}_market_ts
    ON loan.{_USER_POSITION_TABLE} (market, "timestamp" DESC);
"""

_DDL_USER_POSITION_INDEX_USER_TS = f"""
CREATE INDEX IF NOT EXISTS idx_{_USER_POSITION_TABLE}_user_ts
    ON loan.{_USER_POSITION_TABLE} (user_address, "timestamp" DESC);
"""

_DDL_USER_POSITION_ASSET = f"""
CREATE TABLE IF NOT EXISTS loan.{_USER_POSITION_ASSET_TABLE} (
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

_DDL_USER_POSITION_ASSET_INDEX_USER_TS = f"""
CREATE INDEX IF NOT EXISTS idx_{_USER_POSITION_ASSET_TABLE}_user_ts
    ON loan.{_USER_POSITION_ASSET_TABLE} (user_address, "timestamp" DESC);
"""

_DDL_USER_POSITION_ASSET_INDEX_MARKET_TS = f"""
CREATE INDEX IF NOT EXISTS idx_{_USER_POSITION_ASSET_TABLE}_market_ts
    ON loan.{_USER_POSITION_ASSET_TABLE} (market, "timestamp" DESC);
"""

_UPSERT_USER_POSITION = f"""
INSERT INTO loan.{_USER_POSITION_TABLE} (
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

_UPSERT_USER_POSITION_ASSET = f"""
INSERT INTO loan.{_USER_POSITION_ASSET_TABLE} (
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


async def _ensure_reserve_columns(conn: Any, table_name: str) -> None:
    await conn.execute(
        f"""
        ALTER TABLE loan.{table_name}
        ADD COLUMN IF NOT EXISTS price_in_base NUMERIC(30, 8);
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
            await _ensure_reserve_columns(conn, reserve_table)
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
    table_name = reserve_table_name(protocol)
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


async def ensure_user_position_snapshot_tables(
    pool: asyncpg.Pool,
    use_timescaledb: bool = False,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_DDL_USER_POSITION)
        await conn.execute(_DDL_USER_POSITION_INDEX_MARKET_TS)
        await conn.execute(_DDL_USER_POSITION_INDEX_USER_TS)

        await conn.execute(_DDL_USER_POSITION_ASSET)
        await conn.execute(_DDL_USER_POSITION_ASSET_INDEX_USER_TS)
        await conn.execute(_DDL_USER_POSITION_ASSET_INDEX_MARKET_TS)

        if use_timescaledb:
            await _try_enable_hypertable(conn, _USER_POSITION_TABLE)
            await _try_enable_hypertable(conn, _USER_POSITION_ASSET_TABLE)

    logger.info(
        "Compound user position snapshot tables ready: %s, %s (timescaledb=%s)",
        _USER_POSITION_TABLE,
        _USER_POSITION_ASSET_TABLE,
        use_timescaledb,
    )


async def fetch_existing_user_position_addresses(
    pool: asyncpg.Pool,
    point_ts: datetime,
    market: bytes,
    user_addresses: list[bytes],
) -> set[bytes]:
    if not user_addresses:
        return set()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT user_address
            FROM loan.{_USER_POSITION_TABLE}
            WHERE "timestamp" = $1
              AND market = $2
              AND user_address = ANY($3::bytea[])
            """,
            point_ts,
            market,
            user_addresses,
        )
    return {bytes(row["user_address"]) for row in rows}


async def upsert_user_position_snapshots(
    pool: asyncpg.Pool,
    rows: list[UserPositionSnapshotRow],
) -> int:
    if not rows:
        return 0
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
                    DELETE FROM loan.{_USER_POSITION_TABLE}
                    WHERE "timestamp" = $1
                      AND market = $2
                      AND user_address = ANY($3::bytea[])
                    """,
                    timestamp,
                    market,
                    user_addresses,
                )
            await conn.copy_records_to_table(
                _USER_POSITION_TABLE,
                schema_name="loan",
                records=values,
                columns=list(_USER_POSITION_COLUMNS),
            )
    return len(rows)


async def upsert_user_position_asset_rows(
    pool: asyncpg.Pool,
    rows: list[UserPositionAssetRow],
) -> int:
    if not rows:
        return 0
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
                    DELETE FROM loan.{_USER_POSITION_ASSET_TABLE}
                    WHERE "timestamp" = $1
                      AND market = $2
                      AND user_address = ANY($3::bytea[])
                    """,
                    timestamp,
                    market,
                    user_addresses,
                )
            await conn.copy_records_to_table(
                _USER_POSITION_ASSET_TABLE,
                schema_name="loan",
                records=values,
                columns=list(_USER_POSITION_ASSET_COLUMNS),
            )
    return len(rows)


def ensure_compound_v3_user_positions_table(engine):
    inspector = inspect(engine)
    if not inspector.has_table("compound_v3_user_positions", schema="loan"):
        Base.metadata.create_all(engine, tables=[CompoundV3UserPosition.__table__])
