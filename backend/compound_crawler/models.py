"""Core dataclasses for Compound crawler."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UserPosition:
    address: str
    total_collateral_usd: float
    total_debt_usd: float
    health_factor: float
