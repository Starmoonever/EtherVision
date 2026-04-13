"""Domain models for the Morpho scaffold."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class PositionAsset:
    asset_address: str
    symbol: str
    side: str
    amount: Decimal = Decimal("0")
    price_usd: Decimal = Decimal("0")
    value_usd: Decimal = Decimal("0")


@dataclass
class UserPosition:
    protocol: str
    market_type: str
    chain: str
    market_id: str
    user_address: str
    collateral_usd: Decimal = Decimal("0")
    debt_usd: Decimal = Decimal("0")
    health_factor: Decimal = Decimal("0")
    assets: list[PositionAsset] = field(default_factory=list)
