"""API 层全局常量"""

from decimal import Decimal

# ── 清算模拟过滤条件 ──────────────────────────────────────────────────────────

# 仅当 eth_collateral_usd / total_collateral_usd >= ETH_COLLATERAL_RATIO_MIN 时，
# 该仓位才纳入清算模拟计算。
# 目的：过滤掉以非 ETH 资产为主要抵押品的仓位，确保模拟结果聚焦于 ETH 主导的头寸。
ETH_COLLATERAL_RATIO_MIN = Decimal("0.45")
