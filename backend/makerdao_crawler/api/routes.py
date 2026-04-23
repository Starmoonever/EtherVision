"""FastAPI routes for MakerDAO scaffold."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..database import AsyncpgPool
from .schemas import (
    MakerDaoIlkListResponse,
    MakerDaoScaffoldStatusResponse,
    MakerDaoVaultPositionResponse,
)
from .service import get_ilks, get_scaffold_status, get_user_vault_position

router = APIRouter(prefix="/api/makerdao")


@router.get(
    "/status",
    response_model=MakerDaoScaffoldStatusResponse,
    summary="Inspect MakerDAO scaffold status",
)
async def status() -> MakerDaoScaffoldStatusResponse:
    return get_scaffold_status()


@router.get(
    "/ilks",
    response_model=MakerDaoIlkListResponse,
    summary="List MakerDAO ilks from cache",
)
async def ilks(pool: AsyncpgPool) -> MakerDaoIlkListResponse:
    return await get_ilks(pool)


@router.get(
    "/position",
    response_model=MakerDaoVaultPositionResponse,
    summary="Query cached MakerDAO vault positions by address",
)
async def position(
    pool: AsyncpgPool,
    address: str = Query(..., description="MakerDAO owner / proxy / urn address"),
    vault_id: int | None = Query(None, description="可选过滤：vault 编号"),
    ilk: str | None = Query(None, description="可选过滤：MakerDAO ilk"),
) -> MakerDaoVaultPositionResponse:
    return await get_user_vault_position(
        pool,
        address=address,
        vault_id=vault_id,
        ilk=ilk,
    )
