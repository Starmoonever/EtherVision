"""FastAPI routes for Compound scaffold."""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Request
from .schemas import (
    CompoundPositionReplayResponse,
    MarketsResponse,
    MarketGovernanceResponse,
    MarketGovernancePeriodResponse,
    MarketStatePeriodResponse,
    MarketStateResponse,
    V2MarketConfigResponse,
    V2MarketConfigPeriodResponse,
    V2ProtocolConfigResponse,
    V2ProtocolConfigPeriodResponse,
    UserPositionResponse,
)
from .service import (
    get_markets,
    get_market_governance,
    get_market_governance_period,
    get_market_state,
    get_market_state_period,
    get_v2_market_config,
    get_v2_market_config_period,
    get_v2_protocol_config,
    get_v2_protocol_config_period,
    get_positions,
    get_position_replay,
)
from ..database import AsyncpgPool


router = APIRouter(prefix="/api/compound")
_VERSION_DESC_BOTH = 'protocol version: "v2" | "v3" (both supported)'
_VERSION_DESC_V3_ONLY = (
    'protocol version: "v2" | "v3" (currently only v3 is supported; v2 returns 400)'
)
_VERSION_DESC_V2_ONLY = (
    'protocol version: "v2" | "v3" (currently only v2 is supported; v3 returns 400)'
)


def _parse_utc_time(time_str: str) -> int:
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return int(
                datetime.strptime(time_str, fmt)
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
        except ValueError:
            continue
    raise HTTPException(
        status_code=400,
        detail="date/time 格式无法识别，示例：2024-11-14T12:00:00Z、2024-11-14 12:00:00、2024-11-14",
    )


@router.get(
    "/markets",
    response_model=MarketsResponse,
    summary="List supported Compound markets",
)
async def markets(
    version: Literal["v2", "v3"] = Query(
        "v3",
        description=_VERSION_DESC_BOTH,
    ),
) -> MarketsResponse:
    return get_markets(version)


@router.get(
    "/{version}/markets",
    response_model=MarketsResponse,
    summary="List supported Compound markets (version in path)",
)
async def markets_by_path(
    version: Literal["v2", "v3"],
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
        "查询 Compound 单一用户地址的仓位快照（支持 v2 / v3）。\n\n"
        "- `address` 为必选，只返回该地址的仓位\n"
        "- `market` 可传单个市场地址/名称，或传 `all` 返回所有已支持市场\n"
        "- `date` 推荐直接传 `YYYY-MM-DD`\n"
        "- 如果 `date` 同时包含具体时间，服务会忽略时分秒，只取该 UTC 日期并归一到 `00:00:00Z`\n"
        "- `version=v3` 且 `date` 为空：直接从链上抓取实时数据，不写库\n"
        "- `version=v3` 且 `date` 不为空：优先查库；若库中不存在，则链上查询后写入快照表再返回\n"
        "- `version=v2`：仅返回数据库快照（`date` 为空时返回各市场最新快照）\n"
        "- 返回结果中的 `positions` 为该地址在命中市场下的仓位列表"
    ),
)
async def position(
    request: Request,
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query(
        "v3",
        description=_VERSION_DESC_BOTH,
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
            "不传则按 version 规则返回实时/快照数据。"
        ),
    ),
) -> UserPositionResponse:
    return await get_positions(
        pool=pool,
        version=version,
        market=market,
        address=address,
        date=date,
        w3=getattr(request.app.state, "w3", None),
    )


@router.get(
    "/{version}/position",
    response_model=UserPositionResponse,
    summary="Query a single Compound user position (version in path)",
)
async def position_by_path(
    request: Request,
    pool: AsyncpgPool,
    version: Literal["v2", "v3"],
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
            "不传则按 version 规则返回实时/快照数据。"
        ),
    ),
) -> UserPositionResponse:
    return await get_positions(
        pool=pool,
        version=version,
        market=market,
        address=address,
        date=date,
        w3=getattr(request.app.state, "w3", None),
    )


