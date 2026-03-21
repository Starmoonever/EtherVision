"""Pydantic schemas for Compound API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PositionAssetResponse(BaseModel):
    asset: str = Field(description="资产地址。")
    symbol: str | None = Field(description="资产符号，例如 WETH、USDC。")
    side: str = Field(
        description="资产在仓位中的角色，可能为 collateral、base_supply 或 base_borrow。"
    )
    amount: str = Field(description="该资产数量，已按 decimals 缩放。")
    price_in_base: str | None = Field(
        description="该资产相对于 base token 的价格；base token 自身通常为 1。"
    )
    price_usd: str = Field(description="该资产的 USD 价格。")
    value_usd: str = Field(description="该资产按当前价格计算的 USD 市值。")
    discounted_value_usd: str = Field(
        description="该资产可用于清算安全边际计算的折扣后 USD 价值。"
    )
    borrow_collateral_factor: str | None = Field(
        description="Compound v3 的 borrow collateral factor。"
    )
    liquidate_collateral_factor: str | None = Field(
        description="Compound v3 的 liquidate collateral factor。"
    )
    liquidation_factor: str | None = Field(
        description="Compound v3 的 liquidation factor。"
    )
    beta_to_eth: str = Field(
        description="对 ETH 价格的近似敏感度，1 表示强 ETH 敞口，0 表示基本无 ETH 敞口。"
    )
    is_eth_correlated: bool = Field(description="该资产是否被视为 ETH 相关资产。")
    is_basis_risk_asset: bool = Field(
        description="该资产是否属于 ETH 相关但非原生 WETH 的 basis risk 资产。"
    )


class PositionResponse(BaseModel):
    market: str = Field(description="市场合约地址。")
    symbol: str | None = Field(description="市场名称，例如 WETH、USDC、USDT。")
    timestamp: str = Field(description="该市场仓位快照对应的 UTC 时间戳。")
    block_number: int = Field(description="本次仓位快照对应的链上区块号。")
    has_open_position: bool = Field(description="该用户在当前市场是否存在非空仓位。")
    is_liquidatable: bool = Field(
        description="按当前价格和折扣后抵押价值判断，仓位是否已可被清算。"
    )
    base_token: str = Field(description="该市场的 base token 地址，即借贷主资产地址。")
    base_symbol: str | None = Field(description="该市场的 base token 符号。")
    base_price_usd: str = Field(description="base token 的 USD 价格。")
    eth_price_usd: str = Field(
        description="ETH 的 USD 价格，用于 ETH 敏感风险指标计算。"
    )
    total_collateral_usd: str = Field(
        description="仓位总抵押 USD 价值，包括 base supply 和 collateral。"
    )
    total_debt_usd: str = Field(description="仓位总债务 USD 价值。")
    discounted_collateral_usd: str = Field(
        description="按清算折扣系数折算后的可用抵押 USD 价值。"
    )
    liquidation_buffer_usd: str = Field(
        description="清算缓冲 = discounted_collateral_usd - total_debt_usd；越小越危险。"
    )
    health_factor: str = Field(
        description="健康因子 = discounted_collateral_usd / total_debt_usd；无债务时返回极大值。"
    )
    eth_sensitive_collateral_usd: str = Field(
        description="对 ETH 价格敏感的抵押部分 USD 价值。"
    )
    eth_sensitive_debt_usd: str = Field(
        description="对 ETH 价格敏感的债务部分 USD 价值。"
    )
    net_eth_exposure_usd: str = Field(
        description="净 ETH 敞口 = eth_sensitive_collateral_usd - eth_sensitive_debt_usd。"
    )
    non_eth_collateral_usd: str = Field(description="非 ETH 敏感抵押的 USD 价值。")
    non_eth_debt_usd: str = Field(description="非 ETH 敏感债务的 USD 价值。")
    basis_risk_collateral_usd: str = Field(
        description="ETH 相关但带有 basis risk 的抵押 USD 价值。"
    )
    eth_down_liq_price_usd: str | None = Field(
        description="若 ETH 下跌会触发清算，则这里给出估算的 ETH 下跌清算价；否则为空。"
    )
    eth_up_liq_price_usd: str | None = Field(
        description="若 ETH 上涨会触发清算，则这里给出估算的 ETH 上涨清算价；否则为空。"
    )
    eth_liq_mode: str = Field(
        description="ETH 清算方向模式，常见为 down、up、mixed、neutral。"
    )
    dominant_risk: str = Field(
        description="主导风险来源，常见为 eth_down、eth_up、basis、mixed、neutral。"
    )
    assets: list[PositionAssetResponse] = Field(
        description="该用户仓位中的逐资产明细。"
    )


class UserPositionResponse(BaseModel):
    version: str = Field(description="Compound 协议版本；当前仅支持 v3。")
    address: str = Field(description="用户地址。")
    positions: list[PositionResponse] = Field(
        description="该地址在命中市场下的仓位列表；`market=all` 时可能返回多个市场。"
    )


class HealthResponse(BaseModel):
    status: str


class MarketStateReserveResponse(BaseModel):
    reserve: str
    symbol: str | None
    decimals: int | None
    total_supply: str
    total_borrow: str
    utilization: str
    borrow_apr: str
    supply_apr: str
    price_in_base: str
    price_usd: str
    supply_usd: str
    borrow_usd: str


class MarketStateResponse(BaseModel):
    version: str
    market: str
    symbol: str | None
    timestamp: str
    total_supply: str
    total_borrow: str
    collateral_usd: str
    utilization: str
    borrow_apr: str
    supply_apr: str
    price_usd: str
    supply_usd: str
    borrow_usd: str
    reserves: list[MarketStateReserveResponse] | None = None


class MarketStatePeriodResponse(BaseModel):
    points: list[MarketStateResponse]
