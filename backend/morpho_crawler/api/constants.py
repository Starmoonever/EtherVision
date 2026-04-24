"""Morpho FastAPI 层常量。

当前仅承载 GET /api/morpho/markets 分页接口使用的硬编码市场列表。
"""

from __future__ import annotations


# api/morpho/markets相关：Morpho Blue GraphQL 使用的链 ID（Ethereum mainnet）
MORPHO_MARKETS_BLUE_API_CHAIN_ID = 1

# api/morpho/markets相关：Morpho 官方 Blue API（与 app 市场数据同源）
MORPHO_BLUE_GRAPHQL_URL = "https://blue-api.morpho.org/graphql"

# api/morpho/vault/v1/state相关：Morpho 主站 GraphQL（Vault / vaultByAddress 与官网一致）
MORPHO_MAIN_GRAPHQL_URL = "https://api.morpho.org/graphql"

# api/morpho/vault/v2/state相关：Morpho 主站 GraphQL（VaultV2 / vaultV2ByAddress）
MORPHO_MAIN_GRAPHQL_URL_V2 = "https://api.morpho.org/graphql"
