"""Protocol-agnostic API constants."""

from __future__ import annotations

SUPPORTED_PRICE_ASSETS: tuple[tuple[str, str, str], ...] = (
    ("ETH", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "ethereum"),
    ("WETH", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "ethereum"),
    ("WBTC", "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", "ethereum"),
    ("USDC", "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "ethereum"),
    ("USDT", "0xdAC17F958D2ee523a2206206994597C13D831ec7", "ethereum"),
    ("DAI", "0x6B175474E89094C44Da98b954EedeAC495271d0F", "ethereum"),
    ("wstETH", "0x7f39C581F595B53c5cb5bA2D5dA6c935E2Ca0Ae6", "ethereum"),
    ("cbETH", "0xBe9895146f7AF43049ca1c1AE358B0541Ea49704", "ethereum"),
    ("rETH", "0xae78736Cd615f374D3085123A210448E74Fc6393", "ethereum"),
    ("weETH", "0xCd5fE23C85820F7B72D0926FC9B05b43E359b7ee", "ethereum"),
    ("ezETH", "0xbf5495Efe5DB9ce00f80364C8B423567e58d2110", "ethereum"),
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
