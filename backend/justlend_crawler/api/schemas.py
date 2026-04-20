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
    markets: list["JustLendMarketListItem"] = Field(description="当前市场列表。")


class JustLendMarketListItem(BaseModel):
    market: str = Field(description="JustLend 市场地址。")
    symbol: str | None = Field(description="jToken 符号。")
    underlying_address: str | None = Field(description="标的资产地址。")
    underlying_symbol: str | None = Field(description="标的资产符号。")
    updated_at: str = Field(description="最近更新时间。")


class JustLendMarketStateResponse(BaseModel):
    chain: str = Field(description="目标链。")
    protocol: str = Field(description="协议标识。")
    market: str = Field(description="JustLend 市场地址。")
    market_type: str = Field(description="市场类型。")
    symbol: str | None = Field(description="jToken 符号。")
    underlying_address: str | None = Field(description="标的资产地址。")
    underlying_symbol: str | None = Field(description="标的资产符号。")
    underlying_decimals: int | None = Field(description="标的资产 decimals。")
    jtoken_decimals: int | None = Field(description="jToken decimals。")
    comptroller_address: str | None = Field(description="Comptroller 地址。")
    oracle_address: str | None = Field(description="Oracle 地址。")
    is_listed: bool | None = Field(description="市场是否已上市。")
    is_entered_supported: bool | None = Field(
        description="是否支持作为 entered market。"
    )
    collateral_factor: str | None = Field(description="抵押系数。")
    reserve_factor: str | None = Field(description="储备系数。")
    borrow_cap: str | None = Field(description="借款上限。")
    supply_cap: str | None = Field(description="供给上限。")
    exchange_rate: str | None = Field(description="exchange rate。")
    cash: str | None = Field(description="市场可用现金。")
    total_borrows: str | None = Field(description="总借款量。")
    total_reserves: str | None = Field(description="总储备量。")
    total_supply: str | None = Field(description="总供给量。")
    utilization: str | None = Field(description="利用率。")
    borrow_rate: str | None = Field(description="原始 borrow rate。")
    supply_rate: str | None = Field(description="原始 supply rate。")
    underlying_price_in_trx: str | None = Field(description="标的价格，TRX 计价。")
    price_usd: str | None = Field(description="标的价格，USD 计价。")
    timestamp: str = Field(description="快照时间。")
    block_timestamp: str | None = Field(description="链上时间。")
    block_number: int | None = Field(description="链上区块号。")
    extra: dict = Field(description="附加原始字段。")


class JustLendMarketStatePeriodResponse(BaseModel):
    points: list[JustLendMarketStateResponse] = Field(
        description="时间区间内的市场状态点。"
    )


class JustLendPositionAssetResponse(BaseModel):
    asset_address: str = Field(description="TRON 资产地址。")
    symbol: str | None = Field(description="资产符号。")
    side: str = Field(description="仓位方向，collateral、supply 或 borrow。")
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


class JustLendPositionListItemResponse(BaseModel):
    protocol: str = Field(description="协议标识。")
    chain: str = Field(description="链标识。")
    address: str = Field(description="TRON 用户地址。")
    snapshot_at: str = Field(description="本次仓位快照时间。")
    block_timestamp: str = Field(description="底层数据时间戳。")
    total_supply_usd: str = Field(description="总 supply USD 价值。")
    total_collateral_usd: str = Field(description="总抵押 USD 价值。")
    total_borrow_usd: str = Field(description="总 borrow USD 价值。")
    health_factor: str = Field(description="健康因子。")
    ltv: str = Field(description="估算加权抵押率。")
    liquidation_threshold: str = Field(description="估算清算阈值。")
    matched_asset_value_usd: str | None = Field(
        default=None,
        description="按指定 side + asset 排序时命中的资产 USD 价值。",
    )
    assets: list[JustLendPositionAssetResponse] = Field(
        default_factory=list,
        description="逐资产仓位明细；detail=false 时为空。",
    )


class JustLendPositionsResponse(BaseModel):
    items: list[JustLendPositionListItemResponse] = Field(
        description="当前仓位概览列表。"
    )
    page: int = Field(description="当前页码，从 1 开始。")
    page_size: int = Field(description="分页大小。")
    total: int = Field(description="命中的总仓位数。")
    sort_by: str = Field(description="排序字段。")
    order: str = Field(description="排序方向。")
    side: str = Field(description="仓位侧别过滤。")
    asset: str | None = Field(
        default=None,
        description="按资产排序时使用的 TRON 资产地址。",
    )


class JustLendPositionReplayPoint(BaseModel):
    tx_hash: str = Field(description="交易哈希。")
    timestamp: str = Field(description="交易时间（UTC）。")
    block_number: int | None = Field(
        description="底层区块号，JustLend API 暂未提供时为空。"
    )
    market: str | None = Field(description="JustLend 市场地址。")
    symbol: str | None = Field(description="市场或资产符号。")
    operation_type: str | None = Field(description="归一化交易类型。")
    total_collateral_usd: str = Field(description="总抵押 USD 价值。")
    total_debt_usd: str = Field(description="总债务 USD 价值。")
    available_borrow_usd: str = Field(description="估算剩余可借 USD 价值。")
    discounted_collateral_usd: str = Field(description="折算后抵押 USD 价值。")
    liquidation_buffer_usd: str = Field(description="清算缓冲 USD 价值。")
    health_factor: str = Field(description="健康因子。")
    ltv: str = Field(description="估算加权抵押率。")
    liquidation_threshold: str = Field(description="估算清算阈值。")
    brief: str = Field(description="该数据点的简要说明。")
    assets: list[JustLendPositionAssetResponse] = Field(
        default_factory=list, description="逐资产仓位明细。"
    )


class JustLendPositionReplayResponse(BaseModel):
    address: str = Field(description="TRON 用户地址。")
    protocol: str = Field(description="协议标识。")
    from_time: str = Field(description="起始时间（UTC）。")
    to_time: str = Field(description="结束时间（UTC）。")
    data_source: str = Field(description="数据来源：cache、api 或 mixed。")
    points: list[JustLendPositionReplayPoint] = Field(description="历史快照数据点。")
    total_points: int = Field(description="返回的数据点数量。")
    total_tx_count: int = Field(description="时间范围内命中的仓位相关交易数。")
    cache_hit_rate: str = Field(description="快照缓存命中率。")
