"""Pydantic schemas for Morpho APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MorphoScaffoldStatusResponse(BaseModel):
    module: str = Field(description="模块名。")
    status: str = Field(description="当前实现状态。")
    chain: str = Field(description="目标链。")
    supported_protocols: list[str] = Field(description="当前保留的协议标识。")
    message: str = Field(description="当前骨架说明。")


class MorphoPositionAssetResponse(BaseModel):
    role: str = Field(description="资产角色：loan 或 collateral。")
    token_address: str = Field(description="代币地址。")
    symbol: str | None = Field(description="代币符号。")
    decimals: int = Field(description="代币 decimals。")
    amount: str = Field(description="按 decimals 缩放后的资产数量。")
    price_usd: str | None = Field(default=None, description="资产单价（USD）。")
    value_usd: str | None = Field(default=None, description="资产价值（USD）。")


class MorphoPositionResponse(BaseModel):
    protocol: str = Field(description="协议标识。")
    market_type: str = Field(description="Morpho 市场类型。")
    chain: str = Field(description="链标识。")
    morpho_address: str = Field(description="Morpho Blue 合约地址。")
    market_id: str = Field(description="市场 id。")
    address: str = Field(description="EVM 用户地址。")
    block_number: int = Field(description="查询时所用区块号。")
    block_timestamp: str = Field(description="查询时区块时间。")
    has_position: bool = Field(description="该用户在该市场是否有非零仓位。")
    is_healthy: bool = Field(description="按当前 oracle 价格估算，仓位是否健康。")
    loan_token: str = Field(description="借贷 token 地址。")
    loan_token_symbol: str | None = Field(description="借贷 token 符号。")
    loan_token_decimals: int = Field(description="借贷 token decimals。")
    collateral_token: str = Field(description="抵押 token 地址。")
    collateral_token_symbol: str | None = Field(description="抵押 token 符号。")
    collateral_token_decimals: int = Field(description="抵押 token decimals。")
    oracle: str = Field(description="oracle 地址。")
    irm: str = Field(description="irm 地址。")
    lltv: str = Field(description="lltv，WAD 精度。")
    lltv_ratio: str = Field(description="lltv 的十进制形式。")
    supply_shares: str = Field(description="原始 supply shares。")
    borrow_shares: str = Field(description="原始 borrow shares。")
    collateral_assets_raw: str = Field(description="原始 collateral 数量。")
    supply_assets: str = Field(description="估算后的 supply assets。")
    borrow_assets: str = Field(description="估算后的 borrow assets。")
    collateral_assets: str = Field(description="按 decimals 缩放后的 collateral 数量。")
    collateral_value_in_loan_asset: str = Field(
        description="抵押价值，单位为 loan asset。"
    )
    max_borrowable_in_loan_asset: str = Field(
        description="按 lltv 估算的最大可借数量，单位为 loan asset。"
    )
    health_factor: str | None = Field(description="健康因子；无借款时返回 null。")
    price_quote: str = Field(
        description="oracle 返回的价格，表示 1 单位 collateral 对应的 loan asset 价格。"
    )
    data_source: str = Field(description="数据来源：rpc。")
    assets: list[MorphoPositionAssetResponse] = Field(description="资产明细。")


class MorphoPositionReplayPointResponse(BaseModel):
    tx_hash: str = Field(description="交易哈希。")
    timestamp: str = Field(description="交易所在区块时间。")
    block_number: int = Field(description="交易所在区块号。")
    operation_type: str | None = Field(description="主操作类型。")
    brief: str = Field(description="面向前端展示的简短说明。")
    has_position: bool = Field(description="交易后该市场是否仍有非零仓位。")
    is_healthy: bool = Field(description="交易后仓位是否健康。")
    collateral_value_in_loan_asset: str = Field(
        description="交易后抵押价值，单位为 loan asset。"
    )
    borrow_assets: str = Field(description="交易后债务数量，单位为 loan asset。")
    health_factor: str | None = Field(description="交易后健康因子。")
    assets: list[MorphoPositionAssetResponse] = Field(description="交易后资产明细。")


class MorphoPositionReplayResponse(BaseModel):
    protocol: str = Field(description="协议标识。")
    market_type: str = Field(description="Morpho 市场类型。")
    chain: str = Field(description="链标识。")
    market_id: str = Field(description="市场 id。")
    address: str = Field(description="EVM 用户地址。")
    from_time: str = Field(description="起始时间。")
    to_time: str = Field(description="结束时间。")
    data_source: str = Field(description="数据来源：cache 或 rpc。")
    total_points: int = Field(description="返回的时间线点位数。")
    total_tx_count: int = Field(description="命中的交易数。")
    cache_hit_rate: str = Field(description="缓存命中率。")
    points: list[MorphoPositionReplayPointResponse] = Field(description="重放点位。")


# api/morpho/markets相关：GET /api/morpho/markets
class MorphoMarketAssetItem(BaseModel):
    asset: str = Field(description="资产符号。")
    token_address: str = Field(description="代币地址。")
    role: str = Field(description="资产角色：loan 或 collateral。")


# api/morpho/markets相关：GET /api/morpho/markets
class MorphoMarketListItem(BaseModel):
    market_id: str = Field(description="市场 id。")
    dataSource: str = Field(description="市场数据来源：table 或 chain。")
    assets: list[MorphoMarketAssetItem] = Field(
        description="市场资产列表，使用 role 区分 loan/collateral。"
    )
    total_market_size_usd: float | None = Field(
        default=None,
        description="Morpho Blue API 的 TVL（state.sizeUsd），美元。",
    )
    utilization: float | None = Field(
        default=None,
        description="利用率（state.utilization，0~1）。",
    )


# api/morpho/markets相关：GET /api/morpho/markets（分页）
class MorphoMarketListResponse(BaseModel):
    page: int = Field(description="当前页码（从 1 开始）。")
    page_size: int = Field(description="每页条数。")
    total_count: int = Field(description="市场缓存表中的总市场数。")
    total_pages: int = Field(description="总页数。")
    markets: list[MorphoMarketListItem] = Field(
        description="本页市场列表（含 TVL 与利用率）。"
    )


# api/morpho/market/state相关：GET /api/morpho/market/state（嵌套字段）
class MorphoMarketTokenInfo(BaseModel):
    address: str = Field(description="代币地址。")
    symbol: str | None = Field(description="代币符号。")
    decimals: int | None = Field(description="代币 decimals。")


# api/morpho/market/state相关：GET /api/morpho/market/state
class MorphoMarketRatioField(BaseModel):
    formula: str = Field(description="指标计算公式。")
    value: str = Field(description="指标值。")


# api/morpho/market/state相关：GET /api/morpho/market/state
class MorphoMarketSimpleMetricField(BaseModel):
    formula: str = Field(description="指标计算公式。")
    value: str = Field(description="指标值。")
    note: str | None = Field(default=None, description="指标备注。")


# api/morpho/market/state相关：GET /api/morpho/market/state（根响应模型）
class MorphoMarketStateResponse(BaseModel):
    marketId: str = Field(description="Morpho market id。")
    dataSource: str = Field(description="数据来源：table 或 chain。")
    total_market_size_usd: float | None = Field(
        default=None,
        description="市场规模（USD，来自缓存表）。",
    )
    loanToken: MorphoMarketTokenInfo = Field(description="借出资产信息。")
    collateralToken: MorphoMarketTokenInfo = Field(description="抵押资产信息。")
    oracle: str = Field(description="Oracle 地址。")
    irm: str = Field(description="IRM 地址。")
    lltv: dict[str, str] = Field(description="LLTV 原始值与比例。")
    totalSupplyAssets: str = Field(description="市场总供应资产（raw）。")
    totalSupplyShares: str = Field(description="市场总供应份额（raw）。")
    totalBorrowAssets: str = Field(description="市场总借款资产（raw）。")
    totalBorrowShares: str = Field(description="市场总借款份额（raw）。")
    lastUpdate: int = Field(description="市场最后更新时间戳。")
    fee: str = Field(description="市场 fee（raw）。")
    utilization: MorphoMarketRatioField = Field(description="利用率指标。")
    availableLiquidity: MorphoMarketSimpleMetricField = Field(
        description="可用流动性指标。"
    )
    borrowCapacityUsageRough: MorphoMarketSimpleMetricField = Field(
        description="借款上限占用粗估。"
    )
    annualBorrowRate: MorphoMarketSimpleMetricField = Field(
        description="当前借款秒利率线性年化比例。"
    )
    annualBorrowInterestRatio: MorphoMarketSimpleMetricField = Field(
        description="按当前利率估算一年利息/本金比例。"
    )
    annualSupplyRate: MorphoMarketSimpleMetricField = Field(
        description="当前出借侧秒利率线性年化比例。"
    )
    annualSupplyInterestRatio: MorphoMarketSimpleMetricField = Field(
        description="按当前出借侧利率估算一年利息/本金比例。"
    )
    marketScaleTvlLike: MorphoMarketSimpleMetricField = Field(
        description="市场规模（TVL-like）。"
    )
    debtScaleDebtLike: MorphoMarketSimpleMetricField = Field(
        description="借款规模（Debt-like）。"
    )
