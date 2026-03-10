"""FastAPI 路由"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from ..database import AsyncpgPool, DbSession
from .constants import ETH_COLLATERAL_RATIO_MIN, ETH_DEBT_RATIO_MIN
from .schemas import (
    BorrowPositionResponse,
    BorrowUserPositionResponse,
    HistoricalPositionResponse,
    LiquidationPeriodItem,
    LiquidationSimResponse,
    MarketReplayResponse,
    PositionReplayResponse,
    PositionResponse,
    PricePeriodResponse,
    PriceResponse,
    ShortLiqPeriodItem,
    ShortLiqSimResponse,
    TxHistoryResponse,
)
from .service import (
    get_borrow_user_position,
    get_eth_price,
    get_market_replay,
    get_positions_history,
    get_price_period,
    get_sorted_borrow_positions,
    get_sorted_positions,
    get_user_position,
    get_user_position_history,
    get_user_position_replay,
    get_user_tx_history,
    simulate_liquidation,
    simulate_liquidation_period,
    simulate_short_liquidation,
    simulate_short_liquidation_period,
)

router = APIRouter(prefix="/api")


def _w3(request: Request):
    w3 = request.app.state.w3
    if w3 is None:
        raise HTTPException(status_code=503, detail="RPC 节点尚未就绪，请稍后重试")
    return w3


def _parse_utc_time(time_str: str) -> int:
    """UTC 时间字符串 → Unix 秒级时间戳，失败抛 HTTPException。"""
    from datetime import datetime, timezone

    _FMTS = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in _FMTS:
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
        detail="date/time 格式无法识别，支持示例：2024-11-14T12:00:00Z、2024-11-14 12:00:00、2024-11-14",
    )


@router.get(
    "/position",
    response_model=PositionResponse | HistoricalPositionResponse,
    summary="查询用户 Aave 仓位",
    description=(
        "查询指定地址的 Aave V3 仓位。\n\n"
        "- 省略 `date`：实时从以太主网链上查询，返回 `PositionResponse`\n"
        "- 指定 `date`：从 aave.aave_history 重建历史时间点仓位（含利息估算，价格来自 DeFiLlama），返回 `HistoricalPositionResponse`\n\n"
        "支持格式：`2024-11-14T12:00:00Z` / `2024-11-14 12:00:00` / `2024-11-14`"
    ),
)
async def user_position(
    pool: AsyncpgPool,
    request: Request,
    address: str = Query(..., description="以太坊錢包地址（支持校验和或小写）"),
    date: str | None = Query(
        None,
        description="历史时间点（UTC），如 2024-01-01；省略则查询实时链上数据",
    ),
    version: Literal["v2", "v3"] = Query(
        "v3", description="Aave 协议版本：v2 或 v3（默认）"
    ),
) -> PositionResponse | HistoricalPositionResponse:
    if date is None:
        return await get_user_position(_w3(request), address, protocol=version)
    ts = _parse_utc_time(date)
    result = await get_user_position_history(pool, address, ts)
    if result is None:
        # 历史 DB 中无该地址的操作记录，仓位未发生变化，回退到实时链上数据
        return await get_user_position(_w3(request), address, protocol=version)
    return result


@router.get(
    "/positions",
    response_model=list[PositionResponse] | list[HistoricalPositionResponse],
    summary="批量查询仓位排行",
    description=(
        "查询 Aave V3 仓位排行。\n\n"
        "- 省略 `date`：从数据库读取已爬取的实时快照，支持 `orderby` / `order` 排序，最多 200 条，返回 `list[PositionResponse]`\n"
        "- 指定 `date`：从 aave.aave_history 计算历史时间点 top-N 用户（按 ETH 抵押量降序，近似值，最多 100 条），返回 `list[HistoricalPositionResponse]`\n\n"
        "支持格式：`2024-11-14T12:00:00Z` / `2024-11-14 12:00:00` / `2024-11-14`"
    ),
)
async def positions(
    session: DbSession,
    pool: AsyncpgPool,
    request: Request,
    orderby: Literal[
        "liq_price",
        "health_factor",
        "eth_collateral_amount",
        "eth_collateral_usd",
        "total_debt_usd",
    ] = Query(
        "liq_price",
        description="排序字段（仅实时模式有效）：liq_price / health_factor / eth_collateral_amount / eth_collateral_usd / total_debt_usd",
    ),
    order: Literal["asc", "desc"] = Query(
        "asc",
        description="排序方向（仅实时模式有效）：asc=升序，desc=降序",
    ),
    limit: int = Query(
        10, ge=1, le=200, description="返回记录数（实时模式最多 200，历史模式最多 100）"
    ),
    date: str | None = Query(
        None,
        description="历史时间点（UTC），如 2024-01-01；省略则查询数据库实时快照",
    ),
    version: Literal["v2", "v3"] = Query(
        "v3", description="Aave 协议版本：v2 或 v3（默认）"
    ),
) -> list[PositionResponse] | list[HistoricalPositionResponse]:
    if date is None:
        return await get_sorted_positions(
            session, orderby=orderby, order=order, limit=limit, protocol=version
        )
    ts = _parse_utc_time(date)
    return await get_positions_history(pool, ts, limit=min(limit, 100))


@router.get(
    "/price",
    response_model=PriceResponse,
    summary="查询资产价格（当前或历史）",
    description=(
        "查询资产 USD 价格。\n\n"
        "- `time=now`（默认）：从链上 Aave Oracle 实时查询当前价格\n"
        "- `time=<UTC 时间字符串>`：从 DeFiLlama 查询历史价格\n\n"
        "支持格式：`2024-11-14T12:00:00Z` / `2024-11-14 12:00:00` / `2024-11-14`"
    ),
)
async def asset_price(
    request: Request,
    asset: str = Query("eth", description="资产名称，如 eth、wbtc、usdc"),
    time: str = Query(
        "now",
        description="now = 实时价格；UTC 时间字符串 = 历史价格，如 2024-11-14T12:00:00Z",
    ),
) -> PriceResponse:
    if time == "now":
        return await get_eth_price(_w3(request), asset)
    ts = _parse_utc_time(time)
    return await get_eth_price(_w3(request), asset, timestamp=ts)


@router.get(
    "/liquidate",
    response_model=LiquidationSimResponse,
    summary="模拟 ETH 价格下跌时的清算情况",
    description=(
        "模拟当 ETH 价格跌至指定值时，有哪些账户会被清算，"
        "以及清算人可获取的抵押品总价值（含 5% 清算奖励折价）。\n\n"
        "数据来源：数据库实时快照（需先运行 `aave-crawler crawl`）。\n\n"
        "**清算折价说明**：Aave V3 WETH 清算奖励系数为 1.05，"
        "即清算人偿还 1 USD 债务可获得 1.05 USD 的 ETH 抵押品。\n"
        "`total_liquidation_usd = Σ min(债务 × 1.05, ETH抵押品USD)`"
    ),
)
async def liquidate_simulation(
    session: DbSession,
    request: Request,
    eth_price: float = Query(
        ...,
        gt=0,
        description="模拟的 ETH 价格（USD），必须大于 0",
    ),
    limit: int = Query(
        100,
        ge=1,
        le=1000,
        description="返回的仓位数量，默认 100，最多 1000",
    ),
    orderby: Literal[
        "liq_price",
        "eth_collateral_amount",
        "eth_collateral_usd",
        "total_debt_usd",
    ] = Query(
        "liq_price",
        description="排序字段：liq_price / eth_collateral_amount / eth_collateral_usd / total_debt_usd",
    ),
    order: Literal["desc", "asc"] = Query(
        "desc",
        description="排序方向：desc=降序（默认），asc=升序",
    ),
    eth_ratio: float = Query(
        float(ETH_COLLATERAL_RATIO_MIN),
        ge=0.0,
        le=1.0,
        description="ETH 抵押品占比过滤阈値：仅当 eth_collateral_usd / total_collateral_usd >= 该値时才纳入计算，取値 [0, 1]，默认 "
        + str(ETH_COLLATERAL_RATIO_MIN),
    ),
    cap: float | None = Query(
        None,
        gt=0,
        description="liq_price 上限（USD）：仅返回 liq_price < cap 的地址；省略则返回全部",
    ),
    version: Literal["v2", "v3"] = Query(
        "v3", description="Aave 协议版本：v2 或 v3（默认）"
    ),
) -> LiquidationSimResponse:
    from decimal import Decimal

    # 自动获取当前 ETH 实时价格，用于过滤掉上涨清算仓位（liq_price > 当前价格）
    current_eth_price: Decimal | None = None
    try:
        w3 = _w3(request)
        price_resp = await get_eth_price(w3, "eth")
        current_eth_price = Decimal(str(price_resp.price_usd))
    except Exception:
        pass  # RPC 不可用时降级处理：不过滤，结果可能包含上涨清算仓位

    return await simulate_liquidation(
        session,
        Decimal(str(eth_price)),
        orderby=orderby,
        order=order,
        limit=limit,
        eth_ratio=Decimal(str(eth_ratio)),
        protocol=version,
        cap=Decimal(str(cap)) if cap is not None else None,
        current_eth_price=current_eth_price,
    )


@router.get(
    "/price/period",
    response_model=PricePeriodResponse,
    summary="查询资产历史价格序列",
    description=(
        "从 DeFiLlama 查询指定资产在 start～end 时间段内，按 interval 分钟间隔的历史 USD 价格序列。\n\n"
        "支持时间格式：`2024-11-14T12:00:00Z` / `2024-11-14 12:00:00` / `2024-11-14`"
    ),
)
async def asset_price_period(
    request: Request,
    asset: str = Query("eth", description="资产名称，如 eth、wbtc、usdc"),
    start: str = Query(..., description="起始 UTC 时间，如 2024-01-01"),
    end: str = Query(..., description="结束 UTC 时间，如 2024-12-31"),
    interval: int = Query(60, ge=1, description="采样间隔（分钟），最小 1"),
) -> PricePeriodResponse:
    start_ts = _parse_utc_time(start)
    end_ts = _parse_utc_time(end)
    return await get_price_period(
        _w3(request), asset, start_ts=start_ts, end_ts=end_ts, interval_minutes=interval
    )


@router.get(
    "/liquidate/period",
    response_model=list[LiquidationPeriodItem],
    summary="模拟 ETH 价格在区间内波动时的清算变化",
    description=(
        "分析 ETH 价格在 start～end 区间内，每隔 interval 步长时触发清算的汇总统计。\n\n"
        "返回按价格升序排列的清算快照序列，可观察不同价格点的清算量和可清算抵押品变化趋势。\n\n"
        "**注意**：start 必须 <= end，interval 必须大于 0。"
    ),
)
async def liquidate_period(
    pool: AsyncpgPool,
    request: Request,
    start: float = Query(..., gt=0, description="起始 ETH 价格（USD），必须大于 0"),
    end: float = Query(..., gt=0, description="结束 ETH 价格（USD），必须 >= start"),
    interval: float = Query(..., gt=0, description="价格步长（USD），必须大于 0"),
    eth_ratio: float = Query(
        float(ETH_COLLATERAL_RATIO_MIN),
        ge=0.0,
        le=1.0,
        description="ETH 抵押品占比过滤阈値，取値 [0, 1]，默认 "
        + str(ETH_COLLATERAL_RATIO_MIN),
    ),
    version: Literal["v2", "v3"] = Query(
        "v3", description="Aave 协议版本：v2 或 v3（默认）"
    ),
) -> list[LiquidationPeriodItem]:
    from decimal import Decimal

    # 自动获取当前 ETH 实时价格，用于过滤掉上涨清算仓位位
    current_eth_price: Decimal | None = None
    try:
        w3 = _w3(request)
        price_resp = await get_eth_price(w3, "eth")
        current_eth_price = Decimal(str(price_resp.price_usd))
    except Exception:
        pass

    return await simulate_liquidation_period(
        pool,
        start_price=Decimal(str(start)),
        end_price=Decimal(str(end)),
        interval=Decimal(str(interval)),
        eth_ratio=Decimal(str(eth_ratio)),
        protocol=version,
        current_eth_price=current_eth_price,
    )


# ── 历史回放路由 ───────────────────────────────────────────────────────────────────────


@router.get(
    "/position/replay",
    response_model=PositionReplayResponse,
    summary="历史仓位回放",
    description=(
        "以 transaction 为数据点，回放指定地址在时间范围内每笔交易时刻的链上真实仓位。\n\n"
        "- 通过 RPC `eth_call(block_identifier=N)` 直接读取链上状态，**无利息重建误差**\n"
        "- 首次查询多数时间用于 RPC 重放；缓存命中后直接返回，响应毫秒级\n"
        "- 返回字段：`timestamp`, `total_collateral_usd`, `total_debt_usd`, "
        "`health_factor`, `liq_price`, `eth_price_usd`，可选 `detail=true` 展开资产明细\n\n"
        "支持时间格式：`2024-01-01` / `2024-11-14T12:00:00Z` / `2024-11-14 12:00:00`"
    ),
)
async def user_position_replay(
    pool: AsyncpgPool,
    request: Request,
    address: str = Query(..., description="以太坊錢包地址"),
    start: str = Query(..., description="起始时间（UTC），如 2024-01-01"),
    end: str = Query(..., description="结束时间（UTC），如 2024-12-31"),
    version: Literal["v2", "v3"] = Query("v3", description="协议版本"),
    use_cache: bool = Query(True, description="是否优先使用缓存（默认 true）"),
    detail: bool = Query(False, description="是否展开各个资产明细（默认 false）"),
) -> PositionReplayResponse:
    from_ts = _parse_utc_time(start)
    to_ts = _parse_utc_time(end)
    if from_ts > to_ts:
        raise HTTPException(status_code=400, detail="start 必须早于或等于 end")
    return await get_user_position_replay(
        pool,
        _w3(request),
        address,
        from_ts=from_ts,
        to_ts=to_ts,
        protocol=version,
        use_cache=use_cache,
        detail=detail,
    )


@router.get(
    "/positions/replay",
    response_model=MarketReplayResponse,
    summary="大盘历史快照回放",
    description=(
        "查询 Aave V2/V3 某时间段内的全市场历史大盘数据，"
        "每个区块快照为一个数据点。\n\n"
        "- 数据来源：`loan.aave_v{2|3}_market_totals`（汇总表，滚动更新），需要先运行 `collect_market_snapshots.py` 采集\n"
        "- `interval` 控制数据点密度，单位小时，从起始时间按间隔选取最近的快照\n"
        "- `detail=true` 时展开每个 reserve 的明细数据\n\n"
        "支持时间格式：`2024-11-14T12:00:00Z` / `2024-01-01`"
    ),
)
async def market_snapshot_replay(
    pool: AsyncpgPool,
    request: Request,
    start: str = Query(..., description="起始时间（UTC），如 2024-01-01"),
    end: str = Query(..., description="结束时间（UTC），如 2025-01-01"),
    version: Literal["v2", "v3"] = Query(
        "v3", description="Aave 协议版本：v2 或 v3（默认）"
    ),
    interval: int = Query(
        24, ge=1, description="采样间隔（小时），默认 24（每天一个数据点）"
    ),
    detail: bool = Query(False, description="是否展开每个 reserve 明细（默认 false）"),
) -> MarketReplayResponse:
    from_ts = _parse_utc_time(start)
    to_ts = _parse_utc_time(end)
    if from_ts > to_ts:
        raise HTTPException(status_code=400, detail="start 必须早于或等于 end")
    return await get_market_replay(
        pool,
        protocol=version,
        from_ts=from_ts,
        to_ts=to_ts,
        interval_hours=interval,
        detail=detail,
        w3=_w3(request),
    )


@router.get(
    "/txs",
    response_model=TxHistoryResponse,
    summary="查询用户 Aave 历史交易列表",
    description=(
        "列出指定地址在时间范围内所有触发 Aave 仓位变化的交易（supply / withdraw / borrow / repay / liquidationcall）。\n\n"
        "每条记录会标注该 tx 的仓位快照是否已在缓存中（`cached: true/false`），方便估训后续回放的 RPC 开销。\n\n"
        "数据来源：`aave.aave_history` 表。"
    ),
)
async def user_tx_history(
    pool: AsyncpgPool,
    request: Request,
    address: str = Query(..., description="以太坊錢包地址"),
    start: str = Query(..., description="起始时间（UTC）"),
    end: str = Query(..., description="结束时间（UTC）"),
    version: Literal["v2", "v3"] = Query("v3", description="协议版本"),
    detail: bool = Query(
        False, description="是否返回完整交易列表（默认 false，仅返回汇总统计）"
    ),
) -> TxHistoryResponse:
    from_ts = _parse_utc_time(start)
    to_ts = _parse_utc_time(end)
    return await get_user_tx_history(
        pool,
        address,
        from_ts=from_ts,
        to_ts=to_ts,
        protocol=version,
        detail=detail,
    )


# ── 借贷端（做空 ETH / borrow WETH）清算分析路由 ─────────────────────────────


@router.get(
    "/borrow/positions",
    response_model=list[BorrowPositionResponse],
    summary="查询借贷端仓位（做空 ETH / 借入 WETH）",
    description=(
        "返回数据库中已爬取的借入了 WETH 的仓位，按指定字段排序。\n\n"
        "**触发清算条件**：ETH 价格上涨至 `liq_price_rise` 时，"
        "该仓位的健康系数将触碰 1.0，面临被清算风险。\n\n"
        "`liq_price_rise = 0` 表示该仓位无 ETH 上涨清算风险（例如抵押品中含同比例 ETH 系资产）。\n\n"
        "数据来源：数据库实时快照（需先运行 `aave-crawler crawl -p v3_borrow`）。"
    ),
)
async def borrow_positions(
    session: DbSession,
    request: Request,
    orderby: Literal[
        "liq_price_rise",
        "weth_debt_usd",
        "total_debt_usd",
        "health_factor",
    ] = Query("liq_price_rise", description="排序字段"),
    order: Literal["asc", "desc"] = Query(
        "asc", description="排序方向：asc=升序（默认），desc=降序"
    ),
    limit: int = Query(10, ge=1, le=200, description="返回数量，最多 200"),
    version: Literal["v2", "v3"] = Query(
        "v3", description="Aave 协议版本：v2 或 v3（默认）"
    ),
) -> list[BorrowPositionResponse]:
    protocol = f"{version}_borrow"
    return await get_sorted_borrow_positions(
        session,
        orderby=orderby,
        order=order,
        limit=limit,
        protocol=protocol,
    )


@router.get(
    "/borrow/position",
    response_model=BorrowUserPositionResponse,
    summary="查询单个地址的借贷端仓位详情",
    description=(
        "从数据库快照中读取指定地址的借贷端仓位（借入 WETH 场景）。\n\n"
        "包含汇总信息（weth_debt、liq_price_rise、健康系数等）以及每个资产的 reserve 明细。\n\n"
        "数据来源：数据库实时快照（需先运行 `aave-crawler crawl -p v3_borrow`）。\n\n"
        "地址不存在时返回 404。"
    ),
)
async def borrow_user_position(
    pool: AsyncpgPool,
    request: Request,
    address: str = Query(..., description="以太坊钱包地址（支持校验和或小写）"),
    version: Literal["v2", "v3"] = Query(
        "v3", description="Aave 协议版本：v2 或 v3（默认）"
    ),
) -> BorrowUserPositionResponse:
    protocol = f"{version}_borrow"
    result = await get_borrow_user_position(pool, address, protocol=protocol)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"地址 {address} 在 {protocol} 数据库中不存在，请先运行爬虫或确认地址正确",
        )
    return result


@router.get(
    "/borrow/liquidate",
    response_model=ShortLiqSimResponse,
    summary="模拟 ETH 价格上涨时的做空清算情况",
    description=(
        "模拟当 ETH 价格涨至指定值时，有哪些借入 WETH 的账户会被清算，"
        "以及清算人可获取的非 ETH 抵押品总价值（含 5% 清算奖励折价）。\n\n"
        "数据来源：数据库实时快照（需先运行 `aave-crawler crawl -p v3_borrow`）。\n\n"
        "**触发条件**：`liq_price_rise > 0 AND liq_price_rise <= eth_price`\n\n"
        "**清算折价说明**：`total_liquidation_usd = Σ min(WETH债务USD × 1.05, 总抵押USD)`"
    ),
)
async def borrow_liquidate_simulation(
    pool: AsyncpgPool,
    request: Request,
    eth_price: float = Query(
        ..., gt=0, description="模拟的 ETH 价格（USD），必须大于 0"
    ),
    limit: int = Query(
        100, ge=1, le=1000, description="返回的仓位数量，默认 100，最多 1000"
    ),
    orderby: Literal[
        "liq_price_rise",
        "weth_debt_usd",
        "total_debt_usd",
    ] = Query("liq_price_rise", description="排序字段"),
    order: Literal["desc", "asc"] = Query(
        "asc", description="排序方向：asc=升序（默认），desc=降序"
    ),
    cap: float | None = Query(
        None,
        gt=0,
        description="liq_price_rise 上限（USD）：仅返回 liq_price_rise < cap 的地址；省略则返回全部",
    ),
    eth_ratio: float = Query(
        float(ETH_DEBT_RATIO_MIN),
        ge=0,
        le=1,
        description="WETH 债务占总债务的最小比例（0~1），过滤掉非 WETH 主导的仓位，默认 "
        + str(ETH_DEBT_RATIO_MIN),
    ),
    version: Literal["v2", "v3"] = Query(
        "v3", description="Aave 协议版本：v2 或 v3（默认）"
    ),
) -> ShortLiqSimResponse:
    from decimal import Decimal

    protocol = f"{version}_borrow"
    return await simulate_short_liquidation(
        pool,
        Decimal(str(eth_price)),
        orderby=orderby,
        order=order,
        limit=limit,
        protocol=protocol,
        cap=Decimal(str(cap)) if cap is not None else None,
        eth_ratio=Decimal(str(eth_ratio)),
    )


@router.get(
    "/borrow/liquidate/period",
    response_model=list[ShortLiqPeriodItem],
    summary="模拟 ETH 价格在区间内上涨时的做空清算变化",
    description=(
        "分析 ETH 价格在 start～end 区间内，每隔 interval 步长时借贷端触发清算的汇总统计。\n\n"
        "返回按价格升序排列的清算快照序列，可观察不同价格点的做空清算量变化趋势。\n\n"
        "**注意**：start 必须 <= end，interval 必须大于 0。"
    ),
)
async def borrow_liquidate_period(
    pool: AsyncpgPool,
    request: Request,
    start: float = Query(..., gt=0, description="起始 ETH 价格（USD），必须大于 0"),
    end: float = Query(..., gt=0, description="结束 ETH 价格（USD），必须 >= start"),
    interval: float = Query(..., gt=0, description="价格步长（USD），必须大于 0"),
    eth_ratio: float = Query(
        float(ETH_DEBT_RATIO_MIN),
        ge=0,
        le=1,
        description="WETH 债务占总债务的最小比例（0~1），过滤掉非 WETH 主导的仓位，默认 "
        + str(ETH_DEBT_RATIO_MIN),
    ),
    version: Literal["v2", "v3"] = Query(
        "v3", description="Aave 协议版本：v2 或 v3（默认）"
    ),
) -> list[ShortLiqPeriodItem]:
    from decimal import Decimal

    protocol = f"{version}_borrow"
    return await simulate_short_liquidation_period(
        pool,
        start_price=Decimal(str(start)),
        end_price=Decimal(str(end)),
        interval=Decimal(str(interval)),
        protocol=protocol,
        eth_ratio=Decimal(str(eth_ratio)),
    )
