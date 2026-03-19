"""FastAPI routes for Compound scaffold."""

from __future__ import annotations

from fastapi import APIRouter, Query

from .constants import DEFAULT_LIMIT, MAX_LIMIT
from .schemas import PositionResponse
from .service import get_sorted_positions

router = APIRouter(prefix="/api/compound")


@router.get(
    "/positions",
    response_model=list[PositionResponse],
    summary="Query Compound positions (scaffold)",
)
async def positions(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Result size"),
) -> list[PositionResponse]:
    return await get_sorted_positions(limit)
