"""FastAPI routes for MakerDAO scaffold."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from ..database import AsyncpgPool
from . import service
from .schemas import (
    MakerDaoIlkDetailResponse,
    MakerDaoIlkListResponse,
    MakerDaoPositionsResponse,
    MakerDaoScaffoldStatusResponse,
    MakerDaoSystemUrnPositionsResponse,
    MakerDaoVaultPositionResponse,
)

router = APIRouter(prefix="/api/makerdao")


def _require_ilk_or_address(
    *,
    ilk: str | None,
    address: str | None,
) -> tuple[str | None, str | None]:
    normalized_ilk = ilk.strip() if ilk is not None else None
    normalized_address = address.strip() if address is not None else None
    if not normalized_ilk:
        normalized_ilk = None
    if not normalized_address:
        normalized_address = None
    if (normalized_ilk is None) == (normalized_address is None):
        raise HTTPException(
            status_code=400,
            detail="ilk 和 address 必须且只能提供其中一个",
        )
    return normalized_ilk, normalized_address


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
    ilk: str | None = Query(None, description="MakerDAO ilk 名称，例如 ETH-A"),
    address: str | None = Query(None, description="抵押品代币地址，例如 0x..."),
) -> MakerDaoIlkDetailResponse:
    ilk, address = _require_ilk_or_address(ilk=ilk, address=address)
    return await service.get_ilk_detail(
        pool,
        ilk=ilk,
        address=address,
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
    "/positions",
    response_model=MakerDaoPositionsResponse,
    summary="Query current MakerDAO positions overview",
)
async def positions(
    pool: AsyncpgPool,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=200, description="分页大小，最大 200"),
    sort_by: Literal[
        "health_factor",
        "collateral_value_usd",
        "debt_value_usd",
        "liquidation_price_usd",
        "snapshot_at",
        "ilk",
    ] = Query("health_factor", description="排序字段"),
    order: Literal["asc", "desc"] = Query("asc", description="排序方向"),
    position_scope: Literal["all", "user", "system"] = Query(
        "all",
        description="仓位范围：all、user 或 system",
    ),
    ilk: str | None = Query(None, description="MakerDAO ilk 过滤条件"),
    is_healthy: bool | None = Query(None, description="按健康状态过滤"),
    include_empty: bool = Query(False, description="是否返回空仓位"),
) -> MakerDaoPositionsResponse:
    return await service.get_positions(
        pool,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        order=order,
        position_scope=position_scope,
        ilk=ilk,
        is_healthy=is_healthy,
        include_empty=include_empty,
    )


@router.get(
    "/system/position",
    response_model=MakerDaoSystemUrnPositionsResponse,
    summary="Query MakerDAO system urn positions by urn",
)
async def system_position(
    request: Request,
    pool: AsyncpgPool,
    urn: str = Query(..., description="MakerDAO 系统 urn 地址"),
) -> MakerDaoSystemUrnPositionsResponse:
    return await service.get_system_urn_positions(
        pool,
        urn=urn,
        w3=getattr(request.app.state, "w3", None),
    )
