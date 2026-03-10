"""
SQLAlchemy 2.0 ORM 声明模型 (loan schema)。

这些模型作为 Alembic autogenerate 的 schema 来源，用于数据库迁移管理。
日常 API 查询仍通过 sqlalchemy.text() 执行原生 SQL。
"""

from __future__ import annotations

from datetime import datetime
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
from sqlalchemy.dialects.postgresql import JSONB
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
# 仓位快照缓存表（TX 级别历史回放缓存）
# ──────────────────────────────────────────────────────────────────────────────


class PositionSnapshotCache(Base):
    __tablename__ = "position_snapshot_cache"
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
