"""Protocol-agnostic API constants."""

from __future__ import annotations

from typing import Final

SUPPORTED_PRICE_ASSETS: tuple[tuple[str, str, str], ...] = (
    ("ETH", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "ethereum"),
    ("WETH", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "ethereum"),
    ("WBTC", "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", "ethereum"),
    ("cbBTC", "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", "ethereum"),
    ("tBTC", "0x18084fbA666a33d37592fA2633fD49a74DD93a88", "ethereum"),
    ("eBTC", "0x657e8C867D8b37dcc18fEE6fDbcE5A28000d3069", "ethereum"),
    ("LBTC", "0x8236a87084f8B84306f72007F36F2618A5634494", "ethereum"),
    ("USDC", "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "ethereum"),
    ("USDT", "0xdAC17F958D2ee523a2206206994597C13D831ec7", "ethereum"),
    ("DAI", "0x6B175474E89094C44Da98b954EedeAC495271d0F", "ethereum"),
    ("USDS", "0xdC035D45d973E3EC169d2276DDab16f1e407384F", "ethereum"),
    ("GHO", "0x40D16FC0246aD09AaD9Ba06aDcD28A7e825cA331", "ethereum"),
    ("PYUSD", "0x6c3ea9036406852006290770BEdFcAbA0e23A0e8", "ethereum"),
    ("USDe", "0x4c9EDD5852cd905f086C759E8383e09bff1E68B3", "ethereum"),
    ("sUSDe", "0x9D39A5DE30e57443Bff2A8307A4256C8797A3497", "ethereum"),
    ("stETH", "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84", "ethereum"),
    ("wstETH", "0x7f39C581F595B53c5cb5bA2D5dA6c935E2Ca0Ae6", "ethereum"),
    ("cbETH", "0xBe9895146f7AF43049ca1c1AE358B0541Ea49704", "ethereum"),
    ("rETH", "0xae78736Cd615f374D3085123A210448E74Fc6393", "ethereum"),
    ("eETH", "0x35fA164735182de50811E8e2E824cFb9B6118ac2", "ethereum"),
    ("weETH", "0xCd5fE23C85820F7B72D0926FC9B05b43E359b7ee", "ethereum"),
    ("swETH", "0xf951E335afb289353dc249e82926178EaC7DEd78", "ethereum"),
    ("ezETH", "0xbf5495Efe5DB9ce00f80364C8B423567e58d2110", "ethereum"),
    ("mETH", "0xd5F7838F5c461FeFf7Fe49EA5EbAF7728Bb0ADfa", "ethereum"),
    ("osETH", "0xf1C9acDc66974dDfB6dEc12AA385b9cd01190E38", "ethereum"),
    ("TRX", "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb", "tron"),
    ("USDD", "TXDk8mbtRbXeYuMNS83CfKPaYYT8XWv9Hz", "tron"),
    ("USDT", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "tron"),
    ("SUN", "TSSMHYeV2uE9qYH95DqyoCuNCzEL1NvU3S", "tron"),
    ("BTT", "TAFjULxiVgT4qWk6UZwjqwZXTSaGaqnVp4", "tron"),
    ("NFT", "TFczxzPhnThNSqr5by8tvxsdCFRRz6cPNq", "tron"),
    ("JST", "TCFLL5dx5ZJdKnWuesXxi1VPwjLVmWZZy9", "tron"),
    ("WIN", "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7", "tron"),
    ("USDJ", "TMwFHYXLJaRUPeW6421aqXL4ZEzPRFGkGT", "tron"),
    ("USDC", "TLZSucJRjnqBKwvQz6n5hd29gbS4P7u7w8", "tron"),
    ("TUSD", "TUpMhErZL2fhh4sVNULAbNKLokS4GjC1F4", "tron"),
    ("BTC", "TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9", "tron"),
    ("ETH", "THb4CqiFdwNHsWsQCs4JhzwjMWys4aqCbF", "tron"),
    ("sTRX", "TU3kjFuhtEo42tsCBtfYUAZxoqQ4yuSLQ5", "tron"),
)

PRICE_ASSET_ALIASES: Final[dict[str, str]] = {
    "ETH": "ETH",
    "WETH": "WETH",
    "STETH": "stETH",
    "WSTETH": "wstETH",
    "CBETH": "cbETH",
    "RETH": "rETH",
    "EETH": "eETH",
    "WEETH": "weETH",
    "SWETH": "swETH",
    "EZETH": "ezETH",
    "METH": "mETH",
    "OSETH": "osETH",
    "TBTC": "tBTC",
    "EBTC": "eBTC",
    "LBTC": "LBTC",
    "USDE": "USDe",
    "SUSDE": "sUSDe",
    "PYUSD": "PYUSD",
    "USDS": "USDS",
    "GHO": "GHO",
}

ETHEREUM_PRICE_ASSETS: Final[dict[str, tuple[str, str, str]]] = {
    asset.upper(): (asset, token_address, chain)
    for asset, token_address, chain in SUPPORTED_PRICE_ASSETS
    if chain == "ethereum"
}

ETHEREUM_PRICE_ASSET_BY_ADDRESS: Final[dict[str, tuple[str, str, str]]] = {
    token_address.lower(): (asset, token_address, chain)
    for asset, token_address, chain in SUPPORTED_PRICE_ASSETS
    if chain == "ethereum"
}
