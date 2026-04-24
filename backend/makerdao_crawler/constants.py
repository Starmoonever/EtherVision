"""Shared constants for the MakerDAO scaffold."""

MAKERDAO_CHAIN = "ethereum"
MAKERDAO_PROTOCOL = "makerdao"
MAKERDAO_DEFAULT_VAULT_TYPE = "vault"

WAD = 10**18
RAY = 10**27
RAD = 10**45

MAKERDAO_CHAINLOG_ADDRESS = "0xdA0Ab1e0017DEbCd72Be8599041a2aa3bA7e740F"
MAKERDAO_DAI_ADDRESS = "0x6B175474E89094C44Da98b954EedeAC495271d0F"

MAKERDAO_DEFAULT_CONTRACTS = {
    "vat": "0x35D1b3F3D7966A1DFe207aa4514C12a259A0492B",
    "spotter": "0x65C79fcB50Ca1594B025960e539eD7A9a6D434A3",
    "dog": "0x135954d155898D42C90D2a57824C690e0c7BEf1B",
    "cdp_manager": "0x5ef30b9986345249bc32d8928B7ee64DE9435E39",
    "get_cdps": "0x36a724Bd100c39f0Ea4D3A20F7097eE01A8Ff573",
    "proxy_registry": "0x4678f0a6958e4D2Bc4F1BAF7Bc52E8F3564f3fE4",
    "ilk_registry": "0x5a464C28D19848f44199D003BeF5ecc87d090F87",
}

MAKERDAO_DEFAULT_ILK_NAMES = [
    "ETH-A",
    "ETH-B",
    "ETH-C",
    "WBTC-A",
    "WBTC-B",
    "WBTC-C",
    "WSTETH-A",
    "WSTETH-B",
    "RETH-A",
    "CBETH-A",
    "LINK-A",
    "UNI-A",
    "AAVE-A",
]

MAKERDAO_DEFAULT_ILK_METADATA = {
    "ETH-A": {
        "symbol": "WETH",
        "token_address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    },
    "ETH-B": {
        "symbol": "WETH",
        "token_address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    },
    "ETH-C": {
        "symbol": "WETH",
        "token_address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    },
    "WBTC-A": {
        "symbol": "WBTC",
        "token_address": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    },
    "WBTC-B": {
        "symbol": "WBTC",
        "token_address": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    },
    "WBTC-C": {
        "symbol": "WBTC",
        "token_address": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    },
    "WSTETH-A": {
        "symbol": "wstETH",
        "token_address": "0x7f39C581F595B53c5cb5bA2D5dA6c935E2Ca0Ae6",
    },
    "WSTETH-B": {
        "symbol": "wstETH",
        "token_address": "0x7f39C581F595B53c5cb5bA2D5dA6c935E2Ca0Ae6",
    },
    "RETH-A": {
        "symbol": "rETH",
        "token_address": "0xae78736Cd615f374D3085123A210448E74Fc6393",
    },
    "CBETH-A": {
        "symbol": "cbETH",
        "token_address": "0xBe9895146f7AF43049ca1c1AE358B0541Ea49704",
    },
    "LINK-A": {
        "symbol": "LINK",
        "token_address": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
    },
    "UNI-A": {
        "symbol": "UNI",
        "token_address": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
    },
    "AAVE-A": {
        "symbol": "AAVE",
        "token_address": "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
    },
}
