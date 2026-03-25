"""
SQLAlchemy 2.0 ORM 声明模型 (loan schema)。

这些模型作为 Alembic autogenerate 的 schema 来源，用于数据库迁移管理。
日常 API 查询仍通过 sqlalchemy.text() 执行原生 SQL。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import BYTEA, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# 抵押端汇总表（ETH 下跌清算风险）
# ──────────────────────────────────────────────────────────────────────────────


class AaveV3PositionCollateral(Base):
    __tablename__ = "aave_v3_eth_positions_collateral"
    __table_args__ = {"schema": "loan"}

    user_address: Mapped[str] = mapped_column(Text, primary_key=True)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    total_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    available_borrows_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    health_factor: Mapped[Decimal] = mapped_column(Numeric(40, 18), nullable=False)
    ltv: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liq_threshold: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liq_price: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    eth_collateral_amount: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    eth_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )


class AaveV2PositionCollateral(Base):
    __tablename__ = "aave_v2_eth_positions_collateral"
    __table_args__ = {"schema": "loan"}

    user_address: Mapped[str] = mapped_column(Text, primary_key=True)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    total_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    available_borrows_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    health_factor: Mapped[Decimal] = mapped_column(Numeric(40, 18), nullable=False)
    ltv: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liq_threshold: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liq_price: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    eth_collateral_amount: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    eth_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 借贷端汇总表（ETH 上涨清算风险）
# ──────────────────────────────────────────────────────────────────────────────


class AaveV3PositionBorrow(Base):
    __tablename__ = "aave_v3_eth_positions_borrow"
    __table_args__ = {"schema": "loan"}

    user_address: Mapped[str] = mapped_column(Text, primary_key=True)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    total_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    available_borrows_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    health_factor: Mapped[Decimal] = mapped_column(Numeric(40, 18), nullable=False)
    ltv: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liq_threshold: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liq_price: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    weth_debt_raw: Mapped[Decimal] = mapped_column(
        Numeric(40, 0), nullable=False, server_default="0"
    )
    weth_debt_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    liq_price_rise: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )


class AaveV2PositionBorrow(Base):
    __tablename__ = "aave_v2_eth_positions_borrow"
    __table_args__ = {"schema": "loan"}

    user_address: Mapped[str] = mapped_column(Text, primary_key=True)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    total_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    available_borrows_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    health_factor: Mapped[Decimal] = mapped_column(Numeric(40, 18), nullable=False)
    ltv: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liq_threshold: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liq_price: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    weth_debt_raw: Mapped[Decimal] = mapped_column(
        Numeric(40, 0), nullable=False, server_default="0"
    )
    weth_debt_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    liq_price_rise: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 资产明细表（reserve positions）
# ──────────────────────────────────────────────────────────────────────────────


class AaveV3ReservePositionCollateral(Base):
    __tablename__ = "aave_v3_eth_reserve_positions_collateral"
    __table_args__ = ({"schema": "loan"},)

    user_address: Mapped[str] = mapped_column(Text, primary_key=True)
    token_address: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    supply_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    supply_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    stable_debt_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    variable_debt_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    use_as_collateral: Mapped[bool] = mapped_column(Boolean, nullable=False)


class AaveV2ReservePositionCollateral(Base):
    __tablename__ = "aave_v2_eth_reserve_positions_collateral"
    __table_args__ = ({"schema": "loan"},)

    user_address: Mapped[str] = mapped_column(Text, primary_key=True)
    token_address: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    supply_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    supply_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    stable_debt_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    variable_debt_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    use_as_collateral: Mapped[bool] = mapped_column(Boolean, nullable=False)


class AaveV3ReservePositionBorrow(Base):
    __tablename__ = "aave_v3_eth_reserve_positions_borrow"
    __table_args__ = ({"schema": "loan"},)

    user_address: Mapped[str] = mapped_column(Text, primary_key=True)
    token_address: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    supply_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    supply_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    stable_debt_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    variable_debt_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    use_as_collateral: Mapped[bool] = mapped_column(Boolean, nullable=False)


class AaveV2ReservePositionBorrow(Base):
    __tablename__ = "aave_v2_eth_reserve_positions_borrow"
    __table_args__ = ({"schema": "loan"},)

    user_address: Mapped[str] = mapped_column(Text, primary_key=True)
    token_address: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    supply_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    supply_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    stable_debt_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    variable_debt_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    use_as_collateral: Mapped[bool] = mapped_column(Boolean, nullable=False)


# ──────────────────────────────────────────────────────────────────────────────
# 地址来源表（来自 chain-data-collector 写入）
# ──────────────────────────────────────────────────────────────────────────────


class AaveV3WethCollateral(Base):
    __tablename__ = "aave_v3_eth_weth_collateral"
    __table_args__ = {"schema": "loan"}

    wallet_address: Mapped[str] = mapped_column("walletAddress", Text, primary_key=True)
    weth_amount_eth: Mapped[Decimal] = mapped_column(
        "wethAmount_ETH", Numeric(30, 8), nullable=False, server_default="0"
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class AaveV2WethCollateral(Base):
    __tablename__ = "aave_v2_eth_weth_collateral"
    __table_args__ = {"schema": "loan"}

    wallet_address: Mapped[str] = mapped_column("walletAddress", Text, primary_key=True)
    weth_amount_eth: Mapped[Decimal] = mapped_column(
        "wethAmount_ETH", Numeric(30, 8), nullable=False, server_default="0"
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class AaveV3WethBorrow(Base):
    __tablename__ = "aave_v3_eth_weth_borrow"
    __table_args__ = {"schema": "loan"}

    wallet_address: Mapped[str] = mapped_column("walletAddress", Text, primary_key=True)
    borrowed_weth_eth: Mapped[Decimal] = mapped_column(
        "borrowedWeth_ETH", Numeric(30, 8), nullable=False, server_default="0"
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class AaveV2WethBorrow(Base):
    __tablename__ = "aave_v2_eth_weth_borrow"
    __table_args__ = {"schema": "loan"}

    wallet_address: Mapped[str] = mapped_column("walletAddress", Text, primary_key=True)
    borrowed_weth_eth: Mapped[Decimal] = mapped_column(
        "borrowedWeth_ETH", Numeric(30, 8), nullable=False, server_default="0"
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 市场快照表（每区块 reserve-level 数据）
# ──────────────────────────────────────────────────────────────────────────────


class AaveV3MarketSnapshot(Base):
    __tablename__ = "aave_v3_eth_market_snapshots"
    __table_args__ = {"schema": "loan"}

    block_number: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    token_address: Mapped[str] = mapped_column(Text, primary_key=True)
    block_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    total_supply_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    total_stable_debt_raw: Mapped[Decimal] = mapped_column(
        Numeric(40, 0), nullable=False
    )
    total_variable_debt_raw: Mapped[Decimal] = mapped_column(
        Numeric(40, 0), nullable=False
    )
    total_supply_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    available_liquidity_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    liquidity_rate_ray: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    variable_borrow_rate_ray: Mapped[Decimal] = mapped_column(
        Numeric(40, 0), nullable=False
    )
    stable_borrow_rate_ray: Mapped[Decimal] = mapped_column(
        Numeric(40, 0), nullable=False
    )
    utilization_rate: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    liquidity_index_ray: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    variable_borrow_index_ray: Mapped[Decimal] = mapped_column(
        Numeric(40, 0), nullable=False
    )
    last_update_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)


class AaveV2MarketSnapshot(Base):
    __tablename__ = "aave_v2_eth_market_snapshots"
    __table_args__ = {"schema": "loan"}

    block_number: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    token_address: Mapped[str] = mapped_column(Text, primary_key=True)
    block_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    total_supply_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    total_stable_debt_raw: Mapped[Decimal] = mapped_column(
        Numeric(40, 0), nullable=False
    )
    total_variable_debt_raw: Mapped[Decimal] = mapped_column(
        Numeric(40, 0), nullable=False
    )
    total_supply_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    available_liquidity_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    liquidity_rate_ray: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    variable_borrow_rate_ray: Mapped[Decimal] = mapped_column(
        Numeric(40, 0), nullable=False
    )
    stable_borrow_rate_ray: Mapped[Decimal] = mapped_column(
        Numeric(40, 0), nullable=False
    )
    utilization_rate: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    liquidity_index_ray: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    variable_borrow_index_ray: Mapped[Decimal] = mapped_column(
        Numeric(40, 0), nullable=False
    )
    last_update_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)


# ──────────────────────────────────────────────────────────────────────────────
# 市场汇总表（滚动聚合）
# ──────────────────────────────────────────────────────────────────────────────


class AaveV3MarketTotal(Base):
    __tablename__ = "aave_v3_market_totals"
    __table_args__ = {"schema": "loan"}

    block_number: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    block_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    tvl_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    liquidity_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    weighted_utilization: Mapped[Decimal] = mapped_column(
        Numeric(10, 8), nullable=False
    )
    weighted_supply_apy: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    weighted_borrow_apy: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AaveV2MarketTotal(Base):
    __tablename__ = "aave_v2_market_totals"
    __table_args__ = {"schema": "loan"}

    block_number: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    block_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    tvl_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    liquidity_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    weighted_utilization: Mapped[Decimal] = mapped_column(
        Numeric(10, 8), nullable=False
    )
    weighted_supply_apy: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    weighted_borrow_apy: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


# ──────────────────────────────────────────────────────────────────────────────
# Compound 市场状态（小时级 market / reserve 快照）
# ──────────────────────────────────────────────────────────────────────────────


class CompoundV2MarketSnapshot(Base):
    __tablename__ = "compound_v2_market_snapshots"
    __table_args__ = {"schema": "loan"}

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    market: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    total_supply: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    total_borrow: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    utilization: Mapped[Decimal] = mapped_column(Numeric(20, 18), nullable=False)
    borrow_rate: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    supply_rate: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    supply_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    borrow_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class CompoundV3MarketSnapshot(Base):
    __tablename__ = "compound_v3_market_snapshots"
    __table_args__ = {"schema": "loan"}

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    market: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    total_supply: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    total_borrow: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    utilization: Mapped[Decimal] = mapped_column(Numeric(20, 18), nullable=False)
    borrow_rate: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    supply_rate: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    supply_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    borrow_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class CompoundV2MarketSnapshotReserve(Base):
    __tablename__ = "compound_v2_market_snapshot_reserves"
    __table_args__ = {"schema": "loan"}

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    market: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    reserve: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    symbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decimals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_supply: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    total_borrow: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    utilization: Mapped[Decimal] = mapped_column(Numeric(20, 18), nullable=False)
    borrow_rate: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    supply_rate: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    supply_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    borrow_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class CompoundV3MarketSnapshotReserve(Base):
    __tablename__ = "compound_v3_market_snapshot_reserves"
    __table_args__ = {"schema": "loan"}

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    market: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    reserve: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    symbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decimals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_supply: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    total_borrow: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    utilization: Mapped[Decimal] = mapped_column(Numeric(20, 18), nullable=False)
    borrow_rate: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    supply_rate: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    supply_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    borrow_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Compound v2 仓位与治理配置快照
# ──────────────────────────────────────────────────────────────────────────────


class CompoundV2UserPositionSnapshot(Base):
    __tablename__ = "compound_v2_user_position_snapshots"
    __table_args__ = {"schema": "loan"}

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    market: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    user_address: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    symbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    has_open_position: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_liquidatable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    base_token: Mapped[Optional[bytes]] = mapped_column(BYTEA, nullable=True)
    base_symbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    base_price_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(30, 8), nullable=True
    )
    eth_price_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    total_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    discounted_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    liquidation_buffer_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    health_factor: Mapped[Decimal] = mapped_column(Numeric(40, 18), nullable=False)
    eth_sensitive_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    eth_sensitive_debt_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    net_eth_exposure_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    non_eth_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    non_eth_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    basis_risk_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    eth_down_liq_price_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(30, 8), nullable=True
    )
    eth_up_liq_price_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(30, 8), nullable=True
    )
    eth_liq_mode: Mapped[str] = mapped_column(Text, nullable=False)
    dominant_risk: Mapped[str] = mapped_column(Text, nullable=False)
    assets_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class CompoundV2UserPositionSnapshotAsset(Base):
    __tablename__ = "compound_v2_user_position_snapshot_assets"
    __table_args__ = {"schema": "loan"}

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    market: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    user_address: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    asset: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    side: Mapped[str] = mapped_column(Text, primary_key=True)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    symbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decimals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    price_in_base: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(30, 8), nullable=True
    )
    price_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    value_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    discounted_value_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    borrow_collateral_factor: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 18), nullable=True
    )
    liquidate_collateral_factor: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 18), nullable=True
    )
    liquidation_factor: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 18), nullable=True
    )
    beta_to_eth: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    is_eth_correlated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_basis_risk_asset: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ctoken: Mapped[Optional[bytes]] = mapped_column(BYTEA, nullable=True)
    underlying: Mapped[Optional[bytes]] = mapped_column(BYTEA, nullable=True)
    exchange_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(38, 18), nullable=True
    )
    is_entered_market: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    collateral_factor: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 18), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class CompoundV2MarketConfigVersion(Base):
    __tablename__ = "compound_v2_market_config_versions"
    __table_args__ = {"schema": "loan"}

    market: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    config_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    effective_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    comptroller: Mapped[Optional[bytes]] = mapped_column(BYTEA, nullable=True)
    interest_rate_model: Mapped[Optional[bytes]] = mapped_column(BYTEA, nullable=True)
    underlying: Mapped[Optional[bytes]] = mapped_column(BYTEA, nullable=True)
    underlying_symbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ctoken_decimals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    underlying_decimals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    collateral_factor: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 18), nullable=True
    )
    reserve_factor: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 18), nullable=True
    )
    liquidation_threshold: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 18), nullable=True
    )
    borrow_cap: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(38, 18), nullable=True
    )
    supply_cap: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(38, 18), nullable=True
    )
    is_listed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    is_comped: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_deprecated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    raw_config_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class CompoundV2ProtocolConfigVersion(Base):
    __tablename__ = "compound_v2_protocol_config_versions"
    __table_args__ = {"schema": "loan"}

    config_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    effective_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    comptroller: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    price_oracle: Mapped[Optional[bytes]] = mapped_column(BYTEA, nullable=True)
    close_factor: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 18), nullable=True
    )
    liquidation_incentive: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 18), nullable=True
    )
    pause_guardian: Mapped[Optional[bytes]] = mapped_column(BYTEA, nullable=True)
    transfer_paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    seize_paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    mint_paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    borrow_paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    raw_config_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class CompoundV2UserMembership(Base):
    __tablename__ = "compound_v2_user_memberships"
    __table_args__ = {"schema": "loan"}

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    user_address: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    market: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    symbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_entered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    raw_membership_jsonb: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 区块时间戳缓存表
# ──────────────────────────────────────────────────────────────────────────────


class EthBlockTimestamp(Base):
    __tablename__ = "eth_block_timestamps"
    __table_args__ = {"schema": "loan"}

    block_number: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    block_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


# ──────────────────────────────────────────────────────────────────────────────
# 日级历史仓位表（collateral / borrow 两端合并为一张表）
# ──────────────────────────────────────────────────────────────────────────────


class AaveV3DailyPosition(Base):
    __tablename__ = "aave_v3_eth_daily_positions"
    __table_args__ = {"schema": "loan"}

    snapshot_date: Mapped[date] = mapped_column(primary_key=True)
    user_address: Mapped[str] = mapped_column(Text, primary_key=True)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    total_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    available_borrows_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    health_factor: Mapped[Decimal] = mapped_column(Numeric(40, 18), nullable=False)
    ltv: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liq_threshold: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liq_price: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    liq_price_rise: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    eth_collateral_amount: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    eth_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    weth_debt_raw: Mapped[Decimal] = mapped_column(
        Numeric(40, 0), nullable=False, server_default="0"
    )
    weth_debt_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    eth_price_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class AaveV2DailyPosition(Base):
    __tablename__ = "aave_v2_eth_daily_positions"
    __table_args__ = {"schema": "loan"}

    snapshot_date: Mapped[date] = mapped_column(primary_key=True)
    user_address: Mapped[str] = mapped_column(Text, primary_key=True)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    total_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    available_borrows_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    health_factor: Mapped[Decimal] = mapped_column(Numeric(40, 18), nullable=False)
    ltv: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liq_threshold: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liq_price: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    liq_price_rise: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    eth_collateral_amount: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    eth_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    weth_debt_raw: Mapped[Decimal] = mapped_column(
        Numeric(40, 0), nullable=False, server_default="0"
    )
    weth_debt_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    eth_price_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class AaveV3DailyReservePosition(Base):
    __tablename__ = "aave_v3_eth_daily_reserve_positions"
    __table_args__ = ({"schema": "loan"},)

    snapshot_date: Mapped[date] = mapped_column(primary_key=True)
    user_address: Mapped[str] = mapped_column(Text, primary_key=True)
    token_address: Mapped[str] = mapped_column(Text, primary_key=True)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    supply_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    supply_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    stable_debt_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    variable_debt_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    use_as_collateral: Mapped[bool] = mapped_column(Boolean, nullable=False)


class AaveV2DailyReservePosition(Base):
    __tablename__ = "aave_v2_eth_daily_reserve_positions"
    __table_args__ = ({"schema": "loan"},)

    snapshot_date: Mapped[date] = mapped_column(primary_key=True)
    user_address: Mapped[str] = mapped_column(Text, primary_key=True)
    token_address: Mapped[str] = mapped_column(Text, primary_key=True)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    supply_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    supply_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    stable_debt_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    variable_debt_raw: Mapped[Decimal] = mapped_column(Numeric(40, 0), nullable=False)
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    use_as_collateral: Mapped[bool] = mapped_column(Boolean, nullable=False)


# ──────────────────────────────────────────────────────────────────────────────


class PositionSnapshotCache(Base):
    __tablename__ = "aave_position_snapshots"
    __table_args__ = (
        UniqueConstraint("user_address", "protocol", "tx_hash", name="uq_snapshot"),
        {"schema": "loan"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_address: Mapped[str] = mapped_column(Text, nullable=False)
    protocol: Mapped[str] = mapped_column(Text, nullable=False)  # 'v2' | 'v3'
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tx_hash: Mapped[str] = mapped_column(Text, nullable=False)
    block_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    total_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    available_borrows_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    health_factor: Mapped[Decimal] = mapped_column(Numeric(40, 18), nullable=False)
    ltv: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liq_threshold: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    liq_price: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    liq_price_rise: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    liq_price_weth: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    eth_collateral_amount: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    eth_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    weth_debt_amount: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    weth_debt_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, server_default="0"
    )
    eth_price_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(30, 8), nullable=True
    )
    reserves_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    brief: Mapped[str] = mapped_column(Text, nullable=False, server_default="''")
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class CompoundPositionSnapshotCache(Base):
    __tablename__ = "compound_position_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "user_address",
            "protocol",
            "market",
            "tx_hash",
            name="uq_compound_snapshot",
        ),
        {"schema": "loan"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_address: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    protocol: Mapped[str] = mapped_column(Text, nullable=False)  # 'v2' | 'v3'
    market: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    symbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tx_hash: Mapped[str] = mapped_column(Text, nullable=False)
    block_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    has_open_position: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_liquidatable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    base_token: Mapped[Optional[bytes]] = mapped_column(BYTEA, nullable=True)
    base_symbol: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    base_price_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(30, 8), nullable=True
    )
    eth_price_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    total_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    total_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    discounted_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    liquidation_buffer_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    health_factor: Mapped[Decimal] = mapped_column(Numeric(40, 18), nullable=False)
    eth_sensitive_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    eth_sensitive_debt_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    net_eth_exposure_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    non_eth_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    non_eth_debt_usd: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    basis_risk_collateral_usd: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False
    )
    eth_down_liq_price_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(30, 8), nullable=True
    )
    eth_up_liq_price_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(30, 8), nullable=True
    )
    eth_liq_mode: Mapped[str] = mapped_column(Text, nullable=False)
    dominant_risk: Mapped[str] = mapped_column(Text, nullable=False)
    assets_jsonb: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    brief: Mapped[str] = mapped_column(Text, nullable=False, server_default="''")
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
