"""Constants and ABIs for Compound market-state collection."""

from __future__ import annotations

# Compound V3 (Ethereum mainnet) Comet markets.
# These are used as defaults when config does not provide market lists.
COMPOUND_V3_MARKETS: list[str] = [
    "0xc3d688B66703497DAA19211EEdff47f25384cdc3",  # USDC Comet
    "0x3Afdc9BCA9213A35503b077a6072F3D0d5AB0840",  # USDT Comet
    "0xA17581A9E3356d9A858b789D68B4d866e593aE94",  # WETH Comet
    "0x5D409e56D886231aDAf00c8775665AD0f9897b56",  # USDS Comet
    "0x3D0bb1ccaB520A66e607822fC55BC921738fAFE3",  # wstETH Comet
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
    "0x041171993284DF560249B57358F931D9EB7B925D",  # cUSDP
    "0x12392F67BDF24FAE0AF363C24AC620A2F67DAD86",  # cTUSD
    "0x158079EE67FCE2F58472A96584A73C7AB9AC95C1",  # cREP
    "0x35A18000230DA775CAC24873D00FF85BCCDED550",  # cUNI
    "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",  # cDAI
    "0x4B0181102A0112A2EF11ABEE5563BB4A3176C9D7",  # cSUSD
    "0x6C8C6B02E7B2BE14D4FA6022DFD6D75921D90E4E",  # cBAT
    "0x70E36F6BF80A52B3B46B3AF8E106CC0ED743E8E4",  # cCOMP
    "0x7713DD9CA933848F6819F38B8352D9A15EA73F67",  # cFEI
    "0x80A2AE356FC9EF4305676F7A3E2ED04E12C33946",  # cYFI
    "0x95B4EF2869EBD94BEB4EEE400A99824BF5DC325B",  # cMKR
    "0xB3319F5D18BC0D84DD1B4825DCDE5D5F7266D407",  # cZRX
    "0xC11B1268C1A384E55C48C2391D8D480264A3A7F4",  # cWBTCLegacy
    "0x39AA39c021dfbaE8faC545936693aC917d5E7563",  # cUSDC
    "0x4Ddc2D193948926D02f9B1fE9e1daa0718270ED5",  # cETH
    "0xccF4429DB6322D5C611ee964527D42E5d685DD6a",  # cWBTC
    "0xE65CDB6479BAC1E22340E4E755FAE7E509ECD06C",  # cAAVE
    "0xF5DCE57282A584D2746FAF1593D3121FCAC444DC",  # cSAI
    "0xf650c3d88d12db855b8bf7d11be6c55a4e07dcc9",  # cUSDT
    "0xFACE851A4921CE59E912D19329929CE6DA6EB0C7",  # cLINK
]

COMPOUND_V2_MARKET_NAMES: dict[str, str] = {
    "0x041171993284df560249b57358f931d9eb7b925d": "cUSDP",
    "0x12392f67bdf24fae0af363c24ac620a2f67dad86": "cTUSD",
    "0x158079ee67fce2f58472a96584a73c7ab9ac95c1": "cREP",
    "0x35a18000230da775cac24873d00ff85bccded550": "cUNI",
    "0x5d3a536e4d6dbd6114cc1ead35777bab948e3643": "cDAI",
    "0x4b0181102a0112a2ef11abee5563bb4a3176c9d7": "cSUSD",
    "0x6c8c6b02e7b2be14d4fa6022dfd6d75921d90e4e": "cBAT",
    "0x70e36f6bf80a52b3b46b3af8e106cc0ed743e8e4": "cCOMP",
    "0x7713dd9ca933848f6819f38b8352d9a15ea73f67": "cFEI",
    "0x80a2ae356fc9ef4305676f7a3e2ed04e12c33946": "cYFI",
    "0x95b4ef2869ebd94beb4eee400a99824bf5dc325b": "cMKR",
    "0xb3319f5d18bc0d84dd1b4825dcde5d5f7266d407": "cZRX",
    "0xc11b1268c1a384e55c48c2391d8d480264a3a7f4": "cWBTCLegacy",
    "0x39aa39c021dfbae8fac545936693ac917d5e7563": "cUSDC",
    "0x4ddc2d193948926d02f9b1fe9e1daa0718270ed5": "cETH",
    "0xccf4429db6322d5c611ee964527d42e5d685dd6a": "cWBTC",
    "0xe65cdb6479bac1e22340e4e755fae7e509ecd06c": "cAAVE",
    "0xf5dce57282a584d2746faf1593d3121fcac444dc": "cSAI",
    "0xf650c3d88d12db855b8bf7d11be6c55a4e07dcc9": "cUSDT",
    "0xface851a4921ce59e912d19329929ce6da6eb0c7": "cLINK",
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
    {
        "inputs": [],
        "name": "interestRateModel",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
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
    },
    {
        "inputs": [{"internalType": "address", "name": "cToken", "type": "address"}],
        "name": "markets",
        "outputs": [
            {"internalType": "bool", "name": "isListed", "type": "bool"},
            {
                "internalType": "uint256",
                "name": "collateralFactorMantissa",
                "type": "uint256",
            },
            {"internalType": "bool", "name": "isComped", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "closeFactorMantissa",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "liquidationIncentiveMantissa",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
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
        "name": "transferGuardianPaused",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "seizeGuardianPaused",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "cToken", "type": "address"}],
        "name": "mintGuardianPaused",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "cToken", "type": "address"}],
        "name": "borrowGuardianPaused",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "cToken", "type": "address"}],
        "name": "borrowCaps",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "cToken", "type": "address"}],
        "name": "supplyCaps",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "cToken", "type": "address"}],
        "name": "compSupplySpeeds",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "cToken", "type": "address"}],
        "name": "compBorrowSpeeds",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "cToken", "type": "address"}],
        "name": "compSpeeds",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "cToken", "type": "address"}],
        "name": "isDeprecated",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
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
