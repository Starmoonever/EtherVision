from __future__ import annotations

from aave_crawler.api.schemas import (
    BorrowPositionResponse,
    BorrowUserPositionResponse,
    HistoricalPositionResponse,
    HistoricalReserveDetail,
    LiqPriceResponse,
    LiquidationPeriodItem,
    LiquidationSimItem,
    LiquidationSimResponse,
    LiquidationWaterfallResponse,
    LiquidationWaterfallTurnItem,
    PositionPeriodItem,
    PositionReplayResponse,
    PositionResponse,
    PositionSnapshotPoint,
    PricePeriodItem,
    PricePeriodResponse,
    PriceResponse,
    ReservePositionSchema,
    ShortLiqPeriodItem,
    ShortLiqSimItem,
    ShortLiqSimResponse,
    TxHistoryItem,
    TxHistoryResponse,
)

ADDR = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
WETH_ADDR = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"

MOCK_POSITION = PositionResponse(
    address=ADDR,
    eth_collateral_amount="1.500000",
    eth_collateral_usd="4500.00",
    total_collateral_usd="4500.00",
    available_borrows_usd="925.00",
    total_debt_usd="2000.00",
    health_factor="1.6875",
    ltv="0.6500",
    liq_threshold="0.8000",
    liq_price="1666.67",
)

MOCK_LIQ = LiqPriceResponse(
    address=ADDR,
    current_eth_price_usd="3000.00",
    liquidation_eth_price_usd="1666.67",
    distance_pct="44.44",
    health_factor="1.6875",
    note="",
)

MOCK_PRICE_ONCHAIN = PriceResponse(
    asset="ETH",
    price_usd="3000.00",
    token_address=WETH_ADDR,
    timestamp="2025-01-01T00:00:00Z",
    source="on-chain",
)

MOCK_PRICE_HIST = PriceResponse(
    asset="ETH",
    price_usd="2800.00",
    token_address=WETH_ADDR,
    timestamp="2024-06-01T00:00:00Z",
    source="defillama",
)

MOCK_HIST_POSITION = HistoricalPositionResponse(
    address=ADDR,
    at_time="2025-01-01T00:00:00Z",
    eth_collateral_amount="1.500000",
    eth_price_usd="3200.00",
    eth_collateral_usd="4800.00",
    total_debt_approx_usd="2000.00",
    liq_price="1666.67",
    reserves=[
        HistoricalReserveDetail(
            symbol="WETH",
            token_address=WETH_ADDR,
            supply_amount="1.500000",
            debt_amount="0.000000",
        )
    ],
    note="",
)

MOCK_POSITIONS_LIST = [MOCK_POSITION]
MOCK_HIST_POSITIONS_LIST = [MOCK_HIST_POSITION]

MOCK_PRICE_PERIOD = PricePeriodResponse(
    asset="ETH",
    token_address=WETH_ADDR,
    source="defillama",
    prices=[
        PricePeriodItem(price_usd="2800.00", timestamp="2024-06-01T00:00:00Z"),
        PricePeriodItem(price_usd="2900.00", timestamp="2024-06-02T00:00:00Z"),
        PricePeriodItem(price_usd="3000.00", timestamp="2024-06-03T00:00:00Z"),
    ],
)

MOCK_SIM_RESPONSE = LiquidationSimResponse(
    simulated_eth_price="1500.00",
    positions=[
        LiquidationSimItem(
            address=ADDR,
            liq_price="1666.67",
            eth_collateral_amount="1.500000",
            eth_collateral_usd="2250.00",
            total_collateral_usd="4500.00",
            total_debt_usd="2000.00",
        )
    ],
    positions_cnt="1",
    total_eth_collateral_amount="1.500000",
    total_eth_collateral_usd="2250.00",
    total_liquidation_usd="2100.00",
    note="共 1 个仓位",
)

MOCK_SIM_EMPTY = LiquidationSimResponse(
    simulated_eth_price="100.00",
    positions=[],
    positions_cnt="0",
    total_eth_collateral_amount="0.000000",
    total_eth_collateral_usd="0.00",
    total_liquidation_usd="0.00",
    note="共 0 个仓位",
)

