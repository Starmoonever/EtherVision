"""API 层 Pydantic 响应模型"""

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
    total_collateral_usd: str = Field(
        description="总抵押 USD 估值（含 ETH 和其他资产）"
    )
    available_borrows_usd: str = Field(description="可借 USD 额度")
    total_debt_usd: str = Field(description="总借贷 USD")
    health_factor: str = Field(description="健康系数；无借贷时返回 'inf'")
    ltv: str = Field(description="贷款价値比（0~1）")
    liq_threshold: str = Field(description="清算阈値（0~1）")
    liq_price: str = Field(
        description="ETH 跌至这个价格时触发清算风险；无借贷或无法计算时返回 '0'"
    )


class LiqPriceResponse(BaseModel):
    address: str
    current_eth_price_usd: str = Field(
        description="当前 ETH/USD 价格（来自链上 Oracle）"
    )
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
    timestamp: str = Field(
        description="价格对应的 UTC 时间，格式如 2024-11-14T12:00:00Z"
    )
    source: str = Field(
        description="数据来源：on-chain（链上 Oracle）或 defillama（DeFiLlama 历史）"
    )


class PricePeriodItem(BaseModel):
    price_usd: str = Field(description="USD 价格（2 位小数）")
    timestamp: str = Field(description="UTC 时间，格式如 2024-11-14T12:00:00Z")


class PricePeriodResponse(BaseModel):
    asset: str = Field(description="资产符号，如 ETH")
    token_address: str = Field(description="对应的代币合约地址")
    source: str = Field(default="defillama", description="数据来源，固定为 defillama")
    prices: list[PricePeriodItem] = Field(description="按时间升序排列的价格序列")


class LiquidationSimItem(BaseModel):
    address: str
    liq_price: str = Field(description="该地址的 ETH 清算触发价（USD）")
    eth_collateral_amount: str = Field(description="ETH/WETH 抵押数量")
    eth_collateral_usd: str = Field(
        description="ETH 抵押品在模拟价格下的 USD 估值（eth_collateral_amount × eth_price）"
    )
    total_debt_usd: str = Field(description="总借贷 USD（快照时刻）")


class LiquidationSimResponse(BaseModel):
    simulated_eth_price: str = Field(description="本次模拟使用的 ETH 价格（USD）")
    positions: list[LiquidationSimItem] = Field(
        description="在此价格下触发清算的所有仓位，按 liq_price 降序排列"
    )
    positions_cnt: str = Field(description="触发清算的仓位数量")
    total_eth_collateral_amount: str = Field(description="可被清算的 ETH 抵押品总量")
    total_eth_collateral_usd: str = Field(
        description="可被清算的 ETH 抵押品在模拟价格下的总 USD 估值"
    )
    total_liquidation_usd: str = Field(
        description=(
            "清算人实际可获取的抵押品 USD 总估值（含清算奖励折价）。"
            "计算方式：min(债务 × 清算奖励系数, ETH 抵押品 USD) 逐仓累加，"
            "默认使用 Aave V3 WETH 清算奖励系数 1.05（5% 折价优惠）。"
        )
    )
    note: str = Field(
        default="", description="备注，如参与计算的仓位数量、使用的清算奖励系数等"
    )


class LiquidationPeriodItem(BaseModel):
    simulated_eth_price: str = Field(description="模拟 ETH 价格（USD）")
    positions_cnt: str = Field(description="在此价格下触发清算的仓位数量")
    total_eth_collateral_amount: str = Field(description="可被清算的 ETH 抵押品总量")
    total_eth_collateral_usd: str = Field(
        description="可被清算的 ETH 抵押品总 USD 估值（按模拟价格）"
    )
    total_liquidation_usd: str = Field(
        description="清算人可获得的抵押品总 USD 价值（含 5% 清算奖励）"
    )


class HistoricalReserveDetail(BaseModel):
    symbol: str
    token_address: str
    supply_amount: str = Field(description="净供给量（含利息估算，原生单位）")
    debt_amount: str = Field(description="净借贷量（含利息估算，原生单位）")


