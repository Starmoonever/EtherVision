"""Pydantic schemas for MakerDAO APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MakerDaoScaffoldStatusResponse(BaseModel):
    module: str = Field(description="模块名。")
    status: str = Field(description="当前实现状态。")
    chain: str = Field(description="目标链。")
    supported_protocols: list[str] = Field(description="当前保留的协议标识。")
    message: str = Field(description="当前骨架说明。")


class MakerDaoIlkOverviewItem(BaseModel):
    ilk: str = Field(description="MakerDAO ilk 名称。")
    vault_type: str = Field(description="仓位类型。")
    gem_symbol: str | None = Field(description="抵押资产符号。")
    gem_address: str | None = Field(description="抵押资产地址。")
    updated_at: str = Field(description="最近更新时间。")


class MakerDaoIlkListResponse(BaseModel):
    chain: str = Field(description="链标识。")
    protocol: str = Field(description="协议标识。")
    ilks: list[MakerDaoIlkOverviewItem] = Field(description="可用 ilk 概览列表。")


class MakerDaoIlkDetailResponse(BaseModel):
    chain: str = Field(description="链标识。")
    protocol: str = Field(description="协议标识。")
    ilk: str = Field(description="MakerDAO ilk 名称。")
    vault_type: str = Field(description="仓位类型。")
    gem_symbol: str | None = Field(description="抵押资产符号。")
    gem_address: str | None = Field(description="抵押资产地址。")
    debt_ceiling: str | None = Field(description="债务上限。")
    liquidation_ratio: str | None = Field(description="清算比率。")
    liquidation_penalty: str | None = Field(description="清算罚金。")
    stability_fee: str | None = Field(description="稳定费。")
    dust: str | None = Field(description="最小债务规模。")
    updated_at: str = Field(description="最近更新时间。")


class MakerDaoPositionAssetResponse(BaseModel):
    role: str = Field(description="资产角色：collateral 或 debt。")
    token_address: str | None = Field(description="代币地址。")
    symbol: str | None = Field(description="代币符号。")
    amount: str = Field(description="资产数量。")
    value_usd: str | None = Field(description="资产价值（USD）。")


class MakerDaoVaultPositionItemResponse(BaseModel):
    vault_uid: str = Field(description="仓位唯一标识。")
    vault_id: int | None = Field(description="Vault 编号。")
    vault_type: str = Field(description="仓位类型。")
    ilk: str = Field(description="MakerDAO ilk 名称。")
    urn_address: str = Field(description="urn 地址。")
    owner_address: str | None = Field(description="owner 地址。")
    proxy_address: str | None = Field(description="proxy 地址。")
    block_number: int | None = Field(description="快照区块号。")
    block_timestamp: str = Field(description="快照区块时间。")
    snapshot_at: str = Field(description="缓存写入时间。")
    collateral_symbol: str | None = Field(description="抵押资产符号。")
    collateral_token_address: str | None = Field(description="抵押资产地址。")
    collateral_amount: str = Field(description="抵押数量。")
    collateral_value_usd: str | None = Field(description="抵押价值（USD）。")
    debt_symbol: str = Field(description="债务资产符号。")
    debt_token_address: str | None = Field(description="债务资产地址。")
    debt_amount: str = Field(description="债务数量。")
    debt_value_usd: str | None = Field(description="债务价值（USD）。")
    liquidation_ratio: str | None = Field(description="清算比率。")
    liquidation_price_usd: str | None = Field(description="清算价格（USD）。")
    health_factor: str | None = Field(description="健康因子。")
    is_healthy: bool = Field(description="仓位是否健康。")
    data_source: str = Field(description="数据来源。")
    assets: list[MakerDaoPositionAssetResponse] = Field(description="资产明细。")


class MakerDaoVaultPositionResponse(BaseModel):
    chain: str = Field(description="链标识。")
    protocol: str = Field(description="协议标识。")
    address: str = Field(description="查询地址。")
    total_positions: int = Field(description="命中的仓位数量。")
    positions: list[MakerDaoVaultPositionItemResponse] = Field(
        description="当前仓位列表。"
    )
