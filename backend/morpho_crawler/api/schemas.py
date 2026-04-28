"""Pydantic schemas for Morpho APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field

from pydantic import ConfigDict  # api/morpho/vault/v1/state相关


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


# api/morpho/vault/v1/state相关：文档结构（类型展示）
class MorphoVaultTokenInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    address: str = Field(description="EVM 地址。")
    symbol: str | None = Field(default=None, description="代币符号。")
    decimals: int | None = Field(default=None, description="代币精度。")


class MorphoVaultV1AllocationMarket(BaseModel):
    model_config = ConfigDict(extra="allow")

    market_id: str = Field(description="市场 id。")
    loanAsset: MorphoVaultTokenInfo = Field(description="借贷侧资产。")
    collateralAsset: MorphoVaultTokenInfo = Field(description="抵押侧资产。")
    dataSource: str | None = Field(default=None, description="数据来源标记。")


class MorphoVaultV1AllocationItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    market: MorphoVaultV1AllocationMarket = Field(description="关联市场信息。")
    supplyAssetsUsd: float | None = Field(
        default=None, description="该市场供应资产 USD。"
    )
    supplyCapUsd: float | None = Field(default=None, description="该市场供应上限 USD。")
    liquidityUsd: float | None = Field(
        default=None, description="该市场可提取流动性 USD。"
    )


class MorphoVaultV1StatePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    totalAssetsUsd: float | None = Field(default=None, description="总资产 USD。")
    apy: float | None = Field(default=None, description="APY。")
    netApy: float | None = Field(default=None, description="净 APY。")
    netApyExcludingRewards: float | None = Field(
        default=None, description="剔除奖励后的净 APY。"
    )
    avgNetApy: float | None = Field(default=None, description="平均净 APY。")
    avgNetApyExcludingRewards: float | None = Field(
        default=None, description="平均净 APY（剔除奖励）。"
    )
    timelock: int | None = Field(default=None, description="时间锁秒数。")
    fee: float | None = Field(default=None, description="费率。")
    liquidityUsd: float | None = Field(default=None, description="流动性 USD。")
    allocation: list[MorphoVaultV1AllocationItem] = Field(
        default_factory=list, description="allocation 列表。"
    )


class MorphoVaultV1ByAddress(BaseModel):
    model_config = ConfigDict(extra="allow")

    address: str = Field(description="金库地址。")
    name: str | None = Field(default=None, description="金库名称。")
    asset: MorphoVaultTokenInfo = Field(description="金库资产信息。")
    state: MorphoVaultV1StatePayload = Field(description="金库状态。")
    dataSource: str | None = Field(default=None, description="数据来源标记。")


class MorphoVaultV1Data(BaseModel):
    model_config = ConfigDict(extra="allow")

    vaultByAddress: MorphoVaultV1ByAddress = Field(description="V1 金库结果。")


class MorphoVaultV1StateGraphQLResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: MorphoVaultV1Data = Field(description="GraphQL data 字段。")


# [V2_STATE_ADAPTERS_ADD] 新增：V2 adapters 输出结构（保持 extra 兼容）
class MorphoVaultV2MetaMorphoPositionState(BaseModel):
    model_config = ConfigDict(extra="allow")

    address: str | None = Field(default=None, description="MetaMorpho position 标识。")
    assets: float | int | None = Field(default=None, description="资产数量。")
    assetsUsd: float | None = Field(default=None, description="资产 USD。")


class MorphoVaultV2MetaMorphoPosition(BaseModel):
    model_config = ConfigDict(extra="allow")

    state: MorphoVaultV2MetaMorphoPositionState | None = Field(default=None)


class MorphoVaultV2AdapterMarketPositionState(BaseModel):
    model_config = ConfigDict(extra="allow")

    supplyAssets: float | int | None = Field(default=None, description="供给资产。")
    supplyAssetsUsd: float | None = Field(default=None, description="供给资产 USD。")


class MorphoVaultV2AdapterMarketPositionItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    market_id: str | None = Field(default=None, description="市场标识。")
    state: MorphoVaultV2AdapterMarketPositionState | None = Field(default=None)


class MorphoVaultV2AdapterMarketPositions(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[MorphoVaultV2AdapterMarketPositionItem] = Field(default_factory=list)


class MorphoVaultV2AdapterItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str | None = Field(default=None, description="Adapter 类型。")
    assets: float | int | None = Field(default=None, description="资产数量。")
    assetsUsd: float | None = Field(default=None, description="资产 USD。")
    position: MorphoVaultV2MetaMorphoPosition | None = Field(default=None)
    positions: MorphoVaultV2AdapterMarketPositions | None = Field(default=None)


class MorphoVaultV2AdaptersPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[MorphoVaultV2AdapterItem] = Field(default_factory=list)


class MorphoVaultV2ByAddress(BaseModel):
    model_config = ConfigDict(extra="allow")

    address: str = Field(description="金库地址。")
    name: str | None = Field(default=None, description="金库名称。")
    totalAssetsUsd: float | None = Field(default=None, description="总资产 USD。")
    idleAssetsUsd: float | None = Field(default=None, description="空闲资产 USD。")
    liquidityUsd: float | None = Field(default=None, description="流动性 USD。")
    apy: float | None = Field(default=None, description="APY。")
    netApy: float | None = Field(default=None, description="净 APY。")
    netApyExcludingRewards: float | None = Field(
        default=None, description="剔除奖励净 APY。"
    )
    avgNetApy: float | None = Field(default=None, description="平均净 APY。")
    avgNetApyExcludingRewards: float | None = Field(
        default=None, description="平均净 APY（剔除奖励）。"
    )
    maxApy: float | None = Field(default=None, description="最大 APY。")
    forceDeallocatableLiquidityUsd: float | None = Field(
        default=None, description="可强制释放流动性 USD。"
    )
    performanceFee: float | None = Field(default=None, description="业绩费。")
    managementFee: float | None = Field(default=None, description="管理费。")
    asset: MorphoVaultTokenInfo = Field(description="金库资产信息。")
    # [V2_STATE_ADAPTERS_ADD] 新增：在原有输出上追加 adapters 字段
    adapters: MorphoVaultV2AdaptersPayload | None = Field(
        default=None, description="Adapter 列表。"
    )
    dataSource: str | None = Field(default=None, description="数据来源标记。")


class MorphoVaultV2StateGraphQLResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "vaultV2ByAddress": {
                    "address": "string",
                    "name": "string",
                    "totalAssetsUsd": 0.0,
                    "idleAssetsUsd": 0.0,
                    "liquidityUsd": 0.0,
                    "apy": 0.0,
                    "netApy": 0.0,
                    "netApyExcludingRewards": 0.0,
                    "avgNetApy": 0.0,
                    "avgNetApyExcludingRewards": 0.0,
                    "maxApy": 0.0,
                    "forceDeallocatableLiquidityUsd": 0.0,
                    "performanceFee": 0.0,
                    "managementFee": 0.0,
                    "asset": {
                        "address": "string",
                        "symbol": "string",
                        "decimals": 6,
                    },
                    "adapters": {
                        "items": [
                            {
                                "type": "MetaMorpho",
                                "position": {
                                    "state": {
                                        "address": "string",
                                        "assets": 0,
                                        "assetsUsd": 0,
                                    }
                                },
                                "dataSource": "table",
                            },
                            {
                                "type": "MorphoMarketV1",
                                "assets": 0,
                                "assetsUsd": 0.0,
                                "positions": {
                                    "items": [
                                        {
                                            "market_id": "string",
                                            "state": {
                                                "supplyAssets": 0,
                                                "supplyAssetsUsd": 0.0,
                                            },
                                        }
                                    ]
                                },
                                "dataSource": "table",
                            },
                        ]
                    },
                    "dataSource": "table",
                }
            }
        },
    )

    vaultV2ByAddress: MorphoVaultV2ByAddress = Field(description="V2 金库结果。")


# api/morpho/vaults相关：总表资产信息
class MorphoVotesAsset(BaseModel):
    asset: str = Field(description="资产名称（symbol）。")
    token_address: str = Field(description="资产地址（EVM）。")


# api/morpho/vaults相关：单条金库概览
class MorphoVotesItem(BaseModel):
    address: str = Field(description="金库地址。")
    name: str = Field(description="金库名称。")
    asset: MorphoVotesAsset = Field(description="资产信息。")
    total_assets_usd: float = Field(description="总资产（USD）。")
    liquidity: float = Field(description="流动性（USD）。")
    apy: float = Field(description="APY。")
    protocol: str = Field(description="协议版本：v1 或 v2。")


# api/morpho/vaults相关：分页响应
class MorphoVotesResponse(BaseModel):
    page: int = Field(description="当前页。")
    page_size: int = Field(description="每页条数。")
    total: int = Field(description="总条数。")
    items: list[MorphoVotesItem] = Field(description="分页数据。")