class HistoricalPositionResponse(BaseModel):
    address: str
    at_time: str = Field(description="查询时间点（UTC）")
    eth_collateral_amount: str = Field(
        description="ETH/WETH 类抵押品合计（含利息，原生单位）"
    )
    eth_price_usd: str = Field(description="该时刻 ETH 价格（来自 DeFiLlama）")
    eth_collateral_usd: str = Field(description="ETH 抵押品 USD 估值")
    total_debt_approx_usd: str = Field(
        description="总借贷 USD 近似值（仅借贷代币当时价格 × 金额，不含其他资产利率影响）"
    )
    liq_price: str = Field(description="近似清算价格（0 表示无借贷或无法计算）")
    reserves: list[HistoricalReserveDetail] = Field(
        description="按资产明细，仅含有操作记录的资产"
    )
    note: str = Field(
        default="",
        description=(
            "供给量通过 scaled balance × liquidity_index 计算含利息，"
            "但不含用户最后一次操作到查询时间之间的利息累积"
        ),
    )


# ── 借贷端（做空 ETH / borrow WETH）清算分析 ─────────────────────────────────


class BorrowPositionResponse(BaseModel):
    """借贷端仓位：用户借入 WETH，ETH 上涨时面临清算风险。"""

    address: str
    weth_debt_amount: str = Field(description="ETH 系负债合计数量（换算 decimals 后）")
    weth_debt_usd: str = Field(description="ETH 系负债 USD 估值（快照时刻价格）")
    total_collateral_usd: str = Field(description="总抵押 USD 估值")
    total_debt_usd: str = Field(description="总借贷 USD 估值")
    health_factor: str = Field(description="健康系数；无借贷时返回 'inf'")
    liq_price_rise: str = Field(
        description="ETH 涨至该价格时健康系数将触碰 1.0（触发清算风险）；"
        "0 表示不存在 ETH 上涨清算风险（如抵押品也含 ETH 系资产）"
    )


class ShortLiqSimItem(BaseModel):
    """单个做空仓位在模拟 ETH 价格下的清算信息。"""

    address: str
    liq_price_rise: str = Field(description="该地址的 ETH 上涨清算触发价（USD）")
    weth_debt_amount: str = Field(description="ETH 系负债数量")
    weth_debt_usd: str = Field(
        description="ETH 系负债在模拟价格下的 USD 估值（weth_debt_amount × eth_price）"
    )
    total_collateral_usd: str = Field(
        description="总抵押 USD 估值（快照时刻，主要为非 ETH 资产）"
    )


class ShortLiqSimResponse(BaseModel):
    """做空清算模拟汇总：ETH 上涨至 simulated_eth_price 时的清算统计。"""

    simulated_eth_price: str = Field(description="本次模拟使用的 ETH 价格（USD）")
    positions: list[ShortLiqSimItem] = Field(
        description="在此价格下触发清算的所有借贷仓位，按 liq_price_rise 升序排列"
    )
    positions_cnt: str = Field(description="触发清算的仓位数量")
    total_weth_debt_amount: str = Field(description="可被清算的 ETH 系负债总量")
    total_weth_debt_usd: str = Field(
        description="可被清算的 ETH 系负债在模拟价格下的总 USD 估值"
    )
    total_liquidation_usd: str = Field(
        description=(
            "清算人实际可获取的抵押品 USD 总估值（含清算奖励折价）。"
            "计算方式：min(WETH债务USD × 清算奖励系数, 总抵押USD) 逐仓累加，"
            "默认使用 Aave V3 WETH 清算奖励系数 1.05。"
        )
    )
    note: str = Field(default="", description="备注")


