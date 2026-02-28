"""API 层全局常量"""

from decimal import Decimal

# ── 清算模拟过滤条件 ──────────────────────────────────────────────────────────

# 仅当 eth_collateral_usd / total_collateral_usd >= ETH_COLLATERAL_RATIO_MIN 时，
# 该仓位才纳入清算模拟计算（抵押侧）。
# 目的：过滤掉以非 ETH 资产为主要抵押品的仓位，确保模拟结果聚焦于 ETH 主导的头寸。
ETH_COLLATERAL_RATIO_MIN = Decimal("0.45")

# 仅当 weth_debt_usd / total_debt_usd >= ETH_DEBT_RATIO_MIN 时，
# 该仓位才纳入借贷端清算模拟计算（借贷侧）。
# 目的：过滤掉以非 WETH 资产为主要债务的仓位，确保做空模拟聚焦于 WETH 主导的借贷头寸。
ETH_DEBT_RATIO_MIN = Decimal("0.45")