@router.get(
    "/position/replay",
    response_model=CompoundPositionReplayResponse,
    summary="Replay Compound user position by tx history",
    description=(
        "按交易粒度回放用户在 Compound 的历史仓位。\n\n"
        "- 先查缓存表 `loan.compound_position_snapshots`\n"
        "- 对于缓存缺失点：`version=v3` 自动在线补采并写回缓存\n"
        "- 对于缓存缺失点：`version=v2` 目前仅支持读缓存，不做在线补采\n"
        "- `detail=true` 时返回资产明细"
    ),
)
async def position_replay(
    request: Request,
    pool: AsyncpgPool,
    address: str = Query(..., description="用户地址（0x...）"),
    start: str = Query(..., description="起始时间（UTC）"),
    end: str = Query(..., description="结束时间（UTC）"),
    version: Literal["v2", "v3"] = Query("v3", description=_VERSION_DESC_BOTH),
    use_cache: bool = Query(True, description="是否优先使用缓存"),
    detail: bool = Query(False, description="是否返回资产明细"),
) -> CompoundPositionReplayResponse:
    from_ts = _parse_utc_time(start)
    to_ts = _parse_utc_time(end)
    if from_ts > to_ts:
        raise HTTPException(status_code=400, detail="start 必须早于或等于 end")
    return await get_position_replay(
        pool=pool,
        version=version,
        address=address,
        from_ts=from_ts,
        to_ts=to_ts,
        use_cache=use_cache,
        detail=detail,
        w3=getattr(request.app.state, "w3", None),
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
        description=_VERSION_DESC_V3_ONLY,
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
        description=_VERSION_DESC_V3_ONLY,
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
    "/market/config",
    response_model=V2MarketConfigResponse,
    summary="Query Compound v2 market config",
)
async def market_config(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query(
        "v2",
        description=_VERSION_DESC_V2_ONLY,
    ),
    market: str = Query(
        ...,
        description='市场地址或名称：`"0x..." | "<SYMBOL>"`',
    ),
    date: str | None = Query(
        None,
        description="可选 UTC 小时时间；不传则返回最新配置版本。",
    ),
) -> V2MarketConfigResponse:
    return await get_v2_market_config(
        pool=pool,
        version=version,
        market=market,
        date=date,
    )


@router.get(
    "/{version}/market/config",
    response_model=V2MarketConfigResponse,
    summary="Query Compound v2 market config (version in path)",
    description="该端点当前仅支持 `version=v2`，传 `v3` 会返回 400。",
)
async def market_config_by_path(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"],
    market: str = Query(
        ...,
        description='市场地址或名称：`"0x..." | "<SYMBOL>"`',
    ),
    date: str | None = Query(
        None,
        description="可选 UTC 小时时间；不传则返回最新配置版本。",
    ),
) -> V2MarketConfigResponse:
    return await get_v2_market_config(
        pool=pool,
        version=version,
        market=market,
        date=date,
    )


@router.get(
    "/market/config/period",
    response_model=V2MarketConfigPeriodResponse,
    summary="Query Compound v2 market config changes over a period",
)
async def market_config_period(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query(
        "v2",
        description=_VERSION_DESC_V2_ONLY,
    ),
    market: str = Query(
        ...,
        description='市场地址或名称：`"0x..." | "<SYMBOL>"`',
    ),
    start: str = Query(..., description="UTC datetime at hour precision (start)"),
    end: str = Query(..., description="UTC datetime at hour precision (end)"),
    latest_only_per_day: bool = Query(
        False,
        description="若同一天内有多次配置变更，只返回当天最后一个版本。",
    ),
) -> V2MarketConfigPeriodResponse:
    return await get_v2_market_config_period(
        pool=pool,
        version=version,
        market=market,
        start=start,
        end=end,
        latest_only_per_day=latest_only_per_day,
    )


