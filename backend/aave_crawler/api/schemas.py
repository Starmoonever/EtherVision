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
    price_usd: str = Field(description="USD 价格")
    token_address: str = Field(description="对应的代币合约地址")
    timestamp: str = Field(description="价格对应的 UTC 时间，格式如 2024-11-14T12:00:00Z")
    source: str = Field(description="数据来源：on-chain（链上 Oracle）或 defillama（DeFiLlama 历史）")


class HistoricalReserveDetail(BaseModel):
    symbol: str
    token_address: str
    supply_amount: str = Field(description="净供给量（含利息估算，原生单位）")
    debt_amount: str = Field(description="净借贷量（含利息估算，原生单位）")


class HistoricalPositionResponse(BaseModel):
    address: str
    at_time: str = Field(description="查询时间点（UTC）")
    eth_collateral_amount: str = Field(description="ETH/WETH 类抵押品合计（含利息，原生单位）")
    eth_price_usd: str = Field(description="该时刻 ETH 价格（来自 DeFiLlama）")
    eth_collateral_usd: str = Field(description="ETH 抵押品 USD 估值")
    total_debt_approx_usd: str = Field(description="总借贷 USD 近似值（仅借贷代币当时价格 × 金额，不含其他资产利率影响）")
    liq_price: str = Field(description="近似清算价格（0 表示无借贷或无法计算）")
    reserves: list[HistoricalReserveDetail] = Field(description="按资产明细，仅含有操作记录的资产")
    note: str = Field(
        default="",
        description=(
            "供给量通过 scaled balance × liquidity_index 计算含利息，"
            "但不含用户最后一次操作到查询时间之间的利息累积"
        ),
    )
