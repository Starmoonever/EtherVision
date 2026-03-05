"""
全局常量。

每当新增 ETH LST/LRT 时只需修改此文件中的 ETH_SYMBOLS / _ETH_DISPLAY，
不再需要同步修改 db.py、api/service.py 和各 scripts。
"""

from decimal import Decimal

# ── ETH 系资产 ────────────────────────────────────────────────────────────────

# 全大写，用于 Python .upper() 比较
ETH_SYMBOLS: frozenset[str] = frozenset(
    {
        "WETH",
        "ETH",
        "CBETH",
        "WSTETH",
        "RETH",
        "WEETH",
        "EZETH",
        "RSETH",
        "OSETH",
        "ETHX",
    }
)

# 链上原始大小写（用于 SQL IN 列表，与 ETH_SYMBOLS 元素一一对应）
_ETH_DISPLAY = (
    "WETH", "ETH", "cbETH", "wstETH", "rETH",
    "weETH", "ezETH", "rsETH", "osETH", "ETHx",
)

# WHERE symbol IN (...) 字符串，可直接插入 SQL f-string
ETH_SYMBOLS_SQL: str = ", ".join(f"'{s}'" for s in _ETH_DISPLAY)

# ── 数值常量 ──────────────────────────────────────────────────────────────────

# uint256 最大值；链上 health_factor = MAX_UINT256 表示无穷大（无债务）
MAX_UINT256: int = (1 << 256) - 1

# DB 中 health_factor 列的无穷大哨兵（NUMERIC(40,18)，18 位精度存储）
# 无穷大 HF 在 DB 中写入 1e18，读出后与此值比较
MAX_HF: Decimal = Decimal("1e18")

# ETH/USD 清算价上限（防止极端仓位溢出 NUMERIC(30,8)，约 1000 万 USD）
LIQ_PRICE_CAP: Decimal = Decimal("9999999.99999999")

# ── Aave Ethereum Mainnet 核心合约地址 ────────────────────────────────────────

# AavePools（checksum）
POOL_V3 = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
POOL_V2 = "0x7d2768dE32b0b80b7a3454c06BdAc94A69DDc7A9"

# WETH（小写，供 tx_parser 静态 token 表查找）
WETH_ADDR = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
