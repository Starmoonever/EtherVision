"""Service helpers for Morpho APIs."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import re
from typing import Any, cast

from crawler_shared.api.constants import ETHEREUM_PRICE_ASSETS, PRICE_ASSET_ALIASES
from crawler_shared.api.service import get_price
from crawler_shared.price_history import (
    get_historical_price_usd,
    get_historical_prices_usd,
)
from eth_typing import ChecksumAddress
import httpx
from fastapi import HTTPException
from web3 import AsyncWeb3

from ..constants import (
    MORPHO_BLUE_ADDRESS,
    MORPHO_CHAIN,
    MORPHO_DEFAULT_MARKET_TYPE,
    MORPHO_PROTOCOL,
)
from ..database import AsyncpgPool
from ..db import (
    fetch_current_user_positions,
    fetch_position_replay_snapshots,
    upsert_current_user_position,
    upsert_market,
    upsert_position_replay_snapshots,
)
from ..rpc import (
    IRM_ABI,
    MorphoReplayEvent,
    MorphoRealtimePosition,
    WAD,
    ZERO_ADDRESS,
    _format_decimal_fixed,
    _mul_div_down,
    _w_taylor_compounded,
    fetch_market_state,  # api/morpho/market/state相关
    fetch_position_at_block,
    fetch_realtime_position,
    fetch_user_market_replay_events,
)
from .constants import MORPHO_BLUE_GRAPHQL_URL  # api/morpho/markets相关
from .constants import MORPHO_MAIN_GRAPHQL_URL  # api/morpho/vault/v1/state相关
from .constants import MORPHO_MAIN_GRAPHQL_URL_V2  # api/morpho/vault/v2/state相关
from .schemas import (
    MorphoMarketAssetItem,  # api/morpho/markets相关
    MorphoMarketListItem,  # api/morpho/markets相关
    MorphoMarketStateResponse,  # api/morpho/market/state相关
    MorphoMarketListResponse,  # api/morpho/markets相关
    MorphoPositionAssetResponse,
    MorphoPositionReplayPointResponse,
    MorphoPositionReplayResponse,
    MorphoPositionResponse,
    MorphoScaffoldStatusResponse,
)
from .schemas import MorphoVaultV1StateGraphQLResponse  # api/morpho/vault/v1/state相关
from .schemas import MorphoVaultV2StateGraphQLResponse  # api/morpho/vault/v2/state相关
from .schemas import (
    MorphoVotesAsset,  # api/morpho/vaults相关
    MorphoVotesItem,  # api/morpho/vaults相关
    MorphoVotesResponse,  # api/morpho/vaults相关
)

BRIEF_LABELS = {
    "supply": "供给",
    "withdraw": "提取",
    "borrow": "借入",
    "repay": "还款",
    "supply_collateral": "新增抵押",
    "withdraw_collateral": "移除抵押",
    "liquidation": "被清算",
}


# api/morpho/markets相关：币名按共享字典映射到 ethereum token address
def _resolve_ethereum_token_address(value: str) -> str | None:
    key = value.strip()
    if not key:
        return None
    alias_key = key.upper()
    canonical_asset = PRICE_ASSET_ALIASES.get(alias_key, alias_key)
    token = ETHEREUM_PRICE_ASSETS.get(canonical_asset.upper())
    if not token:
        return None
    return str(token[1]).strip()


# api/morpho/markets相关：GET /api/morpho/markets 从 Morpho Blue GraphQL 拉取单市场 TVL/利用率
_MARKET_BY_ID_GRAPHQL = """
query MarketMetrics($marketId: String!, $chainId: Int!) {
  marketById(marketId: $marketId, chainId: $chainId) {
    marketId
    loanAsset {
      symbol
      address
    }
    collateralAsset {
      symbol
      address
    }
    state {
      sizeUsd
      utilization
    }
  }
}
""".strip()

# api/morpho/vault/v1/state相关：Morpho 主站 GraphQL，与 openapi 示例中 vaultByAddress / state / allocation 字段对齐
_VAULT_BY_ADDRESS_MAIN_GRAPHQL = """
query MorphoVaultByAddress($address: String!, $chainId: Int!) {
  vaultByAddress(address: $address, chainId: $chainId) {
    address
    name
    asset {
      address
      symbol
      decimals
    }
    state {
      totalAssetsUsd
      apy
      netApy
      netApyExcludingRewards
      avgNetApy
      avgNetApyExcludingRewards
      timelock
      fee
      allocation {
        market {
          market_id: marketId
          loanAsset {
            symbol
            address
          }
          collateralAsset {
            symbol
            address
          }
        }
        supplyAssets
        supplyAssetsUsd
        supplyCapUsd
      }
    }
  }
}
""".strip()

# api/morpho/vault/v1/state相关：按 market_id 查询 market 的 supply/borrow，用于估算可提取流动性
_MARKET_LIQUIDITY_BY_ID_GRAPHQL = """
query MarketLiquidity($marketId: String!, $chainId: Int!) {
  marketById(marketId: $marketId, chainId: $chainId) {
    state {
      supplyAssets
      borrowAssets
    }
  }
}
""".strip()

# api/morpho/vault/v2/state相关：Morpho 主站 GraphQL，字段对齐 tmp/morpho_vault_v2_xxx.json
_VAULT_V2_BY_ADDRESS_MAIN_GRAPHQL = """
query VaultV2ByAddress($address: String!, $chainId: Int!) {
  vaultV2ByAddress(address: $address, chainId: $chainId) {
    address
    name
    totalAssetsUsd
    idleAssetsUsd
    liquidityUsd
    apy
    netApy
    netApyExcludingRewards
    avgNetApy
    avgNetApyExcludingRewards
    maxApy
    forceDeallocatableLiquidityUsd
    performanceFee
    managementFee
    asset {
      address
      symbol
      decimals
    }
    # [V2_STATE_ADAPTERS_ADD] 新增：返回 adapters（按约定输出 address / market_id）
    adapters {
      items {
        type
        ... on MetaMorphoAdapter {
          position {
            state {
              address: id
              assets
              assetsUsd
            }
          }
        }
        ... on MorphoVaultV2Adapter {
          assets
          assetsUsd
          innerVault {
            address
          }
        }
        ... on MorphoMarketV1Adapter {
          assets
          assetsUsd
          positions {
            items {
              market_id: id
              state {
                supplyAssets
                supplyAssetsUsd
              }
            }
          }
        }
      }
    }
  }
}
""".strip()

# api/morpho/markets相关：为 True 时对每页市场请求 Blue API 填充 TVL/利用率；False 时跳过请求（字段为 null），保留下方拉取实现以便恢复
MORPHO_MARKETS_FETCH_BLUE_STATE = True


# api/morpho/markets相关：按 market_id 查询 Morpho Blue API，返回 TVL/利用率与 loan/collateral 资产信息
async def _fetch_market_metrics_from_blue_api(
    client: httpx.AsyncClient,
    *,
    market_id: str,
    chain_id: int,
) -> tuple[float | None, float | None, dict[str, Any], dict[str, Any]]:
    payload = {
        "query": _MARKET_BY_ID_GRAPHQL,
        "variables": {"marketId": market_id, "chainId": chain_id},
    }
    try:
        resp = await client.post(MORPHO_BLUE_GRAPHQL_URL, json=payload)
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Morpho Blue API 请求失败: {exc}",
        ) from exc
    if body.get("errors"):
        raise HTTPException(
            status_code=502,
            detail=f"Morpho Blue API 返回错误: {body['errors']}",
        )
    row = (body.get("data") or {}).get("marketById")
    if not row:
        return None, None, {}, {}
    state = row.get("state") or {}
    loan_asset = row.get("loanAsset") or {}
    collateral_asset = row.get("collateralAsset") or {}
    size = state.get("sizeUsd")
    util = state.get("utilization")
    try:
        size_f = float(size) if size is not None else None
    except (TypeError, ValueError):
        size_f = None
    try:
        util_f = float(util) if util is not None else None
    except (TypeError, ValueError):
        util_f = None
    return size_f, util_f, loan_asset, collateral_asset


# api/morpho/vault/v1/state相关：GET /api/morpho/vault/v1/state，透传 Morpho 主站 GraphQL 的 data + extensions
async def get_vault_state_main_graphql(
    *,
    address: str,
    chain_id: int = 1,
    w3: AsyncWeb3 | None = None,
    pool: AsyncpgPool | None = None,
) -> MorphoVaultV1StateGraphQLResponse:
    raw = (address or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="address 不能为空")
    try:
        checksum = AsyncWeb3.to_checksum_address(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效 EVM 地址: {exc}") from exc
    # api/morpho/vault/v1/state相关：优先查表命中，减少 GraphQL 请求
    if pool is not None:
        table_data = await _fetch_vault_v1_state_from_table(
            pool, vault_address=checksum
        )
        if table_data is not None:
            vault_table = (table_data.get("data") or {}).get("vaultByAddress") or {}
            allocations_table = (
                (vault_table.get("state") or {}).get("allocation")
            ) or []
            if w3 is not None and isinstance(allocations_table, list):
                await _mark_vault_allocation_market_data_sources(
                    w3, pool=pool, allocations=allocations_table
                )
            if isinstance(vault_table, dict):
                vault_table["dataSource"] = "table"
            data_payload_v1 = cast(dict[str, Any], table_data.get("data") or {})
            return MorphoVaultV1StateGraphQLResponse(data=cast(Any, data_payload_v1))

    payload = {
        "query": _VAULT_BY_ADDRESS_MAIN_GRAPHQL,
        "variables": {"address": checksum, "chainId": chain_id},
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(MORPHO_MAIN_GRAPHQL_URL, json=payload)
            resp.raise_for_status()
            body = cast(dict[str, Any], resp.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Morpho 主站 GraphQL 请求失败: {exc}",
        ) from exc

    errs = body.get("errors") or []
    data = body.get("data")
    vault = (data or {}).get("vaultByAddress") if isinstance(data, dict) else None
    if vault is None:
        detail = "未找到该链上的 Vault"
        if errs and isinstance(errs[0], dict):
            detail = str(errs[0].get("message") or detail)
        raise HTTPException(status_code=404, detail=detail)

    # api/morpho/vault/v1/state相关：基于 allocation 与 market 可用流动性估算 liquidityUsd
    state = vault.get("state") if isinstance(vault, dict) else None
    allocations = state.get("allocation") if isinstance(state, dict) else None
    if isinstance(state, dict) and isinstance(allocations, list):
        liquidity_usd = Decimal("0")
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                tasks = [
                    _fetch_market_available_liquidity_assets(
                        client,
                        market_id=str(
                            ((item.get("market") or {}).get("market_id") or "")
                        ).strip(),
                        chain_id=chain_id,
                    )
                    if isinstance(item, dict)
                    else _done_none()
                    for item in allocations
                ]
                available_list = await asyncio.gather(*tasks, return_exceptions=True)
        except httpx.HTTPError:
            available_list = [None for _ in allocations]

        for item, available_any in zip(allocations, available_list):
            if not isinstance(item, dict):
                continue
            available_assets: Decimal | None
            if isinstance(available_any, BaseException):
                available_assets = None
            elif isinstance(available_any, Decimal):
                available_assets = available_any
            else:
                available_assets = None
            try:
                alloc_assets = Decimal(str(item.get("supplyAssets") or 0))
            except Exception:
                alloc_assets = Decimal("0")
            try:
                alloc_usd = Decimal(str(item.get("supplyAssetsUsd") or 0))
            except Exception:
                alloc_usd = Decimal("0")
            if alloc_assets <= 0:
                item.pop("supplyAssets", None)
                item["liquidityUsd"] = 0.0
                continue
            if available_assets is None:
                # 回退：查不到 market 状态时按 allocation 近似
                liq_assets = alloc_assets
            else:
                liq_assets = min(alloc_assets, available_assets)
            if liq_assets < 0:
                liq_assets = Decimal("0")
            # api/morpho/vault/v1/state相关：为每个 allocation 增加 market 级 liquidityUsd（Ii 口径）
            liq_usd_i = alloc_usd * (liq_assets / alloc_assets)
            item.pop("supplyAssets", None)
            item["liquidityUsd"] = float(liq_usd_i)
            liquidity_usd += liq_usd_i

        liquidity_usd_value = float(liquidity_usd)
        # api/morpho/vault/v1/state相关：把 liquidityUsd 字段放在 fee 下、allocation 上
        if "allocation" in state:
            allocation_value = state.pop("allocation")
            state["liquidityUsd"] = liquidity_usd_value
            state["allocation"] = allocation_value
        else:
            state["liquidityUsd"] = liquidity_usd_value
    if isinstance(vault, dict):
        vault["dataSource"] = "graphql"
        allocations_graphql = ((vault.get("state") or {}).get("allocation")) or []
        if (
            w3 is not None
            and pool is not None
            and isinstance(allocations_graphql, list)
        ):
            await _mark_vault_allocation_market_data_sources(
                w3, pool=pool, allocations=allocations_graphql
            )
    # api/morpho/vault/v1/state相关：GraphQL 命中后回写 vault 当前表（下次优先查表）
    if pool is not None and isinstance(vault, dict):
        await _upsert_vault_v1_state_to_table(pool, vault=vault)

    data_payload_v1 = cast(
        dict[str, Any],
        data if isinstance(data, dict) else {"vaultByAddress": vault},
    )
    return MorphoVaultV1StateGraphQLResponse(data=cast(Any, data_payload_v1))


# api/morpho/vault/v1/state相关：按地址查 vault 当前表并组装接口结构
async def _fetch_vault_v1_state_from_table(
    pool: AsyncpgPool, *, vault_address: str
) -> dict[str, Any] | None:
    vault_addr_b = _evm_to_db_bytes(vault_address)
    async with pool.acquire() as conn:
        head = await conn.fetchrow(
            """
            SELECT
                vault_address,
                vault_name,
                asset_address,
                asset_symbol,
                asset_decimals,
                total_assets_usd,
                apy,
                net_apy,
                net_apy_excluding_rewards,
                avg_net_apy,
                avg_net_apy_excluding_rewards,
                timelock_seconds,
                fee_raw,
                liquidity_usd
            FROM loan.morpho_vault_v1_current
            WHERE vault_address = $1
            LIMIT 1
            """,
            vault_addr_b,
        )
        if head is None:
            return None
        alloc_rows = await conn.fetch(
            """
            SELECT
                a.market_id,
                a.supply_assets_usd,
                a.supply_cap_usd,
                a.liquidity_usd,
                m.loan_symbol,
                m.loan_address,
                m.collateral_symbol,
                m.collateral_address
            FROM loan.morpho_vault_v1_allocation_current AS a
            LEFT JOIN loan.morpho_blue_current_markets AS m
              ON m.market_id = a.market_id
            WHERE a.vault_address = $1
            ORDER BY a.market_id
            """,
            vault_addr_b,
        )
    allocation: list[dict[str, Any]] = []
    for row in alloc_rows:
        allocation.append(
            {
                "market": {
                    "market_id": str(row["market_id"]),
                    "loanAsset": {
                        "symbol": row["loan_symbol"],
                        "address": _normalize_evm_address(
                            str(row["loan_address"] or ZERO_ADDRESS)
                        ),
                    },
                    "collateralAsset": {
                        "symbol": row["collateral_symbol"],
                        "address": _normalize_evm_address(
                            str(row["collateral_address"] or ZERO_ADDRESS)
                        ),
                    },
                },
                "supplyAssetsUsd": float(row["supply_assets_usd"] or 0),
                "supplyCapUsd": float(row["supply_cap_usd"] or 0),
                "liquidityUsd": float(row["liquidity_usd"] or 0),
            }
        )
    return {
        "data": {
            "vaultByAddress": {
                "address": _db_bytes_to_evm(head["vault_address"]),
                "name": head["vault_name"],
                "asset": {
                    "address": _db_bytes_to_evm(head["asset_address"]),
                    "symbol": head["asset_symbol"],
                    "decimals": head["asset_decimals"],
                },
                "state": {
                    "totalAssetsUsd": float(head["total_assets_usd"] or 0),
                    "apy": float(head["apy"] or 0),
                    "netApy": float(head["net_apy"] or 0),
                    "netApyExcludingRewards": float(
                        head["net_apy_excluding_rewards"] or 0
                    ),
                    "avgNetApy": float(head["avg_net_apy"] or 0),
                    "avgNetApyExcludingRewards": float(
                        head["avg_net_apy_excluding_rewards"] or 0
                    ),
                    "timelock": int(head["timelock_seconds"] or 0),
                    "fee": float(head["fee_raw"] or 0),
                    "liquidityUsd": float(head["liquidity_usd"] or 0),
                    "allocation": allocation,
                },
            }
        }
    }


# api/morpho/vault/v1/state相关：回写 vault 当前表
async def _upsert_vault_v1_state_to_table(
    pool: AsyncpgPool, *, vault: dict[str, Any]
) -> None:
    state = vault.get("state") or {}
    asset = vault.get("asset") or {}
    vault_addr = str(vault.get("address") or "").strip()
    if not vault_addr:
        return
    vault_addr_b = _evm_to_db_bytes(vault_addr)
    asset_addr_b = _evm_to_db_bytes(str(asset.get("address") or ZERO_ADDRESS))
    allocation = state.get("allocation") or []
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO loan.morpho_vault_v1_current (
                    vault_address, vault_name, asset_address, asset_symbol, asset_decimals,
                    total_assets_usd, apy, net_apy, net_apy_excluding_rewards,
                    avg_net_apy, avg_net_apy_excluding_rewards, timelock_seconds,
                    fee_raw, liquidity_usd, source_ts, updated_at
                )
                VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,NOW(),NOW()
                )
                ON CONFLICT (vault_address) DO UPDATE SET
                    vault_name = EXCLUDED.vault_name,
                    asset_address = EXCLUDED.asset_address,
                    asset_symbol = EXCLUDED.asset_symbol,
                    asset_decimals = EXCLUDED.asset_decimals,
                    total_assets_usd = EXCLUDED.total_assets_usd,
                    apy = EXCLUDED.apy,
                    net_apy = EXCLUDED.net_apy,
                    net_apy_excluding_rewards = EXCLUDED.net_apy_excluding_rewards,
                    avg_net_apy = EXCLUDED.avg_net_apy,
                    avg_net_apy_excluding_rewards = EXCLUDED.avg_net_apy_excluding_rewards,
                    timelock_seconds = EXCLUDED.timelock_seconds,
                    fee_raw = EXCLUDED.fee_raw,
                    liquidity_usd = EXCLUDED.liquidity_usd,
                    source_ts = NOW(),
                    updated_at = NOW()
                """,
                vault_addr_b,
                vault.get("name"),
                asset_addr_b,
                asset.get("symbol"),
                asset.get("decimals"),
                state.get("totalAssetsUsd"),
                state.get("apy"),
                state.get("netApy"),
                state.get("netApyExcludingRewards"),
                state.get("avgNetApy"),
                state.get("avgNetApyExcludingRewards"),
                state.get("timelock"),
                state.get("fee"),
                state.get("liquidityUsd"),
            )
            await conn.execute(
                """
                DELETE FROM loan.morpho_vault_v1_allocation_current
                WHERE vault_address = $1
                """,
                vault_addr_b,
            )
            rows: list[tuple[Any, ...]] = []
            for item in allocation:
                if not isinstance(item, dict):
                    continue
                market_id = str(
                    ((item.get("market") or {}).get("market_id") or "")
                ).strip()
                if not market_id:
                    continue
                rows.append(
                    (
                        vault_addr_b,
                        market_id,
                        item.get("supplyAssetsUsd"),
                        item.get("supplyCapUsd"),
                        item.get("liquidityUsd"),
                    )
                )
            if rows:
                await conn.executemany(
                    """
                    INSERT INTO loan.morpho_vault_v1_allocation_current (
                        vault_address, market_id, supply_assets_usd, supply_cap_usd, liquidity_usd, source_ts, updated_at
                    )
                    VALUES ($1,$2,$3,$4,$5,NOW(),NOW())
                    """,
                    rows,
                )


