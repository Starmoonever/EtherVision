"""FastAPI routes for Compound scaffold."""

from __future__ import annotations
from typing import Literal
from fastapi import APIRouter, Query
from .schemas import (
    MarketsResponse,
    MarketGovernanceResponse,
    MarketGovernancePeriodResponse,
    MarketStatePeriodResponse,
    MarketStateResponse,
    UserPositionResponse,
)
from .service import (
    get_markets,
    get_market_governance,
    get_market_governance_period,
    get_market_state,
    get_market_state_period,
    get_positions,
)
from ..database import AsyncpgPool


router = APIRouter(prefix="/api/compound")


@router.get(
    "/markets",
    response_model=MarketsResponse,
    summary="List supported Compound markets",
)
async def markets(
    version: Literal["v2", "v3"] = Query(
        "v3",
        description='protocol version: "v2" | "v3" (currently only v3 is supported)',
    ),
) -> MarketsResponse:
    return get_markets(version)


@router.get(
    "/position",
    response_model=UserPositionResponse,
    summary="Query a single Compound user position",
    response_description=(
        "返回单一地址在指定市场或全部市场下的仓位列表；每个元素都包含市场标识、时间戳、清算缓冲、健康因子、ETH 敏感敞口以及逐资产明细。"
    ),
    description=(
        "查询 Compound v3 中单一用户地址的仓位快照。\n\n"
        "- `address` 为必选，只返回该地址的仓位\n"
        "- `market` 可传单个市场地址/名称，或传 `all` 返回所有已支持市场\n"
        "- `date` 推荐直接传 `YYYY-MM-DD`\n"
        "- 如果 `date` 同时包含具体时间，服务会忽略时分秒，只取该 UTC 日期并归一到 `00:00:00Z`\n"
        "- 若 `date` 为空，则直接从链上抓取实时数据，不写库\n"
        "- 若 `date` 不为空，则优先查库；若库中不存在，则链上查询后写入快照表再返回\n"
        "- 返回结果中的 `positions` 为该地址在命中市场下的仓位列表"
    ),
)
async def position(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query(
        "v3",
        description='protocol version: "v2" | "v3" (currently only v3 is supported)',
    ),
    market: str = Query(
        ...,
        description='市场地址或名称，也支持 `all`：`"0x..." | "<SYMBOL>" | "all"`',
    ),
    address: str = Query(
        ...,
        description="必选用户地址；该端点只返回这个地址的仓位。",
    ),
    date: str | None = Query(
        None,
        description=(
            "可选 UTC 日期，推荐格式 `YYYY-MM-DD`。若同时带有时分秒，将被忽略并自动归一到该日期的 `00:00:00Z`；"
            "不传则返回链上实时数据。"
        ),
    ),
) -> UserPositionResponse:
    return await get_positions(
        pool=pool,
        version=version,
        market=market,
        address=address,
        date=date,
    )


@router.get(
    "/market/governance",
    response_model=MarketGovernanceResponse,
    summary="Query Compound market governance parameters",
    response_description=(
        "返回某个 Compound v3 市场在指定时点生效的治理参数版本，包括利率曲线参数、奖励参数、清算参数以及逐 collateral 资产配置。"
    ),
    description=(
        "查询 Compound v3 市场治理参数。\n\n"
        "- `market` 支持市场地址或名称，如 `WETH`、`USDC`\n"
        "- `date` 为空时返回数据库中该市场最新一版治理配置\n"
        "- `date` 不为空时，返回 `effective_timestamp <= date` 的最近一版治理配置\n"
        "- `detail=false` 时不返回 `assets` 明细；传 `true` 才展开 collateral 配置\n"
        "- `date` 需精确到小时，例如 `2026-03-21T00:00:00Z`\n"
        "- 返回中的 `*_per_second_*` 字段为 Comet 合约原始每秒参数\n"
        "- 返回中的 `*_per_year_*` 字段为在服务端按 `31536000` 秒年化后的结果"
    ),
)
async def market_governance(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query(
        "v3",
        description='protocol version: "v2" | "v3" (currently only v3 is supported)',
    ),
    market: str = Query(
        ...,
        description='市场地址或名称：`"0x..." | "<SYMBOL>"`',
    ),
    date: str | None = Query(
        None,
        description="可选 UTC 小时时间；不传则返回最新治理参数版本。",
    ),
    detail: bool = Query(
        False,
        description="是否返回 collateral `assets` 明细；默认 false。",
    ),
) -> MarketGovernanceResponse:
    return await get_market_governance(
        pool=pool,
        version=version,
        market=market,
        date=date,
        detail=detail,
    )


