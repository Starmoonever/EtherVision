"""Protocol-agnostic API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PriceResponse(BaseModel):
    asset: str = Field(description="资产符号，如 ETH")
    price_usd: str = Field(description="USD 价格")
    token_address: str = Field(description="对应的代币合约地址")
    timestamp: str = Field(
        description="价格对应的 UTC 时间，格式如 2024-11-14T12:00:00Z"
    )
    source: str = Field(
        description="数据来源：on-chain（链上 Oracle）或 defillama（DeFiLlama 历史）"
    )


class PriceAssetSchema(BaseModel):
    asset: str = Field(description="资产符号，如 ETH、WBTC、USDT。")
    token_address: str = Field(description="资产地址。")
    chain: str = Field(description="资产所属链，如 ethereum 或 tron。")


class PriceAssetsResponse(BaseModel):
    assets: list[PriceAssetSchema] = Field(description="当前支持价格查询的资产列表。")


class PricePeriodItem(BaseModel):
    price_usd: str = Field(description="USD 价格（2 位小数）")
    timestamp: str = Field(description="UTC 时间，格式如 2024-11-14T12:00:00Z")


class PricePeriodResponse(BaseModel):
    asset: str = Field(description="资产符号，如 ETH")
    token_address: str = Field(description="对应的代币合约地址")
    source: str = Field(default="defillama", description="数据来源，固定为 defillama")
    prices: list[PricePeriodItem] = Field(description="按时间升序排列的价格序列")