# api/morpho/vault/v1/state相关：为 allocation.market 标记 dataSource，必要时触发 market/state 回写
async def _mark_vault_allocation_market_data_sources(
    w3: AsyncWeb3, *, pool: AsyncpgPool, allocations: list[dict[str, Any]]
) -> None:
    for item in allocations:
        if not isinstance(item, dict):
            continue
        market = item.get("market")
        if not isinstance(market, dict):
            continue
        market_id = str(market.get("market_id") or "").strip()
        if not market_id:
            continue
        row = await _fetch_market_state_row_from_table(pool, market_id)
        if row is not None:
            market["dataSource"] = "table"
            continue
        # 未命中时调用 market/state 链上分支并回写表
        try:
            await get_market_state(w3, pool=pool, market_id=market_id, date=None)
            market["dataSource"] = "chain"
        except HTTPException:
            market["dataSource"] = "chain_error"


# api/morpho/vault/v1/state相关：查询单 market 的可用流动性（supplyAssets - borrowAssets）
async def _fetch_market_available_liquidity_assets(
    client: httpx.AsyncClient,
    *,
    market_id: str,
    chain_id: int,
) -> Decimal | None:
    if not market_id:
        return None
    payload = {
        "query": _MARKET_LIQUIDITY_BY_ID_GRAPHQL,
        "variables": {"marketId": market_id, "chainId": chain_id},
    }
    resp = await client.post(MORPHO_BLUE_GRAPHQL_URL, json=payload)
    resp.raise_for_status()
    body = cast(dict[str, Any], resp.json())
    if body.get("errors"):
        return None
    state = ((body.get("data") or {}).get("marketById") or {}).get("state") or {}
    try:
        supply_assets = Decimal(str(state.get("supplyAssets") or 0))
        borrow_assets = Decimal(str(state.get("borrowAssets") or 0))
    except Exception:
        return None
    available = supply_assets - borrow_assets
    return available if available > 0 else Decimal("0")


# api/morpho/vault/v1/state相关：给 gather 用的空协程占位
async def _done_none() -> None:
    return None


# [V2_STATE_ADAPTERS_ADD] 新增：去掉适配器标识里的链前缀（例如 "1-"）
def _strip_chain_prefix(text: Any) -> str:
    raw = str(text or "")
    return re.sub(r"^\d+-", "", raw)