class ShortLiqPeriodItem(BaseModel):
    """做空清算区间模拟的单个价格点汇总。"""

    simulated_eth_price: str = Field(description="模拟 ETH 价格（USD）")
    positions_cnt: str = Field(description="在此价格下触发清算的仓位数量")
    total_weth_debt_amount: str = Field(description="可被清算的 ETH 系负债总量")
    total_weth_debt_usd: str = Field(
        description="可被清算的 ETH 系负债总 USD 估值（按模拟价格）"
    )
    total_liquidation_usd: str = Field(
        description="清算人可获得的抵押品总 USD 价值（含 5% 清算奖励）"
    )


class BorrowUserPositionResponse(BaseModel):
    """借贷端单用户仓位详情：仅返回借贷端专属字段，不与 /user/position 重叠。"""

    address: str
    scanned_at: str = Field(description="数据快照时间（UTC）")
    weth_debt_amount: str = Field(description="ETH 系负债合计数量（换算 decimals 后）")
    weth_debt_usd: str = Field(description="ETH 系负债 USD 估值（快照时刻价格）")
    health_factor: str = Field(description="快照时局健康系数；无借贷时返回 'inf'")
    liq_price_rise: str = Field(
        description="ETH 涨至该价格时健康系数将触碰 1.0；0 表示无 ETH 上涨清算风险"
    )
    reserves: list[ReservePositionSchema] = Field(
        description="资产明细列表，按负债 USD 降序排列"
    )


# ── 历史仓位回放（position_snapshot_cache）─────────────────────────────────────


class SnapshotReserveDetail(BaseModel):
    """快照中单个资产的明细（从 reserves_json 反序列化）。"""

    symbol: str
    token_address: str
    price_usd: str = Field(description="该区块时刻的 Oracle 价格（USD，8 位精度）")
    supply_usd: str = Field(description="供给 USD 估值")
    total_debt_usd: str = Field(description="借贷 USD 估值")
    use_as_collateral: bool


class PositionSnapshotPoint(BaseModel):
    """回放序列中的单个数据点（对应一笔 tx 时刻的链上真实仓位）。"""

    tx_hash: str
    block_number: int
    timestamp: str = Field(description="区块 UTC 时间，格式 2024-01-15T08:23:11Z")
    eth_price_usd: str = Field(description="同区块链上 Oracle ETH/USD 价格")
    total_collateral_usd: str
    total_debt_usd: str
    available_borrows_usd: str
    health_factor: str = Field(description="健康系数；无借贷时返回 'inf'")
    liq_threshold: str = Field(description="清算阈值（0~1）")
    liq_price: str = Field(description="ETH 清算触发价（USD）；0 表示无风险")
    reserves: list[SnapshotReserveDetail] = Field(
        default_factory=list,
        description="资产明细；仅当请求 detail=true 时填充",
    )


class PositionReplayResponse(BaseModel):
    """历史仓位回放响应。"""

    address: str
    protocol: str = Field(description="协议版本：v2 | v3")
    from_time: str = Field(description="查询起始时间（UTC）")
    to_time: str = Field(description="查询结束时间（UTC）")
    data_source: str = Field(
        description="数据来源：cache（全缓存命中）| rpc（全 RPC 重放）| mixed（混合）"
    )
    points: list[PositionSnapshotPoint]
    total_points: int = Field(description="返回的数据点数量")
    cache_hit_rate: str = Field(description="缓存命中率（0.00~1.00）")


class TxHistoryItem(BaseModel):
    """用户 Aave 事件列表中的单条记录（来自 aave_history）。"""

    tx_hash: str
    block_number: int
    timestamp: str = Field(description="区块 UTC 时间")
    operation_type: str = Field(description="事件类型：supply / withdraw / borrow / repay / liquidationcall 等")
    token_symbol: str = Field(description="涉及的资产符号")
    cached: bool = Field(description="该 tx 的仓位快照是否已在缓存中")


class TxHistoryResponse(BaseModel):
    """用户 Aave 历史事件列表响应。"""

    address: str
    protocol: str
    from_time: str
    to_time: str
    txs: list[TxHistoryItem]
    total: int
