"""Business service layer for Compound API."""

from __future__ import annotations

from .schemas import PositionResponse


async def get_sorted_positions(limit: int) -> list[PositionResponse]:
    _ = limit
    return []
