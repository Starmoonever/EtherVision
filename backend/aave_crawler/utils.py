"""
通用工具函数（纯计算，无 IO / 异步依赖）。
"""

from __future__ import annotations

from decimal import Decimal


def raw_to_decimal(raw: int, decimals: int) -> Decimal:
    """链上原始整数 → Decimal，用于 NUMERIC 列。

    等价于 Decimal(raw) / 10**decimals，集中定义避免各模块重复实现。
    """
    return Decimal(raw) / Decimal(10 ** decimals)