@router.get(
    "/market/governance/period",
    response_model=MarketGovernancePeriodResponse,
    summary="Query Compound market governance changes over a period",
    response_description=(
        "返回指定时间区间内该市场发生治理参数变更的版本列表；仅包含有变动的数据点。"
    ),
    description=(
        "按时间区间查询 Compound v3 市场治理参数变更历史。\n\n"
        "- `start` 和 `end` 都需精确到小时\n"
        "- 仅返回 `effective_timestamp` 落在区间内的配置版本\n"
        "- `latest_only_per_day=true` 时，同一天内若发生多次变更，只保留当天最后一个版本\n"
        "- `detail=false` 时不返回 `assets` 明细；传 `true` 才展开 collateral 配置\n"
        "- 因为底层表按 `config_hash` 去重，所以返回结果天然只包含发生变更的点\n"
        "- 每个点都包含完整市场治理参数以及逐 collateral 资产配置"
    ),
)
async def market_governance_period(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query(
        "v3",
        description='protocol version: "v2" | "v3" (currently only v3 is supported)',
    ),
    market: str = Query(
        ...,
        description='市场地址或名称：`"0x..." | "<SYMBOL>"`',
    ),
    start: str = Query(..., description="UTC datetime at hour precision (start)"),
    end: str = Query(..., description="UTC datetime at hour precision (end)"),
    latest_only_per_day: bool = Query(
        False,
        description="若同一天内有多次治理参数变更，只返回当天最后一个版本。",
    ),
    detail: bool = Query(
        False,
        description="是否返回 collateral `assets` 明细；默认 false。",
    ),
) -> MarketGovernancePeriodResponse:
    return await get_market_governance_period(
        pool=pool,
        version=version,
        market=market,
        start=start,
        end=end,
        latest_only_per_day=latest_only_per_day,
        detail=detail,
    )


@router.get(
    "/market/state/period",
    response_model=MarketStatePeriodResponse,
    summary="Query Compound market state over a period",
)
async def market_state_period(
    pool: AsyncpgPool,
    version: str = Query(
        "v3",
        description='protocol version: "v2" | "v3" (currently only v3 is supported)',
    ),
    market: str = Query(
        ...,
        description="market name or address (case-insensitive for symbol)",
    ),
    start: str = Query(..., description="UTC datetime at hour precision (start)"),
    end: str = Query(..., description="UTC datetime at hour precision (end)"),
    interval: int = Query(
        24,
        description="Sampling interval in hours (default 24, allowed 1-168)",
    ),
    detail: bool = Query(False, description="Whether to expand reserve details"),
) -> "MarketStatePeriodResponse":
    return await get_market_state_period(
        pool=pool,
        version=version,
        market=market,
        start=start,
        end=end,
        interval=interval,
        detail=detail,
    )


@router.get(
    "/market/state",
    response_model=MarketStateResponse,
    summary="Query Compound market state",
)
async def market_state(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query(
        "v3",
        description='protocol version: "v2" | "v3" (currently only v3 is supported)',
    ),
    market: str = Query(
        ...,
        description="market name or address (case-insensitive for symbol)",
    ),
    date: str = Query(..., description="UTC datetime at hour precision"),
    detail: bool = Query(False, description="Whether to expand reserve details"),
) -> MarketStateResponse:
    return await get_market_state(
        pool=pool,
        version=version,
        market=market,
        date=date,
        detail=detail,
    )
