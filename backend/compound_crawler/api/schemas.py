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
