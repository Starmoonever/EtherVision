"""Constants and ABIs for Compound market-state collection."""

from __future__ import annotations

# Compound V3 (Ethereum mainnet) Comet markets.
# These are used as defaults when config does not provide market lists.
COMPOUND_V3_MARKETS: list[str] = [
    "0xc3d688B66703497DAA19211EEdff47f25384cdc3",  # USDC Comet
    "0x3Afdc9BCA9213A35503b077a6072F3D0d5AB0840",  # USDT Comet
    "0xA17581A9E3356d9A858b789D68B4d866e593aE94",  # WETH Comet
    "0x5D409e56D886231aDAf00c8775665AD0f9897b56",  # USDS Comet
    "0x3D0bb1ccaB520A66e607822fC55BC921738fAFE3",  # wstETH Cometm
]

COMPOUND_V3_MARKET_NAMES: dict[str, str] = {
    "0xc3d688b66703497daa19211eedff47f25384cdc3": "USDC",
    "0x3afdc9bca9213a35503b077a6072f3d0d5ab0840": "USDT",
    "0xa17581a9e3356d9a858b789d68b4d866e593ae94": "WETH",
    "0x5d409e56d886231adaf00c8775665ad0f9897b56": "USDS",
    "0x3d0bb1ccab520a66e607822fc55bc921738fafe3": "wstETH",
}

# Compound V2 (Ethereum mainnet) cToken markets.
# These are used as defaults when config does not provide market lists.
COMPOUND_V2_MARKETS: list[str] = [
    "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",  # cDAI
    "0x39AA39c021dfbaE8faC545936693aC917d5E7563",  # cUSDC
    "0xf650c3d88d12db855b8bf7d11be2e55a4e07dcc9",  # cUSDT
    "0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5",  # cETH
    "0xccF4429DB6322D5C611ee964527D42E5d685DD6a",  # cWBTC
]

COMPOUND_V2_MARKET_NAMES: dict[str, str] = {
    "0x5d3a536e4d6dbd6114cc1ead35777bab948e3643": "cDAI",
    "0x39aa39c021dfbae8fac545936693ac917d5e7563": "cUSDC",
    "0xf650c3d88d12db855b8bf7d11be2e55a4e07dcc9": "cUSDT",
    "0x4ddc2d193948926d02f9b1fe9e1daa0718270ed5": "cETH",
    "0xccf4429db6322d5c611ee964527d42e5d685dd6a": "cWBTC",
}

CTOKEN_V2_ABI = [
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "underlying",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "comptroller",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalBorrows",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalReserves",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getCash",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "exchangeRateStored",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "borrowRatePerBlock",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "supplyRatePerBlock",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "reserveFactorMantissa",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

COMPTROLLER_V2_ABI = [
    {
        "inputs": [],
        "name": "oracle",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]

COMPOUND_V2_ORACLE_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "cToken", "type": "address"}],
        "name": "getUnderlyingPrice",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]

COMET_ABI = [
    {
        "inputs": [],
        "name": "baseScale",
        "outputs": [{"internalType": "uint64", "name": "", "type": "uint64"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "baseToken",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "borrowBalanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "baseTokenPriceFeed",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "governor",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "pauseGuardian",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "extensionDelegate",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "supplyKink",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "supplyPerSecondInterestRateSlopeLow",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "supplyPerSecondInterestRateSlopeHigh",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "supplyPerSecondInterestRateBase",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "borrowKink",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "borrowPerSecondInterestRateSlopeLow",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "borrowPerSecondInterestRateSlopeHigh",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "borrowPerSecondInterestRateBase",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "storeFrontPriceFactor",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "trackingIndexScale",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "baseTrackingSupplySpeed",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "baseTrackingBorrowSpeed",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "baseMinForRewards",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "baseBorrowMin",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "targetReserves",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalBorrow",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getUtilization",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "utilization", "type": "uint256"}
        ],
        "name": "getSupplyRate",
        "outputs": [{"internalType": "uint64", "name": "", "type": "uint64"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "utilization", "type": "uint256"}
        ],
        "name": "getBorrowRate",
        "outputs": [{"internalType": "uint64", "name": "", "type": "uint64"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "numAssets",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint8", "name": "i", "type": "uint8"}],
        "name": "getAssetInfo",
        "outputs": [
            {
                "components": [
                    {"internalType": "uint8", "name": "offset", "type": "uint8"},
                    {"internalType": "address", "name": "asset", "type": "address"},
                    {"internalType": "address", "name": "priceFeed", "type": "address"},
                    {"internalType": "uint64", "name": "scale", "type": "uint64"},
                    {
                        "internalType": "uint64",
                        "name": "borrowCollateralFactor",
                        "type": "uint64",
                    },
                    {
                        "internalType": "uint64",
                        "name": "liquidateCollateralFactor",
                        "type": "uint64",
                    },
                    {
                        "internalType": "uint64",
                        "name": "liquidationFactor",
                        "type": "uint64",
                    },
                    {"internalType": "uint128", "name": "supplyCap", "type": "uint128"},
                ],
                "internalType": "struct CometCore.AssetInfo",
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "priceFeed", "type": "address"}],
        "name": "getPrice",
        "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "account", "type": "address"},
            {"internalType": "address", "name": "asset", "type": "address"},
        ],
        "name": "userCollateral",
        "outputs": [
            {"internalType": "uint128", "name": "balance", "type": "uint128"},
            {"internalType": "uint128", "name": "_reserved", "type": "uint128"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "asset", "type": "address"}],
        "name": "totalsCollateral",
        "outputs": [
            {
                "components": [
                    {
                        "internalType": "uint128",
                        "name": "totalSupplyAsset",
                        "type": "uint128",
                    },
                    {"internalType": "uint128", "name": "_reserved", "type": "uint128"},
                ],
                "internalType": "struct CometStorage.TotalsCollateral",
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalsBasic",
        "outputs": [
            {
                "components": [
                    {
                        "internalType": "uint64",
                        "name": "baseSupplyIndex",
                        "type": "uint64",
                    },
                    {
                        "internalType": "uint64",
                        "name": "baseBorrowIndex",
                        "type": "uint64",
                    },
                    {
                        "internalType": "uint64",
                        "name": "trackingSupplyIndex",
                        "type": "uint64",
                    },
                    {
                        "internalType": "uint64",
                        "name": "trackingBorrowIndex",
                        "type": "uint64",
                    },
                    {
                        "internalType": "uint104",
                        "name": "totalSupplyBase",
                        "type": "uint104",
                    },
                    {
                        "internalType": "uint104",
                        "name": "totalBorrowBase",
                        "type": "uint104",
                    },
                    {
                        "internalType": "uint40",
                        "name": "lastAccrualTime",
                        "type": "uint40",
                    },
                    {"internalType": "uint8", "name": "pauseFlags", "type": "uint8"},
                ],
                "internalType": "struct CometStorage.TotalsBasic",
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

CHAINLINK_AGGREGATOR_V3_ABI = [
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"internalType": "uint80", "name": "roundId", "type": "uint80"},
            {"internalType": "int256", "name": "answer", "type": "int256"},
            {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
            {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
            {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


ERC20_METADATA_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
]


ERC20_SYMBOL_BYTES32_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "bytes32"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    }
]
