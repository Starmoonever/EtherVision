"""Pydantic schemas for JustLend scaffold APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class JustLendScaffoldStatusResponse(BaseModel):
    module: str = Field(description="模块名。")
    status: str = Field(description="当前实现状态。")
    chain: str = Field(description="目标链。")
    supported_protocols: list[str] = Field(description="当前保留的协议标识。")
    message: str = Field(description="当前骨架说明。")


class JustLendMarketResponse(BaseModel):
    chain: str = Field(description="目标链。")
    markets: list[str] = Field(description="当前预留的市场列表。")


class JustLendPositionAssetResponse(BaseModel):
    asset_address: str = Field(description="TRON 资产地址。")
    symbol: str | None = Field(description="资产符号。")
    side: str = Field(description="仓位方向，collateral 或 borrow。")
    amount: str = Field(description="资产数量。")
    price_usd: str = Field(description="资产当前 USD 价格。")
    value_usd: str = Field(description="该仓位方向对应的 USD 价值。")


class JustLendPositionResponse(BaseModel):
    protocol: str = Field(description="协议标识。")
    chain: str = Field(description="链标识。")
    address: str = Field(description="TRON 用户地址。")
    snapshot_at: str = Field(description="本次仓位快照时间。")
    block_timestamp: str = Field(description="底层数据时间戳。")
    total_collateral_usd: str = Field(description="总抵押 USD 价值。")
    total_debt_usd: str = Field(description="总债务 USD 价值。")
    available_borrow_usd: str = Field(description="估算剩余可借 USD 价值。")
    health_factor: str = Field(description="健康因子。")
    ltv: str = Field(description="估算加权抵押率。")
    liquidation_threshold: str = Field(description="估算清算阈值。")
    data_source: str = Field(description="数据来源：database 或 api。")
    assets: list[JustLendPositionAssetResponse] = Field(description="逐资产仓位明细。")