@router.get(
    "/{version}/market/config/period",
    response_model=V2MarketConfigPeriodResponse,
    summary="Query Compound v2 market config changes (version in path)",
    description="该端点当前仅支持 `version=v2`，传 `v3` 会返回 400。",
)
async def market_config_period_by_path(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"],
    market: str = Query(
        ...,
        description='市场地址或名称：`"0x..." | "<SYMBOL>"`',
    ),
    start: str = Query(..., description="UTC datetime at hour precision (start)"),
    end: str = Query(..., description="UTC datetime at hour precision (end)"),
    latest_only_per_day: bool = Query(
        False,
        description="若同一天内有多次配置变更，只返回当天最后一个版本。",
    ),
) -> V2MarketConfigPeriodResponse:
    return await get_v2_market_config_period(
        pool=pool,
        version=version,
        market=market,
        start=start,
        end=end,
        latest_only_per_day=latest_only_per_day,
    )


@router.get(
    "/protocol/config",
    response_model=V2ProtocolConfigResponse,
    summary="Query Compound v2 protocol config",
)
async def protocol_config(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query(
        "v2",
        description=_VERSION_DESC_V2_ONLY,
    ),
    date: str | None = Query(
        None,
        description="可选 UTC 小时时间；不传则返回最新配置版本。",
    ),
) -> V2ProtocolConfigResponse:
    return await get_v2_protocol_config(
        pool=pool,
        version=version,
        date=date,
    )


@router.get(
    "/{version}/protocol/config",
    response_model=V2ProtocolConfigResponse,
    summary="Query Compound v2 protocol config (version in path)",
    description="该端点当前仅支持 `version=v2`，传 `v3` 会返回 400。",
)
async def protocol_config_by_path(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"],
    date: str | None = Query(
        None,
        description="可选 UTC 小时时间；不传则返回最新配置版本。",
    ),
) -> V2ProtocolConfigResponse:
    return await get_v2_protocol_config(
        pool=pool,
        version=version,
        date=date,
    )


@router.get(
    "/protocol/config/period",
    response_model=V2ProtocolConfigPeriodResponse,
    summary="Query Compound v2 protocol config changes over a period",
)
async def protocol_config_period(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"] = Query(
        "v2",
        description=_VERSION_DESC_V2_ONLY,
    ),
    start: str = Query(..., description="UTC datetime at hour precision (start)"),
    end: str = Query(..., description="UTC datetime at hour precision (end)"),
    latest_only_per_day: bool = Query(
        False,
        description="若同一天内有多次配置变更，只返回当天最后一个版本。",
    ),
) -> V2ProtocolConfigPeriodResponse:
    return await get_v2_protocol_config_period(
        pool=pool,
        version=version,
        start=start,
        end=end,
        latest_only_per_day=latest_only_per_day,
    )


@router.get(
    "/{version}/protocol/config/period",
    response_model=V2ProtocolConfigPeriodResponse,
    summary="Query Compound v2 protocol config changes (version in path)",
    description="该端点当前仅支持 `version=v2`，传 `v3` 会返回 400。",
)
async def protocol_config_period_by_path(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"],
    start: str = Query(..., description="UTC datetime at hour precision (start)"),
    end: str = Query(..., description="UTC datetime at hour precision (end)"),
    latest_only_per_day: bool = Query(
        False,
        description="若同一天内有多次配置变更，只返回当天最后一个版本。",
    ),
) -> V2ProtocolConfigPeriodResponse:
    return await get_v2_protocol_config_period(
        pool=pool,
        version=version,
        start=start,
        end=end,
        latest_only_per_day=latest_only_per_day,
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
        description=_VERSION_DESC_BOTH,
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
    "/{version}/market/state/period",
    response_model=MarketStatePeriodResponse,
    summary="Query Compound market state over a period (version in path)",
)
async def market_state_period_by_path(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"],
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
        description=_VERSION_DESC_BOTH,
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


@router.get(
    "/{version}/market/state",
    response_model=MarketStateResponse,
    summary="Query Compound market state (version in path)",
)
async def market_state_by_path(
    pool: AsyncpgPool,
    version: Literal["v2", "v3"],
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
