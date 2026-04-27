"""FastAPI routes for MakerDAO scaffold."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..database import AsyncpgPool
from . import service
from .schemas import (
    MakerDaoIlkDetailResponse,
    MakerDaoIlkListResponse,
    MakerDaoScaffoldStatusResponse,
    MakerDaoSystemUrnPositionResponse,
    MakerDaoVaultPositionResponse,
)

router = APIRouter(prefix="/api/makerdao")


@router.get(
    "/status",
    response_model=MakerDaoScaffoldStatusResponse,
    summary="Inspect MakerDAO scaffold status",
)
async def status() -> MakerDaoScaffoldStatusResponse:
    return service.get_scaffold_status()


@router.get(
    "/ilks",
    response_model=MakerDaoIlkListResponse,
    summary="List MakerDAO ilks from cache with live backfill",
)
async def ilks(request: Request, pool: AsyncpgPool) -> MakerDaoIlkListResponse:
    return await service.get_ilks(pool, w3=getattr(request.app.state, "w3", None))


@router.get(
    "/ilk",
    response_model=MakerDaoIlkDetailResponse,
    summary="Get MakerDAO ilk detail from cache with live backfill",
)
async def ilk(
    request: Request,
    pool: AsyncpgPool,
    ilk: str = Query(..., description="MakerDAO ilk 名称，例如 ETH-A"),
) -> MakerDaoIlkDetailResponse:
    return await service.get_ilk_detail(
        pool,
        ilk=ilk,
        w3=getattr(request.app.state, "w3", None),
    )


@router.get(
    "/position",
    response_model=MakerDaoVaultPositionResponse,
    summary="Query live MakerDAO vault positions by address",
)
async def position(
    request: Request,
    pool: AsyncpgPool,
    address: str = Query(..., description="MakerDAO owner / proxy / urn address"),
    vault_id: int | None = Query(None, description="可选过滤：vault 编号"),
    ilk: str | None = Query(None, description="可选过滤：MakerDAO ilk"),
    include_empty: bool = Query(False, description="是否返回空仓位"),
) -> MakerDaoVaultPositionResponse:
    return await service.get_user_vault_position(
        pool,
        address=address,
        w3=getattr(request.app.state, "w3", None),
        vault_id=vault_id,
        ilk=ilk,
        include_empty=include_empty,
    )


@router.get(
    "/system/position",
    response_model=MakerDaoSystemUrnPositionResponse,
    summary="Query MakerDAO system urn position by urn",
)
async def system_position(
    request: Request,
    pool: AsyncpgPool,
    urn: str = Query(..., description="MakerDAO 系统 urn 地址"),
    ilk: str | None = Query(
        None, description="可选 MakerDAO 系统 ilk，例如 ALLOCATOR-SPARK-A"
    ),
) -> MakerDaoSystemUrnPositionResponse:
    return await service.get_system_urn_position(
        pool,
        urn=urn,
        ilk=ilk,
        w3=getattr(request.app.state, "w3", None),
    )
