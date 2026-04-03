"""Domain models for the JustLend scaffold."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class AssetPosition:
    asset_address: str
    symbol: str
    side: str
    amount: Decimal = Decimal("0")
    price_usd: Decimal = Decimal("0")
    value_usd: Decimal = Decimal("0")


@dataclass
class UserPosition:
    protocol: str
    chain: str
    user_address: str
    total_collateral_usd: Decimal = Decimal("0")
    total_debt_usd: Decimal = Decimal("0")
    health_factor: Decimal = Decimal("0")
    assets: list[AssetPosition] = field(default_factory=list)
