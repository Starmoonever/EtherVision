"""API 层 Pydantic 响应模型"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReservePositionSchema(BaseModel):
    symbol: str
    token_address: str
    price_usd: str = Field(description="资产当前价格（USD，2 位小数）")
    supply_amount: str = Field(description="供给数量（已换算 decimals）")
    supply_usd: str = Field(description="供给 USD 估值")
    stable_debt_amount: str
    variable_debt_amount: str
    total_debt_amount: str
    total_debt_usd: str
    use_as_collateral: bool


class AccountSummarySchema(BaseModel):
    total_collateral_usd: str
    total_debt_usd: str
    available_borrows_usd: str
    health_factor: str = Field(description="健康系数；∞ 时返回 'inf'")
    ltv: str = Field(description="贷款价值比（0~1）")
    liq_threshold: str = Field(description="清算阈值（0~1）")


class PositionResponse(BaseModel):
    address: str
    eth_collateral_amount: str = Field(description="ETH/WETH 抵押数量")
    eth_collateral_usd: str = Field(description="ETH/WETH 抵押的 USD 估値")
    total_debt_usd: str = Field(description="总借贷 USD")
    health_factor: str = Field(description="健康系数；无借贷时返回 'inf'")
    ltv: str = Field(description="贷款价値比（0~1）")
    liq_threshold: str = Field(description="清算阈値（0~1）")
    liq_price: str = Field(description="ETH 跌至这个价格时触发清算风险；无借贷或无法计算时返回 '0'")


class LiquidationLineResponse(BaseModel):
    address: str
    current_eth_price_usd: str = Field(description="当前 ETH/USD 价格（来自链上 Oracle）")
    liquidation_eth_price_usd: str = Field(
        description="ETH 跌至该价格时健康系数将触碰 1.0（触发清算风险）；"
                    "无借贷时返回 '0'"
    )
    distance_pct: str = Field(
        description="当前价格距清算价的百分比。正数=安全空间，负数=已超过清算价"
    )
    health_factor: str
    note: str = Field(default="", description="计算备注，如无 ETH 抵押品时的说明")


class PriceResponse(BaseModel):
    asset: str = Field(description="资产符号，如 ETH")
    price_usd: str = Field(description="当前 USD 价格（链上 Oracle）")
    token_address: str = Field(description="对应的代币合约地址")