MOCK_LIQ_PERIOD = [
    LiquidationPeriodItem(
        simulated_eth_price="1000.00",
        positions_cnt="5",
        total_eth_collateral_amount="7.500000",
        total_eth_collateral_usd="7500.00",
        total_liquidation_usd="7875.00",
    ),
    LiquidationPeriodItem(
        simulated_eth_price="1500.00",
        positions_cnt="3",
        total_eth_collateral_amount="4.500000",
        total_eth_collateral_usd="6750.00",
        total_liquidation_usd="6300.00",
    ),
    LiquidationPeriodItem(
        simulated_eth_price="2000.00",
        positions_cnt="1",
        total_eth_collateral_amount="1.500000",
        total_eth_collateral_usd="3000.00",
        total_liquidation_usd="2100.00",
    ),
]

MOCK_WATERFALL_RESPONSE = LiquidationWaterfallResponse(
    total_liquidation_usd="1050.00",
    total_eth_sold_amount="0.350000",
    total_eth_sold_value="840.00",
    initial_decline="0.05000000",
    cascade_decline="0.00000000",
    total_decline="0.05000000",
    total_liquidation_accounts="1",
    max_hf="1.0200",
    liquidation_turns_cnt="1",
    liquidation_turns=[
        LiquidationWaterfallTurnItem(
            eth_sold_amount="0.350000",
            eth_sold_value="840.00",
            liquidation_accounts="1",
            liquidation_volume_usd="1050.00",
            eth_price="2400.0000",
            eth_price_decline="0.05000000",
        )
    ],
    note="第二阶段：已启用级联迭代",
)

MOCK_BORROW_POSITION = BorrowPositionResponse(
    address=ADDR,
    weth_debt_amount="10.000000",
    weth_debt_usd="18740.00",
    total_collateral_usd="25000.00",
    total_debt_usd="18740.00",
    health_factor="1.1200",
    liq_price_rise="2600.00",
)

MOCK_BORROW_POSITIONS_LIST = [MOCK_BORROW_POSITION]

MOCK_SHORT_SIM_RESPONSE = ShortLiqSimResponse(
    simulated_eth_price="2700.00",
    positions=[
        ShortLiqSimItem(
            address=ADDR,
            liq_price_rise="2600.00",
            weth_debt_amount="10.000000",
            weth_debt_usd="27000.00",
            total_collateral_usd="25000.00",
        )
    ],
    positions_cnt="1",
    total_weth_debt_amount="10.000000",
    total_weth_debt_usd="27000.00",
    total_liquidation_usd="25000.00",
    note="共 1 个仓位",
)

MOCK_SHORT_SIM_EMPTY = ShortLiqSimResponse(
    simulated_eth_price="1000.00",
    positions=[],
    positions_cnt="0",
    total_weth_debt_amount="0.000000",
    total_weth_debt_usd="0.00",
    total_liquidation_usd="0.00",
    note="共 0 个仓位",
)

MOCK_SHORT_LIQ_PERIOD = [
    ShortLiqPeriodItem(
        simulated_eth_price="2200.00",
        positions_cnt="2",
        total_weth_debt_amount="15.000000",
        total_weth_debt_usd="33000.00",
        total_liquidation_usd="30000.00",
    ),
    ShortLiqPeriodItem(
        simulated_eth_price="2500.00",
        positions_cnt="5",
        total_weth_debt_amount="40.000000",
        total_weth_debt_usd="100000.00",
        total_liquidation_usd="90000.00",
    ),
    ShortLiqPeriodItem(
        simulated_eth_price="3000.00",
        positions_cnt="8",
        total_weth_debt_amount="65.000000",
        total_weth_debt_usd="195000.00",
        total_liquidation_usd="170000.00",
    ),
]

