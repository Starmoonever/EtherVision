"""FastAPI routes for Morpho."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..database import AsyncpgPool
from .schemas import (
    MorphoMarketStateResponse,  # api/morpho/market/state相关
    MorphoMarketListResponse,  # api/morpho/markets相关
    MorphoPositionReplayResponse,
    MorphoPositionResponse,
)
from .schemas import MorphoVaultStateGraphQLResponse  # api/morpho/vault/v1/state相关
from .schemas import MorphoVotesResponse  # api/morpho/vaults相关
from .service import (
    get_market_state,  # api/morpho/market/state相关
    get_position_replay,
    get_representative_markets_page,  # api/morpho/markets相关
    get_user_position,
)
from .service import get_vault_state_main_graphql  # api/morpho/vault/v1/state相关
from .service import get_vault_v2_state_main_graphql  # api/morpho/vault/v2/state相关
from .service import get_votes_page  # api/morpho/vaults相关

router = APIRouter(prefix="/api/morpho")


def _w3(request: Request):
    w3 = getattr(request.app.state, "w3", None)
    if w3 is None:
        raise HTTPException(status_code=503, detail="RPC 节点尚未就绪，请稍后重试")
    return w3


@router.get(
    "/position",
    response_model=MorphoPositionResponse,
    summary="Query current Morpho Blue position from RPC",
)
async def position(
    request: Request,
    pool: AsyncpgPool,
    address: str = Query(..., description="EVM user address"),
    market_id: str = Query(..., description="Morpho market id (bytes32 hex)"),
    protocol: str = Query(
        "blue", description='Morpho protocol selector; currently only "blue"'
    ),
) -> MorphoPositionResponse:
    return await get_user_position(
        _w3(request),
        pool=pool,
        address=address,
        market_id=market_id,
        protocol=protocol,
    )


@router.get(
    "/position/replay",
    response_model=MorphoPositionReplayResponse,
    summary="Replay Morpho Blue user position by cached snapshots",
)
async def position_replay(
    request: Request,
    pool: AsyncpgPool,
    address: str = Query(..., description="EVM user address"),
    market_id: str = Query(..., description="Morpho market id (bytes32 hex)"),
    start: str = Query(..., description="起始时间（UTC）"),
    end: str = Query(..., description="结束时间（UTC）"),
    protocol: str = Query(
        "blue", description='Morpho protocol selector; currently only "blue"'
    ),
    use_cache: bool = Query(True, description="是否优先使用缓存"),
    detail: bool = Query(False, description="是否返回资产明细"),
) -> MorphoPositionReplayResponse:
    from .service import parse_utc_time

    from_ts = parse_utc_time(start)
    to_ts = parse_utc_time(end)
    if from_ts > to_ts:
        raise HTTPException(status_code=400, detail="start 必须早于或等于 end")

    return await get_position_replay(
        _w3(request),
        pool=pool,
        address=address,
        market_id=market_id,
        protocol=protocol,
        from_ts=from_ts,
        to_ts=to_ts,
        use_cache=use_cache,
        detail=detail,
    )


# api/morpho/markets相关：GET /api/morpho/markets（分页，可自定义每页条数）
@router.get(
    "/markets",
    response_model=MorphoMarketListResponse,
    summary="List hardcoded Morpho markets with TVL page",
)
async def market_list(
    pool: AsyncpgPool,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(
        10,
        ge=1,
        le=100,
        description="每页市场数量，默认 10",
    ),
    sort_by: str = Query(
        "total_market_size_usd",
        description="排序字段：total_market_size_usd / utilization / loan_symbol / collateral_symbol",
    ),
    sort_order: str = Query(
        "desc",
        description="排序方向：asc 或 desc，默认 desc",
    ),
    loan: str | None = Query(
        None,
        description="可选过滤：借款侧（0x 开头按地址过滤，否则按币名过滤）",
    ),
    collateral: str | None = Query(
        None,
        description="可选过滤：抵押侧（0x 开头按地址过滤，否则按币名过滤）",
    ),
) -> MorphoMarketListResponse:
    # api/morpho/markets相关：支持分页、排序与 loan/collateral 地址/币名过滤
    return await get_representative_markets_page(
        pool=pool,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        loan=loan,
        collateral=collateral,
    )


# api/morpho/market/state相关：GET /api/morpho/market/state
@router.get(
    "/market/state",
    response_model=MorphoMarketStateResponse,
    summary="Get Morpho market state",
)
async def market_state(
    request: Request,
    pool: AsyncpgPool,
    market_id: str = Query(..., description="Morpho market id (bytes32 hex)"),
    date: str | None = Query(
        None, description="预留历史参数；当前仅支持实时 latest 数据"
    ),
) -> MorphoMarketStateResponse:
    return await get_market_state(
        _w3(request),
        pool=pool,
        market_id=market_id,
        date=date,
    )


# api/morpho/vault/v1/state相关：GET /api/morpho/vault/v1/state（Morpho 主站 GraphQL vaultByAddress）
@router.get(
    "/vault/v1/state",
    response_model=MorphoVaultStateGraphQLResponse,
    summary="Morpho Vault V1 状态（主站 GraphQL）",
)
async def vault_state(
    request: Request,
    pool: AsyncpgPool,
    address: str = Query(..., description="Vault 合约地址（EVM）"),
) -> MorphoVaultStateGraphQLResponse:
    # api/morpho/vault/v1/state相关：固定主网查询，不暴露 chain_id
    return await get_vault_state_main_graphql(
        address=address,
        w3=_w3(request),
        pool=pool,
    )


# api/morpho/vault/v2/state相关：GET /api/morpho/vault/v2/state（Morpho 主站 GraphQL vaultV2ByAddress）
@router.get(
    "/vault/v2/state",
    response_model=MorphoVaultStateGraphQLResponse,
    summary="Morpho Vault V2 状态（主站 GraphQL）",
)
async def vault_v2_state(
    pool: AsyncpgPool,
    address: str = Query(..., description="Vault V2 合约地址（EVM）"),
) -> MorphoVaultStateGraphQLResponse:
    # api/morpho/vault/v2/state相关：固定主网查询，不暴露 chain_id
    return await get_vault_v2_state_main_graphql(address=address, pool=pool)


# api/morpho/vaults相关：GET /api/morpho/vaults（v1/v2 金库总表概览，分页）
@router.get(
    "/vaults",
    response_model=MorphoVotesResponse,
    summary="List Morpho vault overview from v1/v2 tables",
)
async def votes(
    pool: AsyncpgPool,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页条数，默认 10"),
    sort_by: str = Query(
        "total_assets_usd",
        description="可选排序字段：total_assets_usd / liquidity / apy",
    ),
    sort_order: str = Query(
        "desc",
        description="可选排序方向：asc / desc，默认 desc",
    ),
    asset: str | None = Query(None, description="可选：货币筛选（0x地址或币名映射）"),
    asset_address: str | None = Query(
        None, description="可选：按资产地址过滤（EVM 地址）"
    ),
    protocol: str | None = Query(None, description="可选：按协议过滤（v1 或 v2）"),
) -> MorphoVotesResponse:
    return await get_votes_page(
        pool=pool,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        asset=asset,
        asset_address=asset_address,
        protocol=protocol,
    )