# [V2_STATE_ADAPTERS_ADD] 新增：规范化 adapters 输出中的 id/address/market_id
def _normalize_v2_adapters_identifiers(vault: dict[str, Any]) -> None:
    adapters = (vault.get("adapters") or {}).get("items") or []
    if not isinstance(adapters, list):
        return
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        position = adapter.get("position")
        if isinstance(position, dict):
            state = position.get("state")
            if isinstance(state, dict) and state.get("address") is not None:
                state["address"] = _strip_chain_prefix(state.get("address"))
        positions = adapter.get("positions")
        if isinstance(positions, dict):
            p_items = positions.get("items") or []
            if isinstance(p_items, list):
                for p in p_items:
                    if isinstance(p, dict) and p.get("market_id") is not None:
                        p["market_id"] = _strip_chain_prefix(p.get("market_id"))


# api/morpho/vault/v2/state相关：GET /api/morpho/vault/v2/state，返回顶层 vaultV2ByAddress
async def get_vault_v2_state_main_graphql(
    *,
    address: str,
    chain_id: int = 1,
    pool: AsyncpgPool | None = None,
) -> MorphoVaultV2StateGraphQLResponse:
    raw = (address or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="address 不能为空")
    try:
        checksum = AsyncWeb3.to_checksum_address(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效 EVM 地址: {exc}") from exc
    # api/morpho/vault/v2/state相关：优先查表命中，减少 GraphQL 请求
    if pool is not None:
        table_data = await _fetch_vault_v2_state_from_table(
            pool, vault_address=checksum
        )
        if table_data is not None:
            vault_table = table_data.get("vaultV2ByAddress") or {}
            if isinstance(vault_table, dict):
                vault_table["dataSource"] = "table"
                # [V2_STATE_ADAPTERS_ADD] 新增：为 adapters 标记数据来源
                adapters = (vault_table.get("adapters") or {}).get("items") or []
                if isinstance(adapters, list):
                    for adapter in adapters:
                        if isinstance(adapter, dict):
                            adapter["dataSource"] = "table"
                _normalize_v2_adapters_identifiers(vault_table)
            return MorphoVaultV2StateGraphQLResponse(
                vaultV2ByAddress=cast(Any, vault_table)
            )

    payload = {
        "query": _VAULT_V2_BY_ADDRESS_MAIN_GRAPHQL,
        "variables": {"address": checksum, "chainId": chain_id},
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(MORPHO_MAIN_GRAPHQL_URL_V2, json=payload)
            resp.raise_for_status()
            body = cast(dict[str, Any], resp.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Morpho 主站 GraphQL V2 请求失败: {exc}",
        ) from exc

    errs = body.get("errors") or []
    data = body.get("data")
    vault = (data or {}).get("vaultV2ByAddress") if isinstance(data, dict) else None
    if vault is None:
        detail = "未找到该链上的 V2 Vault"
        if errs and isinstance(errs[0], dict):
            detail = str(errs[0].get("message") or detail)
        raise HTTPException(status_code=404, detail=detail)
    if isinstance(vault, dict):
        vault["dataSource"] = "graphql"
        # [V2_STATE_ADAPTERS_ADD] 新增：为 adapters 标记数据来源
        adapters = (vault.get("adapters") or {}).get("items") or []
        if isinstance(adapters, list):
            for adapter in adapters:
                if isinstance(adapter, dict):
                    adapter["dataSource"] = "graphql"
        _normalize_v2_adapters_identifiers(vault)
    # api/morpho/vault/v2/state相关：GraphQL 命中后回写 V2 当前表
    if pool is not None and isinstance(vault, dict):
        await _upsert_vault_v2_state_to_table(pool, vault=vault)

    return MorphoVaultV2StateGraphQLResponse(vaultV2ByAddress=cast(Any, vault))


# api/morpho/vault/v2/state相关：按地址查 V2 当前表并组装接口结构
async def _fetch_vault_v2_state_from_table(
    pool: AsyncpgPool, *, vault_address: str
) -> dict[str, Any] | None:
    vault_addr_b = _evm_to_db_bytes(vault_address)
    async with pool.acquire() as conn:
        head = await conn.fetchrow(
            """
            SELECT
                vault_address,
                vault_name,
                asset_address,
                asset_symbol,
                asset_decimals,
                total_assets_usd,
                idle_assets_usd,
                liquidity_usd,
                apy,
                net_apy,
                net_apy_excluding_rewards,
                avg_net_apy,
                avg_net_apy_excluding_rewards,
                max_apy,
                force_deallocatable_liquidity_usd,
                performance_fee,
                management_fee,
                market_asset,
                market_asset_usd
            FROM loan.morpho_vault_v2_current
            WHERE vault_address = $1
            LIMIT 1
            """,
            vault_addr_b,
        )
        if head is None:
            return None
        # [V2_STATE_ADAPTERS_ADD] 修改：改为读取 adapters 当前表
        adapter_rows = await conn.fetch(
            """
            SELECT
                id,
                assets,
                assets_usd,
                type
            FROM loan.morpho_vault_v2_adapters_current
            WHERE vault_address = $1
            """,
            vault_addr_b,
        )
    # [V2_STATE_ADAPTERS_ADD] 新增：按最小表结构重建 adapters 输出
    adapters_items: list[dict[str, Any]] = []
    for row in adapter_rows:
        adapter_type = str(row["type"] or "")
        adapter_id = str(row["id"] or "")
        assets = float(row["assets"] or 0)
        assets_usd = float(row["assets_usd"] or 0)
        if adapter_type == "v1":
            adapters_items.append(
                {
                    "type": "MetaMorpho",
                    "position": {
                        "state": {
                            "address": adapter_id,
                            "assets": assets,
                            "assetsUsd": assets_usd,
                        }
                    },
                }
            )
        elif adapter_type == "v2":
            adapters_items.append(
                {
                    "type": "MorphoVaultV2",
                    "assets": assets,
                    "assetsUsd": assets_usd,
                    "innerVault": {"address": adapter_id},
                }
            )
        else:
            adapters_items.append(
                {
                    "type": "MorphoMarketV1",
                    "assets": assets,
                    "assetsUsd": assets_usd,
                    "positions": {
                        "items": [
                            {
                                "market_id": adapter_id,
                                "state": {
                                    "supplyAssets": assets,
                                    "supplyAssetsUsd": assets_usd,
                                },
                            }
                        ]
                    },
                }
            )
    return {
        "vaultV2ByAddress": {
            "address": _db_bytes_to_evm(head["vault_address"]),
            "name": head["vault_name"],
            "totalAssetsUsd": float(head["total_assets_usd"] or 0),
            "idleAssetsUsd": float(head["idle_assets_usd"] or 0),
            "liquidityUsd": float(head["liquidity_usd"] or 0),
            "apy": float(head["apy"] or 0),
            "netApy": float(head["net_apy"] or 0),
            "netApyExcludingRewards": float(head["net_apy_excluding_rewards"] or 0),
            "avgNetApy": float(head["avg_net_apy"] or 0),
            "avgNetApyExcludingRewards": float(
                head["avg_net_apy_excluding_rewards"] or 0
            ),
            "maxApy": float(head["max_apy"] or 0),
            "forceDeallocatableLiquidityUsd": float(
                head["force_deallocatable_liquidity_usd"] or 0
            ),
            "performanceFee": float(head["performance_fee"] or 0),
            "managementFee": float(head["management_fee"] or 0),
            "asset": {
                "address": _db_bytes_to_evm(head["asset_address"]),
                "symbol": head["asset_symbol"],
                "decimals": head["asset_decimals"],
            },
            # [V2_STATE_ADAPTERS_ADD] 新增：在原有输出上追加 adapters
            "adapters": {"items": adapters_items},
        }
    }


# api/morpho/vault/v2/state相关：回写 V2 当前表
async def _upsert_vault_v2_state_to_table(
    pool: AsyncpgPool, *, vault: dict[str, Any]
) -> None:
    vault_addr = str(vault.get("address") or "").strip()
    if not vault_addr:
        return
    asset = vault.get("asset") or {}
    # [V2_STATE_ADAPTERS_ADD] 修改：改为解析 adapters 并写入 adapters 当前表
    adapters = (vault.get("adapters") or {}).get("items") or []
    vault_addr_b = _evm_to_db_bytes(vault_addr)
    asset_addr_b = _evm_to_db_bytes(str(asset.get("address") or ZERO_ADDRESS))
    market_asset = None
    market_asset_usd = None
    if isinstance(adapters, list):
        for adapter in adapters:
            if not isinstance(adapter, dict):
                continue
            if str(adapter.get("type") or "") == "MorphoMarketV1":
                market_asset = adapter.get("assets")
                market_asset_usd = adapter.get("assetsUsd")
                break
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO loan.morpho_vault_v2_current (
                    vault_address, vault_name, asset_address, asset_symbol, asset_decimals,
                    total_assets_usd, idle_assets_usd, liquidity_usd, apy, net_apy,
                    net_apy_excluding_rewards, avg_net_apy, avg_net_apy_excluding_rewards,
                    max_apy, force_deallocatable_liquidity_usd, performance_fee, management_fee,
                    market_asset, market_asset_usd,
                    source_ts, updated_at
                )
                VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,NOW(),NOW()
                )
                ON CONFLICT (vault_address) DO UPDATE SET
                    vault_name = EXCLUDED.vault_name,
                    asset_address = EXCLUDED.asset_address,
                    asset_symbol = EXCLUDED.asset_symbol,
                    asset_decimals = EXCLUDED.asset_decimals,
                    total_assets_usd = EXCLUDED.total_assets_usd,
                    idle_assets_usd = EXCLUDED.idle_assets_usd,
                    liquidity_usd = EXCLUDED.liquidity_usd,
                    apy = EXCLUDED.apy,
                    net_apy = EXCLUDED.net_apy,
                    net_apy_excluding_rewards = EXCLUDED.net_apy_excluding_rewards,
                    avg_net_apy = EXCLUDED.avg_net_apy,
                    avg_net_apy_excluding_rewards = EXCLUDED.avg_net_apy_excluding_rewards,
                    max_apy = EXCLUDED.max_apy,
                    force_deallocatable_liquidity_usd = EXCLUDED.force_deallocatable_liquidity_usd,
                    performance_fee = EXCLUDED.performance_fee,
                    management_fee = EXCLUDED.management_fee,
                    market_asset = EXCLUDED.market_asset,
                    market_asset_usd = EXCLUDED.market_asset_usd,
                    source_ts = NOW(),
                    updated_at = NOW()
                """,
                vault_addr_b,
                vault.get("name"),
                asset_addr_b,
                asset.get("symbol"),
                asset.get("decimals"),
                vault.get("totalAssetsUsd"),
                vault.get("idleAssetsUsd"),
                vault.get("liquidityUsd"),
                vault.get("apy"),
                vault.get("netApy"),
                vault.get("netApyExcludingRewards"),
                vault.get("avgNetApy"),
                vault.get("avgNetApyExcludingRewards"),
                vault.get("maxApy"),
                vault.get("forceDeallocatableLiquidityUsd"),
                vault.get("performanceFee"),
                vault.get("managementFee"),
                market_asset,
                market_asset_usd,
            )
            await conn.execute(
                """
                DELETE FROM loan.morpho_vault_v2_adapters_current
                WHERE vault_address = $1
                """,
                vault_addr_b,
            )
            rows: list[tuple[Any, ...]] = []
            if isinstance(adapters, list):
                for adapter in adapters:
                    if not isinstance(adapter, dict):
                        continue
                    adapter_type = str(adapter.get("type") or "")
                    if adapter_type == "MetaMorpho":
                        pos = (
                            ((adapter.get("position") or {}).get("state") or {})
                            if isinstance(adapter.get("position"), dict)
                            else {}
                        )
                        adapter_id = _strip_chain_prefix(pos.get("address"))
                        adapter_assets = pos.get("assets")
                        adapter_assets_usd = pos.get("assetsUsd")
                        normalized_type = "v1"
                        if not adapter_id:
                            continue
                        rows.append(
                            (
                                vault_addr_b,
                                adapter_id,
                                adapter_assets,
                                adapter_assets_usd,
                                normalized_type,
                            )
                        )
                        continue
                    if adapter_type == "MorphoVaultV2":
                        adapter_id = str(
                            ((adapter.get("innerVault") or {}).get("address") or "")
                        )
                        normalized_type = "v2"
                        if not adapter_id:
                            continue
                        rows.append(
                            (
                                vault_addr_b,
                                adapter_id,
                                adapter.get("assets"),
                                adapter.get("assetsUsd"),
                                normalized_type,
                            )
                        )
                        continue
                    if adapter_type == "MorphoMarketV1":
                        normalized_type = "market"
                        positions = (
                            ((adapter.get("positions") or {}).get("items") or [])
                            if isinstance(adapter.get("positions"), dict)
                            else []
                        )
                        if isinstance(positions, list) and positions:
                            for p in positions:
                                if not isinstance(p, dict):
                                    continue
                                p_state = p.get("state") or {}
                                adapter_id = _strip_chain_prefix(p.get("market_id"))
                                if not adapter_id:
                                    continue
                                rows.append(
                                    (
                                        vault_addr_b,
                                        adapter_id,
                                        p_state.get("supplyAssets"),
                                        p_state.get("supplyAssetsUsd"),
                                        normalized_type,
                                    )
                                )
                            continue
                        # 无 positions 时，仍保留 adapter 级数据
                        fallback_id = str(adapter.get("id") or "market")
                        rows.append(
                            (
                                vault_addr_b,
                                fallback_id,
                                adapter.get("assets"),
                                adapter.get("assetsUsd"),
                                normalized_type,
                            )
                        )
                        continue
                    # 未知 type 兜底
                    fallback_id = str(adapter.get("id") or "")
                    if not fallback_id:
                        continue
                    rows.append(
                        (
                            vault_addr_b,
                            fallback_id,
                            adapter.get("assets"),
                            adapter.get("assetsUsd"),
                            "market",
                        )
                    )
            if rows:
                await conn.executemany(
                    """
                    INSERT INTO loan.morpho_vault_v2_adapters_current (
                        vault_address, id, assets, assets_usd, type, source_ts, updated_at
                    )
                    VALUES ($1,$2,$3,$4,$5,NOW(),NOW())
                    """,
                    rows,
                )


# api/morpho/markets相关：当链上查询失败时，从硬编码 pair 文本回退构造 assets
def _pair_to_assets(pair: str) -> list[MorphoMarketAssetItem]:
    loan_symbol, sep, collateral_symbol = pair.partition(" : ")
    if not sep:
        loan_symbol, sep, collateral_symbol = pair.partition("-")
    return [
        MorphoMarketAssetItem(
            asset=(loan_symbol or "").strip(),
            token_address="",
            role="loan",
        ),
        MorphoMarketAssetItem(
            asset=(collateral_symbol or "").strip(),
            token_address="",
            role="collateral",
        ),
    ]


# api/morpho/markets相关：批量查表获取市场缓存（loan.morpho_blue_current_markets）
async def _fetch_market_rows_from_table(
    pool: AsyncpgPool, market_ids: list[str]
) -> dict[str, dict[str, Any]]:
    if not market_ids:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                market_id,
                loan_symbol,
                loan_address,
                collateral_symbol,
                collateral_address,
                total_market_size_usd,
                total_supply_assets,
                total_borrow_assets
            FROM loan.morpho_blue_current_markets
            WHERE market_id = ANY($1::text[])
            """,
            market_ids,
        )
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        out[str(row["market_id"]).lower()] = dict(row)
    return out


