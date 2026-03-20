"""Pydantic schemas for Compound API."""

from __future__ import annotations

from pydantic import BaseModel


class PositionResponse(BaseModel):
    address: str
    total_collateral_usd: str
    total_debt_usd: str
    health_factor: str


class HealthResponse(BaseModel):
    status: str


class MarketStateReserveResponse(BaseModel):
    reserve: str
    symbol: str | None
    decimals: int | None
    total_supply: str
    total_borrow: str
    utilization: str
    borrow_rate: str
    supply_rate: str
    supply_usd: str
    borrow_usd: str


class MarketStateResponse(BaseModel):
    version: str
    market: str
    timestamp: str
    total_supply: str
    total_borrow: str
    utilization: str
    borrow_rate: str
    supply_rate: str
    supply_usd: str
    borrow_usd: str
    reserves: list[MarketStateReserveResponse] | None = None


class MarketStatePeriodResponse(BaseModel):
    points: list[MarketStateResponse]
