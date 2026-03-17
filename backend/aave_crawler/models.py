"""数据模型（纯 dataclass，不依赖任何外部库）"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── 合约原始返回  ─────────────────────────────────────────────────────────────


@dataclass
class ReserveToken:
    symbol: str
    token_address: str  # checksum address


@dataclass
class AccountSummary:
    """对应 Pool.getUserAccountData 返回值，均为链上原始整数"""

    total_collateral_base: int  # 8 位精度 USD
    total_debt_base: int  # 8 位精度 USD
    available_borrows_base: int  # 8 位精度 USD
    current_liquidation_threshold: int  # basis points / 10000
    ltv: int  # basis points / 10000
    health_factor: int  # 18 位精度；max uint256 表示 ∞


@dataclass
class UserReserveData:
    """对应 DataProvider.getUserReserveData 返回值"""

    current_atoken_balance: int
    current_stable_debt: int
    current_variable_debt: int
    principal_stable_debt: int
    scaled_variable_debt: int
    stable_borrow_rate: int
    liquidity_rate: int
    stable_rate_last_updated: int
    usage_as_collateral_enabled: bool


@dataclass
class ReserveConfig:
    """对应 DataProvider.getReserveConfigurationData 返回值"""

    decimals: int
    ltv: int
    liquidation_threshold: int
    liquidation_bonus: int
    reserve_factor: int
    usage_as_collateral_enabled: bool
    borrowing_enabled: bool
    stable_borrow_rate_enabled: bool
    is_active: bool
    is_frozen: bool


# ── 聚合模型（业务层使用） ────────────────────────────────────────────────────


@dataclass
class ReservePosition:
    """单个资产的仓位，原始整数值，上层再做精度转换"""

    symbol: str
    token_address: str
    decimals: int
    # 价格：Oracle 返回 8 位精度 USD 原始值
    price_raw: int
    # 供给
    supply_raw: int
    usage_as_collateral_enabled: bool
    # 清算阈值（basis points，0-10000），来自 getReserveConfigurationData
    liquidation_threshold: int
    # 借贷
    stable_debt_raw: int
    variable_debt_raw: int
    # Scaled 字段（index 重算所需不变量；default=0 向后兼容）
    scaled_supply_raw: int = 0  # 由 upsert 层从 supply_raw / liquidityIndex 推导
    scaled_variable_debt_raw: int = 0  # getUserReserveData[4] scaledVariableDebt
    principal_stable_debt_raw: int = 0  # getUserReserveData[3] principalStableDebt
    stable_borrow_rate: int = 0  # getUserReserveData[5] stableBorrowRate（per-user）


@dataclass
class UserPosition:
    user_address: str
    block_number: int
    summary: AccountSummary
    reserves: list[ReservePosition] = field(default_factory=list)