MOCK_BORROW_USER_POSITION = BorrowUserPositionResponse(
    address=ADDR,
    scanned_at="2026-02-28T08:00:00Z",
    weth_debt_amount="10.000000",
    weth_debt_usd="18740.00",
    health_factor="1.1200",
    liq_price_rise="2600.00",
    reserves=[
        ReservePositionSchema(
            symbol="WETH",
            token_address=WETH_ADDR,
            price_usd="1874.00",
            supply_amount="0.000000",
            supply_usd="0.00",
            stable_debt_amount="0.000000",
            variable_debt_amount="10.000000",
            total_debt_amount="10.000000",
            total_debt_usd="18740.00",
            use_as_collateral=False,
        ),
        ReservePositionSchema(
            symbol="USDC",
            token_address="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
            price_usd="1.00",
            supply_amount="25000.000000",
            supply_usd="25000.00",
            stable_debt_amount="0.000000",
            variable_debt_amount="0.000000",
            total_debt_amount="0.000000",
            total_debt_usd="0.00",
            use_as_collateral=True,
        ),
    ],
)

MOCK_REPLAY_RESPONSE = PositionReplayResponse(
    address=ADDR,
    protocol="v3",
    from_time="2025-01-01T00:00:00Z",
    to_time="2026-01-01T00:00:00Z",
    data_source="cache",
    total_points=1,
    total_tx_count=1,
    cache_hit_rate="1.00",
    points=[
        PositionSnapshotPoint(
            tx_hash="0x" + "aa" * 32,
            block_number=21_000_000,
            timestamp="2025-06-01T10:00:00Z",
            eth_price_usd="2500.00",
            total_collateral_usd="5000.00",
            total_debt_usd="2000.00",
            available_borrows_usd="1000.00",
            health_factor="1.8750",
            liq_threshold="0.8000",
            liq_price="1250.00",
            liq_price_rise="0.00",
            eth_collateral_amount="2.000000",
            eth_collateral_usd="5000.00",
            weth_debt_amount="0.000000",
            weth_debt_usd="0.00",
            brief="",
        )
    ],
)

MOCK_TX_HISTORY_RESPONSE = TxHistoryResponse(
    address=ADDR,
    protocol="v3",
    from_time="2025-01-01T00:00:00Z",
    to_time="2026-01-01T00:00:00Z",
    total=2,
    stats={"supply": 1, "borrow": 1},
    txs=[
        TxHistoryItem(
            tx_hash="0x" + "aa" * 32,
            block_number=21_000_000,
            timestamp="2025-06-01T10:00:00Z",
            operation_type="supply",
            token_symbol="WETH",
            cached=True,
            brief="",
        ),
        TxHistoryItem(
            tx_hash="0x" + "bb" * 32,
            block_number=21_100_000,
            timestamp="2025-07-01T12:00:00Z",
            operation_type="borrow",
            token_symbol="USDC",
            cached=False,
            brief="",
        ),
    ],
)

MOCK_POSITIONS_PERIOD = [
    PositionPeriodItem(
        snapshot_date="2025-01-01",
        liquidation_cnt="120",
        total_eth_collateral_amount="350.000000",
        total_eth_collateral_usd="1050000.00",
        total_weth_debt_amount="100.000000",
        total_weth_debt_usd="300000.00",
        eth_price="3000.00",
        sim_eth_price="3000.00",
    ),
    PositionPeriodItem(
        snapshot_date="2025-01-02",
        liquidation_cnt="125",
        total_eth_collateral_amount="360.000000",
        total_eth_collateral_usd="1080000.00",
        total_weth_debt_amount="105.000000",
        total_weth_debt_usd="315000.00",
        eth_price="3000.00",
        sim_eth_price="3000.00",
    ),
    PositionPeriodItem(
        snapshot_date="2025-01-03",
        liquidation_cnt="118",
        total_eth_collateral_amount="345.000000",
        total_eth_collateral_usd="931500.00",
        total_weth_debt_amount="98.000000",
        total_weth_debt_usd="264600.00",
        eth_price="3000.00",
        sim_eth_price="2700.00",
    ),
]