# api/morpho/markets相关：将表记录转换为接口输出项（命中缓存时使用）
def _market_item_from_table_row(
    *,
    market_id: str,
    pair_fallback: str,
    row: dict[str, Any],
) -> MorphoMarketListItem:
    loan_symbol = (row.get("loan_symbol") or "").strip()
    loan_address = str(row.get("loan_address") or "").strip()
    collateral_symbol = (row.get("collateral_symbol") or "").strip()
    collateral_address = str(row.get("collateral_address") or "").strip()
    if loan_symbol and loan_address and collateral_symbol and collateral_address:
        assets = [
            MorphoMarketAssetItem(
                asset=loan_symbol,
                token_address=loan_address,
                role="loan",
            ),
            MorphoMarketAssetItem(
                asset=collateral_symbol,
                token_address=collateral_address,
                role="collateral",
            ),
        ]
    else:
        assets = _pair_to_assets(pair_fallback)

    size_raw = row.get("total_market_size_usd")
    size_usd = float(size_raw) if size_raw is not None else None

    util: float | None = None
    supply_raw = row.get("total_supply_assets")
    borrow_raw = row.get("total_borrow_assets")
    if supply_raw is not None and borrow_raw is not None:
        try:
            supply = Decimal(supply_raw)
            borrow = Decimal(borrow_raw)
            if supply > 0:
                util = float(borrow / supply)
        except (ArithmeticError, ValueError, TypeError):
            util = None

    return MorphoMarketListItem(
        market_id=market_id,
        dataSource="table",
        assets=assets,
        total_market_size_usd=size_usd,
        utilization=util,
    )


# api/morpho/market/state相关：GET /api/morpho/market/state 预留 date 参数格式校验
UTC_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_scaffold_status() -> MorphoScaffoldStatusResponse:
    return MorphoScaffoldStatusResponse(
        module=MORPHO_PROTOCOL,
        status="active",
        chain=MORPHO_CHAIN,
        supported_protocols=[MORPHO_DEFAULT_MARKET_TYPE],
        message=(
            "Morpho Blue realtime position query is available via RPC. "
            "Replay snapshots are populated lazily on API requests."
        ),
    )


# api/morpho/markets相关：GET /api/morpho/markets（分页 + Blue API 指标）
async def get_representative_markets_page(
    *,
    pool: AsyncpgPool,
    page: int,
    page_size: int,
    sort_by: str = "total_market_size_usd",
    sort_order: str = "desc",
    loan: str | None = None,
    collateral: str | None = None,
) -> MorphoMarketListResponse:
    if page < 1:
        raise HTTPException(status_code=400, detail="page 必须从 1 开始")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page_size 必须在 1~100 之间")
    # api/morpho/markets相关：排序字段白名单，防止拼接 SQL 注入
    sort_key = sort_by.strip().lower()
    sort_map = {
        "total_market_size_usd": "m.total_market_size_usd",
        "utilization": (
            "CASE "
            "WHEN m.total_supply_assets IS NULL OR m.total_supply_assets = 0 THEN NULL "
            "ELSE (m.total_borrow_assets / m.total_supply_assets) "
            "END"
        ),
        "loan_symbol": "m.loan_symbol",
        "collateral_symbol": "m.collateral_symbol",
    }
    order_key = sort_order.strip().lower()
    if sort_key not in sort_map:
        raise HTTPException(
            status_code=400,
            detail=(
                "sort_by 仅支持：total_market_size_usd, utilization, "
                "loan_symbol, collateral_symbol"
            ),
        )
    if order_key not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="sort_order 仅支持：asc 或 desc")

    order_column = sort_map[sort_key]
    order_direction = "ASC" if order_key == "asc" else "DESC"
    offset = (page - 1) * page_size
    loan_filter = loan.strip() if loan else ""
    collateral_filter = collateral.strip() if collateral else ""

    # api/morpho/markets相关：可选过滤条件（0x 开头按地址，否则走共享映射字典转地址）
    where_parts = ["m.is_active = TRUE"]
    args: list[Any] = []
    if loan_filter:
        if loan_filter.lower().startswith("0x"):
            where_parts.append(f"lower(m.loan_address) = lower(${len(args) + 1})")
            args.append(loan_filter)
        else:
            mapped = _resolve_ethereum_token_address(loan_filter)
            if not mapped:
                where_parts.append("1 = 0")
            else:
                where_parts.append(f"lower(m.loan_address) = lower(${len(args) + 1})")
                args.append(mapped)
    if collateral_filter:
        if collateral_filter.lower().startswith("0x"):
            where_parts.append(f"lower(m.collateral_address) = lower(${len(args) + 1})")
            args.append(collateral_filter)
        else:
            mapped = _resolve_ethereum_token_address(collateral_filter)
            if not mapped:
                where_parts.append("1 = 0")
            else:
                where_parts.append(
                    f"lower(m.collateral_address) = lower(${len(args) + 1})"
                )
                args.append(mapped)
    where_sql = " AND ".join(where_parts)

    async with pool.acquire() as conn:
        total_query = f"""
            SELECT COUNT(*)
            FROM loan.morpho_blue_current_markets AS m
            WHERE {where_sql}
        """
        total = int(await conn.fetchval(total_query, *args))
        rows = await conn.fetch(
            f"""
            SELECT
                market_id,
                loan_symbol,
                loan_address,
                collateral_symbol,
                collateral_address,
                total_market_size_usd,
                total_supply_assets,
                total_borrow_assets
            FROM loan.morpho_blue_current_markets AS m
            WHERE {where_sql}
            ORDER BY {order_column} {order_direction} NULLS LAST, market_id ASC
            OFFSET ${len(args) + 1}
            LIMIT ${len(args) + 2}
            """,
            *args,
            offset,
            page_size,
        )

    total_pages = max(1, (total + page_size - 1) // page_size)
    items: list[MorphoMarketListItem] = []
    for row in rows:
        items.append(
            _market_item_from_table_row(
                market_id=str(row["market_id"]),
                pair_fallback="",
                row=dict(row),
            )
        )

    return MorphoMarketListResponse(
        page=page,
        page_size=page_size,
        total_count=total,
        total_pages=total_pages,
        markets=items,
    )


# api/morpho/market/state相关：GET /api/morpho/market/state
async def _fetch_market_state_row_from_table(
    pool: AsyncpgPool, market_id: str
) -> dict[str, Any] | None:
    market_key = _normalize_market_id_text(market_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                market_id,
                loan_symbol,
                loan_address,
                loan_decimals,
                collateral_symbol,
                collateral_address,
                collateral_decimals,
                oracle,
                irm,
                lltv_raw,
                total_supply_assets,
                total_supply_shares,
                total_borrow_assets,
                total_borrow_shares,
                last_update,
                fee_raw,
                total_market_size_usd
            FROM loan.morpho_blue_current_markets
            WHERE market_id = $1 AND is_active = TRUE
            LIMIT 1
            """,
            market_key,
        )
    return dict(row) if row else None


# api/morpho/market/state相关：表命中时由缓存原始字段组装 market/state 响应
async def _build_market_state_payload_from_table(
    w3: AsyncWeb3, *, market_id: str, row: dict[str, Any]
) -> dict[str, Any]:
    loan_address = _normalize_evm_address(str(row.get("loan_address") or ""))
    collateral_address = _normalize_evm_address(
        str(row.get("collateral_address") or "")
    )
    oracle_address = _normalize_evm_address(str(row.get("oracle") or ZERO_ADDRESS))
    irm_address = _normalize_evm_address(str(row.get("irm") or ZERO_ADDRESS))
    loan_decimals = int(row.get("loan_decimals") or 0)
    collateral_decimals = int(row.get("collateral_decimals") or 0)
    lltv_raw = int(row.get("lltv_raw") or 0)
    total_supply_assets = int(row.get("total_supply_assets") or 0)
    total_supply_shares = int(row.get("total_supply_shares") or 0)
    total_borrow_assets = int(row.get("total_borrow_assets") or 0)
    total_borrow_shares = int(row.get("total_borrow_shares") or 0)
    last_update = int(row.get("last_update") or 0)
    fee = int(row.get("fee_raw") or 0)
    total_market_size_usd_raw = row.get("total_market_size_usd")
    total_market_size_usd = (
        float(total_market_size_usd_raw)
        if total_market_size_usd_raw is not None
        else None
    )

    supply_dec = Decimal(total_supply_assets)
    borrow_dec = Decimal(total_borrow_assets)
    lltv_ratio = Decimal(lltv_raw) / Decimal(WAD) if lltv_raw else Decimal("0")
    utilization = Decimal("0")
    if total_supply_assets > 0:
        utilization = borrow_dec / supply_dec
    available_liquidity = total_supply_assets - total_borrow_assets

    borrow_capacity_usage_rough = Decimal("0")
    if total_supply_assets > 0 and lltv_ratio > 0:
        borrow_capacity_usage_rough = borrow_dec / (supply_dec * lltv_ratio)

    seconds_per_year = 365 * 24 * 60 * 60
    annual_borrow_rate = Decimal("0")
    annual_interest_ratio = Decimal("0")
    annual_supply_rate = Decimal("0")
    annual_supply_interest_ratio = Decimal("0")
    if irm_address != ZERO_ADDRESS:
        irm = w3.eth.contract(
            address=cast(ChecksumAddress, irm_address),
            abi=IRM_ABI,
        )
        market_params_tuple = (
            loan_address,
            collateral_address,
            oracle_address,
            irm_address,
            lltv_raw,
        )
        market_tuple = (
            total_supply_assets,
            total_supply_shares,
            total_borrow_assets,
            total_borrow_shares,
            last_update,
            fee,
        )
        borrow_rate = int(
            await irm.functions.borrowRateView(market_params_tuple, market_tuple).call()
        )
        annual_borrow_rate = (
            Decimal(borrow_rate) * Decimal(seconds_per_year) / Decimal(WAD)
        )
        annual_interest_ratio = Decimal(
            _w_taylor_compounded(borrow_rate, seconds_per_year)
        ) / Decimal(WAD)
        supply_rate = 0
        if total_supply_assets > 0:
            utilization_wad = _mul_div_down(
                total_borrow_assets, WAD, total_supply_assets
            )
            net_supply_rate_wad = _mul_div_down(
                _mul_div_down(borrow_rate, utilization_wad, WAD),
                WAD - fee,
                WAD,
            )
            supply_rate = max(net_supply_rate_wad, 0)
        annual_supply_rate = (
            Decimal(supply_rate) * Decimal(seconds_per_year) / Decimal(WAD)
        )
        annual_supply_interest_ratio = Decimal(
            _w_taylor_compounded(supply_rate, seconds_per_year)
        ) / Decimal(WAD)

    market_id_hex = _normalize_market_id_text(market_id)
    return {
        "marketId": market_id_hex,
        "dataSource": "table",
        "total_market_size_usd": total_market_size_usd,
        "loanToken": {
            "address": loan_address,
            "symbol": row.get("loan_symbol"),
            "decimals": loan_decimals,
        },
        "collateralToken": {
            "address": collateral_address,
            "symbol": row.get("collateral_symbol"),
            "decimals": collateral_decimals,
        },
        "oracle": oracle_address,
        "irm": irm_address,
        "lltv": {
            "raw": str(lltv_raw),
            "ratio": _format_decimal_fixed(lltv_ratio, 6),
        },
        "totalSupplyAssets": str(total_supply_assets),
        "totalSupplyShares": str(total_supply_shares),
        "totalBorrowAssets": str(total_borrow_assets),
        "totalBorrowShares": str(total_borrow_shares),
        "lastUpdate": last_update,
        "fee": str(fee),
        "utilization": {
            "formula": "totalBorrowAssets / totalSupplyAssets",
            "value": _format_decimal_fixed(utilization, 8),
        },
        "availableLiquidity": {
            "formula": "totalSupplyAssets - totalBorrowAssets",
            "value": str(available_liquidity),
            "note": None,
        },
        "borrowCapacityUsageRough": {
            "formula": "totalBorrowAssets / (totalSupplyAssets * lltv)",
            "value": _format_decimal_fixed(borrow_capacity_usage_rough, 8),
            "note": "市场层粗略估算，严格口径需用户仓位级数据",
        },
        "annualBorrowRate": {
            "formula": "borrowRatePerSecond * secondsPerYear",
            "value": _format_decimal_fixed(annual_borrow_rate, 8),
            "note": "基于 IRM borrowRateView 的线性年化（单利近似）",
        },
        "annualBorrowInterestRatio": {
            "formula": "wTaylorCompounded(borrowRatePerSecond, secondsPerYear)",
            "value": _format_decimal_fixed(annual_interest_ratio, 8),
            "note": "基于当前利率估算的一年利息/本金比例",
        },
        "annualSupplyRate": {
            "formula": "borrowRatePerSecond * utilization * (1 - fee) * secondsPerYear",
            "value": _format_decimal_fixed(annual_supply_rate, 8),
            "note": "出借侧线性年化（市场层估算，已扣除协议费）",
        },
        "annualSupplyInterestRatio": {
            "formula": "wTaylorCompounded(borrowRatePerSecond * utilization * (1 - fee), secondsPerYear)",
            "value": _format_decimal_fixed(annual_supply_interest_ratio, 8),
            "note": "出借侧复利年化（市场层估算，已扣除协议费）",
        },
        "marketScaleTvlLike": {
            "formula": "totalSupplyAssets",
            "value": str(total_supply_assets),
            "note": None,
        },
        "debtScaleDebtLike": {
            "formula": "totalBorrowAssets",
            "value": str(total_borrow_assets),
            "note": None,
        },
    }


# api/morpho/market/state相关：GET /api/morpho/market/state
async def _estimate_total_market_size_usd_from_price(
    w3: AsyncWeb3, payload: dict[str, Any]
) -> float | None:
    loan_token = payload.get("loanToken") or {}
    loan_address = str(loan_token.get("address") or "").strip()
    loan_decimals = int(loan_token.get("decimals") or 0)
    total_supply_assets_raw = payload.get("totalSupplyAssets")
    if not loan_address or total_supply_assets_raw is None:
        return None

    try:
        price = await get_price(
            w3,
            symbol=None,
            address=loan_address,
            pool=None,
            chain=MORPHO_CHAIN,
            timestamp=None,
        )
        price_usd = Decimal(price.price_usd)
        amount = Decimal(str(total_supply_assets_raw)) / (Decimal(10) ** loan_decimals)
        return float(amount * price_usd)
    except Exception:
        return None


# api/morpho/market/state相关：GET /api/morpho/market/state
async def get_market_state(
    w3: AsyncWeb3,
    *,
    pool: AsyncpgPool,
    market_id: str,
    date: str | None = None,
) -> MorphoMarketStateResponse:
    if date:
        if not UTC_DAY_RE.match(date):
            raise HTTPException(
                status_code=400,
                detail="date 格式错误，需为 UTC 天级格式：YYYY-MM-DD（例如 2026-04-05）",
            )
        raise HTTPException(
            status_code=400,
            detail="date 参数已预留（UTC 天级），当前 MVP 暂不支持历史查询",
        )
    row = await _fetch_market_state_row_from_table(pool, market_id)
    if row is not None:
        payload = await _build_market_state_payload_from_table(
            w3,
            market_id=market_id,
            row=row,
        )
        return MorphoMarketStateResponse(**payload)

    payload = await fetch_market_state(w3, market_id=market_id)
    # api/morpho/market/state相关：查表未命中，链上查询返回
    payload["dataSource"] = "chain"
    payload["total_market_size_usd"] = await _estimate_total_market_size_usd_from_price(
        w3, payload
    )
    # api/morpho/market/state相关：查表未命中时将链上结果回写 loan.morpho_blue_current_markets
    await _upsert_market_state_row_to_table(pool, payload=payload)
    return MorphoMarketStateResponse(**payload)


# api/morpho/market/state相关：链上 market/state 结果回写当前市场缓存表
async def _upsert_market_state_row_to_table(
    pool: AsyncpgPool, *, payload: dict[str, Any]
) -> None:
    market_id = _normalize_market_id_text(str(payload.get("marketId") or ""))
    if not market_id:
        return

    loan_token = payload.get("loanToken") or {}
    collateral_token = payload.get("collateralToken") or {}
    loan_address = str(loan_token.get("address") or "").strip()
    if not loan_address:
        return
    collateral_address = str(collateral_token.get("address") or "").strip() or None
    total_market_size_usd = payload.get("total_market_size_usd")
    total_market_size_usd_dec: Decimal | None = None
    if total_market_size_usd is not None:
        try:
            total_market_size_usd_dec = Decimal(str(total_market_size_usd))
        except Exception:
            total_market_size_usd_dec = None

    lltv = payload.get("lltv") or {}
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO loan.morpho_blue_current_markets (
                market_id,
                loan_symbol,
                loan_address,
                loan_decimals,
                collateral_symbol,
                collateral_address,
                collateral_decimals,
                oracle,
                irm,
                lltv_raw,
                total_supply_assets,
                total_supply_shares,
                total_borrow_assets,
                total_borrow_shares,
                last_update,
                fee_raw,
                total_market_size_usd,
                source,
                is_active,
                updated_at
            )
            VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,
                $10,$11,$12,$13,$14,$15,$16,$17,$18,TRUE,NOW()
            )
            ON CONFLICT (market_id) DO UPDATE SET
                loan_symbol = EXCLUDED.loan_symbol,
                loan_address = EXCLUDED.loan_address,
                loan_decimals = EXCLUDED.loan_decimals,
                collateral_symbol = EXCLUDED.collateral_symbol,
                collateral_address = EXCLUDED.collateral_address,
                collateral_decimals = EXCLUDED.collateral_decimals,
                oracle = EXCLUDED.oracle,
                irm = EXCLUDED.irm,
                lltv_raw = EXCLUDED.lltv_raw,
                total_supply_assets = EXCLUDED.total_supply_assets,
                total_supply_shares = EXCLUDED.total_supply_shares,
                total_borrow_assets = EXCLUDED.total_borrow_assets,
                total_borrow_shares = EXCLUDED.total_borrow_shares,
                last_update = EXCLUDED.last_update,
                fee_raw = EXCLUDED.fee_raw,
                total_market_size_usd = EXCLUDED.total_market_size_usd,
                source = EXCLUDED.source,
                is_active = TRUE,
                updated_at = NOW()
            """,
            market_id,
            loan_token.get("symbol"),
            loan_address,
            int(loan_token.get("decimals") or 0),
            collateral_token.get("symbol"),
            collateral_address,
            int(collateral_token.get("decimals") or 0),
            str(payload.get("oracle") or ZERO_ADDRESS),
            str(payload.get("irm") or ZERO_ADDRESS),
            Decimal(str(lltv.get("raw") or 0)),
            Decimal(str(payload.get("totalSupplyAssets") or 0)),
            Decimal(str(payload.get("totalSupplyShares") or 0)),
            Decimal(str(payload.get("totalBorrowAssets") or 0)),
            Decimal(str(payload.get("totalBorrowShares") or 0)),
            int(payload.get("lastUpdate") or 0),
            Decimal(str(payload.get("fee") or 0)),
            total_market_size_usd_dec,
            "api-market-state-chain",
        )


def parse_utc_time(value: str) -> int:
    text = value.strip()
    if not text:
        raise HTTPException(status_code=400, detail="时间不能为空")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid UTC datetime: {value}"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp())


def _record_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _format_ratio(value: Decimal, scale: str = "0.000000000000000001") -> str:
    return format(value.quantize(Decimal(scale)), "f")


def _format_scaled(raw: int, decimals: int) -> str:
    return format(Decimal(raw) / (Decimal(10) ** decimals), "f")


def _format_oracle_price(
    raw: int,
    *,
    loan_decimals: int,
    collateral_decimals: int,
) -> str:
    scale = Decimal(10) ** (36 + loan_decimals - collateral_decimals)
    return format(Decimal(raw) / scale, "f")


def _format_brief_amount(amount: Decimal) -> str:
    text = format(amount.quantize(Decimal("0.01")).normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _format_brief_usd(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _normalize_market_id_text(market_id: str) -> str:
    value = market_id.strip().lower()
    if not value.startswith("0x"):
        value = f"0x{value}"
    return value


def _evm_to_db_bytes(address: str) -> bytes:
    try:
        checksum = AsyncWeb3.to_checksum_address(address)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid EVM address") from exc
    return bytes.fromhex(checksum[2:])


def _normalize_evm_address(address: str) -> str:
    try:
        return AsyncWeb3.to_checksum_address(address)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid EVM address") from exc


def _db_bytes_to_evm(value: bytes | bytearray | memoryview | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raw = bytes(value)
    if len(raw) == 20:
        return AsyncWeb3.to_checksum_address(f"0x{raw.hex()}")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"0x{raw.hex()}"
    if decoded.startswith("0x"):
        return AsyncWeb3.to_checksum_address(decoded)
    return decoded


def _parse_extra_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return json.loads(bytes(value).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_assets_json(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            payload = json.loads(bytes(value).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return []
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [item for item in payload if isinstance(item, dict)]
    return []


def _format_health(value: Decimal | None, *, borrow_assets: Decimal) -> str | None:
    if value is None:
        return None
    if borrow_assets <= 0 and value == 0:
        return None
    return _format_ratio(value)


def _build_asset_responses(
    assets: list[dict[str, Any]],
) -> list[MorphoPositionAssetResponse]:
    return [
        MorphoPositionAssetResponse(
            role=str(asset.get("side") or ""),
            token_address=_db_bytes_to_evm(asset.get("asset_address")),
            symbol=asset.get("symbol"),
            decimals=int(asset.get("decimals") or 18),
            amount=str(asset.get("amount") or "0"),
            price_usd=(
                None if asset.get("price_usd") is None else str(asset.get("price_usd"))
            ),
            value_usd=(
                None if asset.get("value_usd") is None else str(asset.get("value_usd"))
            ),
        )
        for asset in assets
    ]


async def _get_asset_price_usd(
    w3: AsyncWeb3,
    *,
    pool: AsyncpgPool,
    token_address: str,
    timestamp: int | None,
    cache: dict[tuple[str, int | None], Decimal | None],
) -> Decimal | None:
    cache_key = (token_address.lower(), timestamp)
    if cache_key in cache:
        return cache[cache_key]
    try:
        if timestamp is not None:
            price, _, _ = await get_historical_price_usd(
                pool,
                token_address=token_address,
                asset_label=token_address,
                requested_ts=timestamp,
            )
            cache[cache_key] = price
            return price
        result = await get_price(
            w3,
            symbol=None,
            address=token_address,
            pool=pool,
            timestamp=None,
        )
    except HTTPException:
        cache[cache_key] = None
        return None
    price = Decimal(str(result.price_usd))
    cache[cache_key] = price
    return price


async def _enrich_position_assets_with_prices(
    w3: AsyncWeb3,
    *,
    pool: AsyncpgPool,
    response: MorphoPositionResponse,
    timestamp: int | None,
    cache: dict[tuple[str, int | None], Decimal | None],
) -> None:
    loan_price_usd: Decimal | None = None
    collateral_price_usd: Decimal | None = None
    if timestamp is not None:
        try:
            prices, _, _ = await get_historical_prices_usd(
                pool,
                assets=[
                    (
                        response.loan_token,
                        response.loan_token_symbol or response.loan_token,
                    ),
                    (
                        response.collateral_token,
                        response.collateral_token_symbol or response.collateral_token,
                    ),
                ],
                requested_ts=timestamp,
            )
            loan_price_usd = prices.get(response.loan_token.lower())
            collateral_price_usd = prices.get(response.collateral_token.lower())
            cache[(response.loan_token.lower(), timestamp)] = loan_price_usd
            cache[(response.collateral_token.lower(), timestamp)] = collateral_price_usd
        except HTTPException:
            loan_price_usd = await _get_asset_price_usd(
                w3,
                pool=pool,
                token_address=response.loan_token,
                timestamp=timestamp,
                cache=cache,
            )
            collateral_price_usd = await _get_asset_price_usd(
                w3,
                pool=pool,
                token_address=response.collateral_token,
                timestamp=timestamp,
                cache=cache,
            )
    else:
        loan_price_usd = await _get_asset_price_usd(
            w3,
            pool=pool,
            token_address=response.loan_token,
            timestamp=timestamp,
            cache=cache,
        )
        collateral_price_usd = await _get_asset_price_usd(
            w3,
            pool=pool,
            token_address=response.collateral_token,
            timestamp=timestamp,
            cache=cache,
        )
    for asset in response.assets:
        price_usd = (
            collateral_price_usd if asset.role == "collateral" else loan_price_usd
        )
        amount = Decimal(str(asset.amount or "0"))
        asset.price_usd = None if price_usd is None else str(price_usd)
        asset.value_usd = None if price_usd is None else str(amount * price_usd)


def _build_response_from_rpc(
    position: MorphoRealtimePosition,
    *,
    data_source: str,
) -> MorphoPositionResponse:
    collateral_value = _format_scaled(
        position.collateral_value_in_loan_asset_raw,
        position.loan_token.decimals,
    )
    borrow_assets = _format_scaled(
        position.borrow_assets_raw,
        position.loan_token.decimals,
    )
    collateral_assets = _format_scaled(
        position.collateral_raw,
        position.collateral_token.decimals,
    )
    return MorphoPositionResponse(
        protocol=MORPHO_PROTOCOL,
        market_type=MORPHO_DEFAULT_MARKET_TYPE,
        chain=MORPHO_CHAIN,
        morpho_address=MORPHO_BLUE_ADDRESS,
        market_id=position.market_id,
        address=position.user_address,
        block_number=position.block_number,
        block_timestamp=_record_ts(position.block_timestamp),
        has_position=position.has_position,
        is_healthy=position.is_healthy,
        loan_token=position.loan_token.address,
        loan_token_symbol=position.loan_token.symbol,
        loan_token_decimals=position.loan_token.decimals,
        collateral_token=position.collateral_token.address,
        collateral_token_symbol=position.collateral_token.symbol,
        collateral_token_decimals=position.collateral_token.decimals,
        oracle=position.oracle,
        irm=position.irm,
        lltv=str(position.lltv),
        lltv_ratio=_format_ratio(Decimal(position.lltv) / Decimal(10**18), "0.000000"),
        supply_shares=str(position.supply_shares),
        borrow_shares=str(position.borrow_shares),
        collateral_assets_raw=str(position.collateral_raw),
        supply_assets=_format_scaled(
            position.supply_assets_raw, position.loan_token.decimals
        ),
        borrow_assets=borrow_assets,
        collateral_assets=collateral_assets,
        collateral_value_in_loan_asset=collateral_value,
        max_borrowable_in_loan_asset=_format_scaled(
            position.max_borrowable_raw,
            position.loan_token.decimals,
        ),
        health_factor=_format_health(
            position.health_factor,
            borrow_assets=Decimal(borrow_assets),
        ),
        price_quote=_format_oracle_price(
            position.price_raw,
            loan_decimals=position.loan_token.decimals,
            collateral_decimals=position.collateral_token.decimals,
        ),
        data_source=data_source,
        assets=[
            MorphoPositionAssetResponse(
                role="loan",
                token_address=position.loan_token.address,
                symbol=position.loan_token.symbol,
                decimals=position.loan_token.decimals,
                amount=_format_scaled(
                    position.supply_assets_raw - position.borrow_assets_raw,
                    position.loan_token.decimals,
                ),
                price_usd=None,
                value_usd=None,
            ),
            MorphoPositionAssetResponse(
                role="collateral",
                token_address=position.collateral_token.address,
                symbol=position.collateral_token.symbol,
                decimals=position.collateral_token.decimals,
                amount=collateral_assets,
                price_usd=None,
                value_usd=None,
            ),
        ],
    )


def _build_response_from_db(
    position_row: Any, asset_rows: list[Any]
) -> MorphoPositionResponse | None:
    extra = _parse_extra_json(position_row.get("extra_jsonb"))
    loan_token = extra.get("loan_token")
    collateral_token = extra.get("collateral_token")
    if not isinstance(loan_token, dict) or not isinstance(collateral_token, dict):
        return None

    block_ts = position_row.get("block_timestamp")
    if block_ts is None:
        return None

    borrow_assets = Decimal(str(extra.get("borrow_assets") or "0"))
    health_factor_raw = position_row.get("health_factor")
    has_position = (
        Decimal(position_row.get("supply_shares") or "0")
        + Decimal(position_row.get("borrow_shares") or "0")
        + Decimal(position_row.get("collateral_amount") or "0")
    ) > 0

    return MorphoPositionResponse(
        protocol=str(position_row.get("protocol") or MORPHO_PROTOCOL),
        market_type=str(position_row.get("market_type") or MORPHO_DEFAULT_MARKET_TYPE),
        chain=str(position_row.get("chain") or MORPHO_CHAIN),
        morpho_address=str(extra.get("morpho_address") or MORPHO_BLUE_ADDRESS),
        market_id=str(position_row.get("market_id")),
        address=_db_bytes_to_evm(position_row.get("user_address")),
        block_number=int(position_row.get("block_number") or 0),
        block_timestamp=_record_ts(block_ts),
        has_position=has_position,
        is_healthy=bool(extra.get("is_healthy", True)),
        loan_token=str(loan_token.get("address") or ""),
        loan_token_symbol=loan_token.get("symbol"),
        loan_token_decimals=int(loan_token.get("decimals") or 18),
        collateral_token=str(collateral_token.get("address") or ""),
        collateral_token_symbol=collateral_token.get("symbol"),
        collateral_token_decimals=int(collateral_token.get("decimals") or 18),
        oracle=str(extra.get("oracle") or ""),
        irm=str(extra.get("irm") or ""),
        lltv=str(extra.get("lltv") or "0"),
        lltv_ratio=str(extra.get("lltv_ratio") or "0"),
        supply_shares=str(
            extra.get("supply_shares_raw") or position_row.get("supply_shares") or "0"
        ),
        borrow_shares=str(
            extra.get("borrow_shares_raw") or position_row.get("borrow_shares") or "0"
        ),
        collateral_assets_raw=str(
            extra.get("collateral_assets_raw")
            or position_row.get("collateral_amount")
            or "0"
        ),
        supply_assets=str(extra.get("supply_assets") or "0"),
        borrow_assets=str(extra.get("borrow_assets") or "0"),
        collateral_assets=str(extra.get("collateral_assets") or "0"),
        collateral_value_in_loan_asset=str(
            extra.get("collateral_value_in_loan_asset") or "0"
        ),
        max_borrowable_in_loan_asset=str(
            extra.get("max_borrowable_in_loan_asset") or "0"
        ),
        health_factor=_format_health(
            None
            if extra.get("health_factor") is None
            and Decimal(health_factor_raw or "0") == 0
            else Decimal(str(extra.get("health_factor") or health_factor_raw or "0")),
            borrow_assets=borrow_assets,
        ),
        price_quote=str(extra.get("price_quote") or "0"),
        data_source="db",
        assets=_build_asset_responses(
            [
                {
                    "side": asset.get("side"),
                    "asset_address": asset.get("asset_address"),
                    "symbol": asset.get("symbol"),
                    "decimals": asset.get("decimals"),
                    "amount": asset.get("amount"),
                    "price_usd": asset.get("price_usd"),
                    "value_usd": asset.get("value_usd"),
                }
                for asset in asset_rows
            ]
        ),
    )


async def _upsert_market_from_position(
    pool: AsyncpgPool,
    *,
    position: MorphoRealtimePosition,
) -> None:
    await upsert_market(
        pool,
        market_id=position.market_id,
        chain=MORPHO_CHAIN,
        protocol=MORPHO_PROTOCOL,
        market_type=MORPHO_DEFAULT_MARKET_TYPE,
        loan_token_address=_evm_to_db_bytes(position.loan_token.address),
        collateral_token_address=_evm_to_db_bytes(position.collateral_token.address),
        oracle_address=_evm_to_db_bytes(position.oracle),
        irm_address=_evm_to_db_bytes(position.irm),
        lltv=Decimal(position.lltv) / Decimal(10**18),
        extra_jsonb={"oracle": position.oracle, "irm": position.irm},
    )


async def _cache_current_position(
    pool: AsyncpgPool,
    *,
    position: MorphoRealtimePosition,
    response: MorphoPositionResponse,
) -> None:
    await upsert_current_user_position(
        pool,
        market_id=position.market_id,
        user_address=_evm_to_db_bytes(position.user_address),
        chain=MORPHO_CHAIN,
        protocol=MORPHO_PROTOCOL,
        market_type=MORPHO_DEFAULT_MARKET_TYPE,
        snapshot_at=position.block_timestamp,
        block_timestamp=position.block_timestamp,
        block_number=position.block_number,
        supply_shares=Decimal(position.supply_shares) / Decimal(10**18),
        borrow_shares=Decimal(position.borrow_shares) / Decimal(10**18),
        collateral_amount=Decimal(response.collateral_assets),
        collateral_usd=Decimal("0"),
        debt_usd=Decimal("0"),
        health_factor=position.health_factor or Decimal("0"),
        extra_jsonb={
            "morpho_address": position.morpho_address,
            "oracle": position.oracle,
            "irm": position.irm,
            "lltv": str(position.lltv),
            "lltv_ratio": response.lltv_ratio,
            "loan_token": {
                "address": position.loan_token.address,
                "symbol": position.loan_token.symbol,
                "decimals": position.loan_token.decimals,
            },
            "collateral_token": {
                "address": position.collateral_token.address,
                "symbol": position.collateral_token.symbol,
                "decimals": position.collateral_token.decimals,
            },
            "supply_assets": response.supply_assets,
            "borrow_assets": response.borrow_assets,
            "collateral_assets": response.collateral_assets,
            "collateral_value_in_loan_asset": response.collateral_value_in_loan_asset,
            "max_borrowable_in_loan_asset": response.max_borrowable_in_loan_asset,
            "health_factor": response.health_factor,
            "price_quote": response.price_quote,
            "is_healthy": response.is_healthy,
            "supply_shares_raw": str(position.supply_shares),
            "borrow_shares_raw": str(position.borrow_shares),
            "collateral_assets_raw": str(position.collateral_raw),
        },
        assets=[
            {
                "asset_address": _evm_to_db_bytes(position.loan_token.address),
                "side": "loan",
                "symbol": position.loan_token.symbol,
                "decimals": position.loan_token.decimals,
                "amount": Decimal(response.supply_assets)
                - Decimal(response.borrow_assets),
                "price_usd": Decimal("0"),
                "value_usd": Decimal("0"),
                "extra_jsonb": {},
            },
            {
                "asset_address": _evm_to_db_bytes(position.collateral_token.address),
                "side": "collateral",
                "symbol": position.collateral_token.symbol,
                "decimals": position.collateral_token.decimals,
                "amount": Decimal(response.collateral_assets),
                "price_usd": Decimal("0"),
                "value_usd": Decimal("0"),
                "extra_jsonb": {},
            },
        ],
    )


def _build_single_event_brief(
    event: MorphoReplayEvent,
    *,
    loan_symbol: str | None,
    collateral_symbol: str | None,
    loan_decimals: int,
    collateral_decimals: int,
    loan_price_usd: Decimal | None,
    collateral_price_usd: Decimal | None,
) -> str:
    label = BRIEF_LABELS.get(event.operation_type, "更新仓位")
    if event.operation_type in {"supply", "withdraw", "borrow", "repay"}:
        amount = Decimal(event.assets or 0) / (Decimal(10) ** loan_decimals)
        value_suffix = ""
        if loan_price_usd is not None and loan_price_usd > 0:
            value_suffix = f" (价值 {_format_brief_usd(amount * loan_price_usd)} usd)"
        if loan_symbol:
            return f"{label} {_format_brief_amount(amount)} {loan_symbol}{value_suffix}"
        return label
    if event.operation_type in {"supply_collateral", "withdraw_collateral"}:
        amount = Decimal(event.collateral_assets or 0) / (
            Decimal(10) ** collateral_decimals
        )
        value_suffix = ""
        if collateral_price_usd is not None and collateral_price_usd > 0:
            value_suffix = (
                f" (价值 {_format_brief_usd(amount * collateral_price_usd)} usd)"
            )
        if collateral_symbol:
            return f"{label} {_format_brief_amount(amount)} {collateral_symbol}{value_suffix}"
        return label
    if event.operation_type == "liquidation":
        parts: list[str] = []
        if event.seized_assets:
            amount = Decimal(event.seized_assets) / (Decimal(10) ** collateral_decimals)
            if collateral_symbol:
                part = f"扣押 {_format_brief_amount(amount)} {collateral_symbol}"
                if collateral_price_usd is not None and collateral_price_usd > 0:
                    part += f" (价值 {_format_brief_usd(amount * collateral_price_usd)} usd)"
                parts.append(part)
        if event.repaid_assets:
            amount = Decimal(event.repaid_assets) / (Decimal(10) ** loan_decimals)
            if loan_symbol:
                part = f"偿还 {_format_brief_amount(amount)} {loan_symbol}"
                if loan_price_usd is not None and loan_price_usd > 0:
                    part += f" (价值 {_format_brief_usd(amount * loan_price_usd)} usd)"
                parts.append(part)
        if parts:
            return f"{label}," + "，".join(parts)
        return label
    return label


def _build_group_brief(
    events: list[MorphoReplayEvent],
    *,
    loan_symbol: str | None,
    collateral_symbol: str | None,
    loan_decimals: int,
    collateral_decimals: int,
    loan_price_usd: Decimal | None,
    collateral_price_usd: Decimal | None,
) -> tuple[str | None, str]:
    operations: list[str] = []
    briefs: list[str] = []
    for event in events:
        operations.append(event.operation_type)
        briefs.append(
            _build_single_event_brief(
                event,
                loan_symbol=loan_symbol,
                collateral_symbol=collateral_symbol,
                loan_decimals=loan_decimals,
                collateral_decimals=collateral_decimals,
                loan_price_usd=loan_price_usd,
                collateral_price_usd=collateral_price_usd,
            )
        )
    deduped_briefs: list[str] = []
    for brief in briefs:
        if brief not in deduped_briefs:
            deduped_briefs.append(brief)
    operation_type = operations[0] if len(set(operations)) == 1 else "batch"
    return operation_type, "；".join(deduped_briefs)


def _build_replay_snapshot_row(
    *,
    position: MorphoRealtimePosition,
    response: MorphoPositionResponse,
    tx_hash: str,
    operation_type: str | None,
    brief: str,
) -> dict[str, Any]:
    borrow_assets = Decimal(response.borrow_assets)
    health_factor = (
        Decimal(response.health_factor)
        if response.health_factor is not None
        else Decimal("0")
    )
    assets_jsonb = [
        {
            "side": asset.role,
            "asset_address": asset.token_address,
            "symbol": asset.symbol,
            "decimals": asset.decimals,
            "amount": asset.amount,
            "price_usd": asset.price_usd,
            "value_usd": asset.value_usd,
        }
        for asset in response.assets
    ]
    return {
        "market_id": position.market_id,
        "user_address": _evm_to_db_bytes(position.user_address),
        "chain": MORPHO_CHAIN,
        "protocol": MORPHO_PROTOCOL,
        "market_type": MORPHO_DEFAULT_MARKET_TYPE,
        "tx_hash": tx_hash,
        "block_number": position.block_number,
        "block_timestamp": position.block_timestamp,
        "operation_type": operation_type,
        "has_position": response.has_position,
        "is_healthy": response.is_healthy,
        "collateral_value_in_loan_asset": Decimal(
            response.collateral_value_in_loan_asset
        ),
        "borrow_assets": borrow_assets,
        "health_factor": health_factor,
        "assets_jsonb": assets_jsonb,
        "extra_jsonb": {
            "loan_token": {
                "address": response.loan_token,
                "symbol": response.loan_token_symbol,
                "decimals": response.loan_token_decimals,
            },
            "collateral_token": {
                "address": response.collateral_token,
                "symbol": response.collateral_token_symbol,
                "decimals": response.collateral_token_decimals,
            },
        },
        "brief": brief,
    }


def _map_replay_row_to_point(
    row: Any,
    *,
    detail: bool,
) -> MorphoPositionReplayPointResponse:
    assets = _parse_assets_json(row.get("assets_jsonb"))
    borrow_assets = Decimal(str(row.get("borrow_assets") or "0"))
    health_factor_raw = Decimal(str(row.get("health_factor") or "0"))
    return MorphoPositionReplayPointResponse(
        tx_hash=str(row.get("tx_hash") or ""),
        timestamp=_record_ts(row["block_timestamp"]),
        block_number=int(row.get("block_number") or 0),
        operation_type=row.get("operation_type"),
        brief=str(row.get("brief") or ""),
        has_position=bool(row.get("has_position")),
        is_healthy=bool(row.get("is_healthy")),
        collateral_value_in_loan_asset=str(
            row.get("collateral_value_in_loan_asset") or "0"
        ),
        borrow_assets=str(row.get("borrow_assets") or "0"),
        health_factor=_format_health(health_factor_raw, borrow_assets=borrow_assets),
        assets=_build_asset_responses(assets) if detail else [],
    )


async def get_user_position(
    w3: AsyncWeb3,
    *,
    pool: AsyncpgPool,
    address: str,
    market_id: str,
    protocol: str,
) -> MorphoPositionResponse:
    if protocol != MORPHO_DEFAULT_MARKET_TYPE:
        raise HTTPException(
            status_code=400, detail=f"unsupported morpho protocol: {protocol}"
        )

    normalized_market_id = _normalize_market_id_text(market_id)
    user_key = _evm_to_db_bytes(address)
    price_cache: dict[tuple[str, int | None], Decimal | None] = {}

    cached_positions, cached_assets = await fetch_current_user_positions(
        pool,
        user_address=user_key,
        market_id=normalized_market_id,
    )
    if cached_positions:
        cached_response = _build_response_from_db(cached_positions[0], cached_assets)
        if cached_response is not None:
            return cached_response

    position = await fetch_realtime_position(
        w3,
        address=address,
        market_id=normalized_market_id,
    )
    response = _build_response_from_rpc(position, data_source="rpc")
    await _enrich_position_assets_with_prices(
        w3,
        pool=pool,
        response=response,
        timestamp=None,
        cache=price_cache,
    )
    await _upsert_market_from_position(pool, position=position)
    await _cache_current_position(pool, position=position, response=response)
    return response


async def get_position_replay(
    w3: AsyncWeb3,
    *,
    pool: AsyncpgPool,
    address: str,
    market_id: str,
    protocol: str,
    from_ts: int,
    to_ts: int,
    use_cache: bool = True,
    detail: bool = False,
) -> MorphoPositionReplayResponse:
    if protocol != MORPHO_DEFAULT_MARKET_TYPE:
        raise HTTPException(
            status_code=400, detail=f"unsupported morpho protocol: {protocol}"
        )

    normalized_market_id = _normalize_market_id_text(market_id)
    user_key = _evm_to_db_bytes(address)
    from_dt = datetime.fromtimestamp(from_ts, tz=timezone.utc)
    to_dt = datetime.fromtimestamp(to_ts, tz=timezone.utc)
    price_cache: dict[tuple[str, int | None], Decimal | None] = {}
    cached_map: dict[str, Any] = {}

    events = await fetch_user_market_replay_events(
        w3,
        address=address,
        market_id=normalized_market_id,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    if not events:
        return MorphoPositionReplayResponse(
            protocol=MORPHO_PROTOCOL,
            market_type=MORPHO_DEFAULT_MARKET_TYPE,
            chain=MORPHO_CHAIN,
            market_id=normalized_market_id,
            address=_normalize_evm_address(address),
            from_time=_record_ts(from_dt),
            to_time=_record_ts(to_dt),
            data_source="rpc",
            total_points=0,
            total_tx_count=0,
            cache_hit_rate="0.00",
            points=[],
        )

    grouped: dict[str, list[MorphoReplayEvent]] = defaultdict(list)
    for event in events:
        grouped[event.tx_hash].append(event)

    if use_cache:
        cached_rows = await fetch_position_replay_snapshots(
            pool,
            user_address=user_key,
            market_id=normalized_market_id,
            from_ts=from_dt,
            to_ts=to_dt,
        )
        for row in cached_rows:
            tx_hash = str(row.get("tx_hash") or "")
            if not tx_hash:
                continue
            cached_map[tx_hash] = row

        if len(cached_map) == len(grouped):
            points = []
            for tx_hash, _tx_events in sorted(
                grouped.items(),
                key=lambda item: (
                    item[1][-1].block_number,
                    item[1][-1].log_index,
                    item[0],
                ),
            ):
                row = cached_map.get(tx_hash)
                if row is None:
                    continue
                points.append(_map_replay_row_to_point(row, detail=detail))
            return MorphoPositionReplayResponse(
                protocol=MORPHO_PROTOCOL,
                market_type=MORPHO_DEFAULT_MARKET_TYPE,
                chain=MORPHO_CHAIN,
                market_id=normalized_market_id,
                address=_normalize_evm_address(address),
                from_time=_record_ts(from_dt),
                to_time=_record_ts(to_dt),
                data_source="cache",
                total_points=len(points),
                total_tx_count=len(points),
                cache_hit_rate="1.00",
                points=points,
            )

    snapshot_rows: list[dict[str, Any]] = []
    points: list[MorphoPositionReplayPointResponse] = []
    for tx_hash, tx_events in sorted(
        grouped.items(),
        key=lambda item: (item[1][-1].block_number, item[1][-1].log_index, item[0]),
    ):
        cached_row = cached_map.get(tx_hash)
        if cached_row is not None:
            points.append(_map_replay_row_to_point(cached_row, detail=detail))
            continue
        tx_events.sort(key=lambda item: item.log_index)
        block_number = tx_events[-1].block_number
        position = await fetch_position_at_block(
            w3,
            address=address,
            market_id=normalized_market_id,
            block_identifier=block_number,
        )
        response = _build_response_from_rpc(position, data_source="rpc")
        await _enrich_position_assets_with_prices(
            w3,
            pool=pool,
            response=response,
            timestamp=int(position.block_timestamp.timestamp()),
            cache=price_cache,
        )
        await _upsert_market_from_position(pool, position=position)
        loan_price_usd = (
            Decimal(response.assets[0].price_usd)
            if response.assets and response.assets[0].price_usd is not None
            else None
        )
        collateral_price_usd = (
            Decimal(response.assets[1].price_usd)
            if len(response.assets) > 1 and response.assets[1].price_usd is not None
            else None
        )
        operation_type, brief = _build_group_brief(
            tx_events,
            loan_symbol=response.loan_token_symbol,
            collateral_symbol=response.collateral_token_symbol,
            loan_decimals=response.loan_token_decimals,
            collateral_decimals=response.collateral_token_decimals,
            loan_price_usd=loan_price_usd,
            collateral_price_usd=collateral_price_usd,
        )
        row = _build_replay_snapshot_row(
            position=position,
            response=response,
            tx_hash=tx_hash,
            operation_type=operation_type,
            brief=brief,
        )
        snapshot_rows.append(row)
        points.append(_map_replay_row_to_point(row, detail=detail))

    if snapshot_rows:
        await upsert_position_replay_snapshots(pool, rows=snapshot_rows)
    cached_count = len(grouped) - len(snapshot_rows)
    return MorphoPositionReplayResponse(
        protocol=MORPHO_PROTOCOL,
        market_type=MORPHO_DEFAULT_MARKET_TYPE,
        chain=MORPHO_CHAIN,
        market_id=normalized_market_id,
        address=_normalize_evm_address(address),
        from_time=_record_ts(from_dt),
        to_time=_record_ts(to_dt),
        data_source="rpc",
        total_points=len(points),
        total_tx_count=len(grouped),
        cache_hit_rate=format(Decimal(cached_count) / Decimal(len(grouped)), ".2f"),
        points=points,
    )


# api/morpho/vaults相关：分页读取 v1/v2 总表概览（仅查表，不请求 GraphQL）
async def get_votes_page(
    *,
    pool: AsyncpgPool,
    page: int,
    page_size: int,
    sort_by: str = "total_assets_usd",
    sort_order: str = "desc",
    asset: str | None = None,
    asset_address: str | None = None,
    protocol: str | None = None,
) -> MorphoVotesResponse:
    if page < 1:
        raise HTTPException(status_code=400, detail="page 必须从 1 开始")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page_size 必须在 1~100 之间")
    # api/morpho/vaults相关：排序字段与方向白名单，防止 SQL 注入
    sort_key = sort_by.strip().lower()
    sort_map = {
        "total_assets_usd": "total_assets_usd",
        "liquidity": "liquidity_usd",
        "apy": "apy",
    }
    if sort_key not in sort_map:
        raise HTTPException(
            status_code=400,
            detail="sort_by 仅支持 total_assets_usd / liquidity / apy",
        )
    order_key = sort_order.strip().lower()
    if order_key not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="sort_order 仅支持 asc 或 desc")
    order_sql = "ASC" if order_key == "asc" else "DESC"
    protocol_value: str | None = None
    if protocol is not None and protocol.strip():
        protocol_value = protocol.strip().lower()
        if protocol_value not in {"v1", "v2"}:
            raise HTTPException(status_code=400, detail="protocol 仅支持 v1 或 v2")
    asset_address_b: bytes | None = None
    # api/morpho/vaults相关：货币筛选优先走 asset，支持 0x 地址或币名映射
    if asset is not None and asset.strip():
        asset_value = asset.strip()
        if asset_value.lower().startswith("0x"):
            asset_address_b = _evm_to_db_bytes(asset_value)
        else:
            mapped = _resolve_ethereum_token_address(asset_value)
            if not mapped:
                raise HTTPException(
                    status_code=400,
                    detail=f"不支持的资产筛选值: {asset_value}",
                )
            asset_address_b = _evm_to_db_bytes(mapped)
    elif asset_address is not None and asset_address.strip():
        asset_address_b = _evm_to_db_bytes(asset_address.strip())
    offset = (page - 1) * page_size

    count_sql = """
        SELECT COUNT(1) AS total
        FROM (
            SELECT asset_address, 'v1'::text AS protocol
            FROM loan.morpho_vault_v1_current
            UNION ALL
            SELECT asset_address, 'v2'::text AS protocol
            FROM loan.morpho_vault_v2_current
        ) t
        WHERE ($1::bytea IS NULL OR asset_address = $1)
          AND ($2::text IS NULL OR protocol = $2)
    """
    page_sql = f"""
        SELECT
            vault_address,
            vault_name AS name,
            asset_symbol,
            asset_address,
            total_assets_usd,
            liquidity_usd,
            apy,
            protocol
        FROM (
            SELECT
                vault_address,
                vault_name,
                asset_symbol,
                asset_address,
                total_assets_usd,
                liquidity_usd,
                apy,
                'v1'::text AS protocol
            FROM loan.morpho_vault_v1_current
            UNION ALL
            SELECT
                vault_address,
                vault_name,
                asset_symbol,
                asset_address,
                total_assets_usd,
                liquidity_usd,
                apy,
                'v2'::text AS protocol
            FROM loan.morpho_vault_v2_current
        ) merged
        WHERE ($1::bytea IS NULL OR asset_address = $1)
          AND ($2::text IS NULL OR protocol = $2)
        ORDER BY {sort_map[sort_key]} {order_sql} NULLS LAST
        OFFSET $3
        LIMIT $4
    """
    async with pool.acquire() as conn:
        total_row = await conn.fetchrow(count_sql, asset_address_b, protocol_value)
        total = int(total_row["total"]) if total_row else 0
        rows = await conn.fetch(
            page_sql, asset_address_b, protocol_value, offset, page_size
        )

    items: list[MorphoVotesItem] = []
    for row in rows:
        items.append(
            MorphoVotesItem(
                address=_db_bytes_to_evm(row["vault_address"]),
                name=str(row["name"] or ""),
                asset=MorphoVotesAsset(
                    asset=str(row["asset_symbol"] or ""),
                    token_address=_db_bytes_to_evm(row["asset_address"]),
                ),
                total_assets_usd=float(row["total_assets_usd"] or 0),
                liquidity=float(row["liquidity_usd"] or 0),
                apy=float(row["apy"] or 0),
                protocol=str(row["protocol"] or ""),
            )
        )

    return MorphoVotesResponse(
        page=page,
        page_size=page_size,
        total=total,
        items=items,
    )
