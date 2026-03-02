"""
Aave V2 / V3 Ethereum Mainnet 合约调用层。

使用 web3.py AsyncWeb3 + AsyncHTTPProvider，支持多公共节点后备。
所有返回值保持链上原始整数，不做精度转换。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from web3 import AsyncWeb3
from web3.providers import AsyncHTTPProvider

from .config import AppConfig
from .models import (AccountSummary, ReserveConfig, ReservePosition,
                     ReserveToken, UserPosition, UserReserveData)

logger = logging.getLogger(__name__)

# ── 合约地址（Ethereum Mainnet Aave V3） ─────────────────────────────────────────────────
# 与 rpc_example.py 中使用的地址一致
POOL_ADDRESS = AsyncWeb3.to_checksum_address(
    "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
)
DATA_PROVIDER_ADDRESS = AsyncWeb3.to_checksum_address(
    "0x7B4EB56E7CD4b454BA8ff71E4518426369a138a3"
)
ORACLE_ADDRESS = AsyncWeb3.to_checksum_address(
    "0x54586bE62E3c3580375aE3723C145253060Ca0C2"
)

ETH_CHAIN_ID = 1


# ── 协议合约配置 ──────────────────────────────────────────────────────────────

# WETH 地址（Ethereum Mainnet），用于从 V3 oracle 获取 ETH/USD 价格
WETH_ADDRESS = AsyncWeb3.to_checksum_address(
    "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
)


@dataclass
class ProtocolContracts:
    """一套 Aave 协议的三个核心合约地址，支持 V2 / V3。

    oracle_price_in_eth: True 表示该协议的 oracle 返回 ETH 计价（18 位精度），
    需要在使用前乘以 ETH/USD 把价格归一化为 8 位 USD。
    Aave V2 Ethereum Mainnet 的 oracle 返回 ETH 价格；V3 返回 USD 价格。
    """

    pool: str  # LendingPool (V2) 或 Pool (V3)
    data_provider: str  # ProtocolDataProvider
    oracle: str  # AaveOracle
    oracle_price_in_eth: bool = False  # V2=True (ETH/18-dec), V3=False (USD/8-dec)


# Aave V3 Ethereum Mainnet
CONTRACTS_V3 = ProtocolContracts(
    pool=POOL_ADDRESS,
    data_provider=DATA_PROVIDER_ADDRESS,
    oracle=ORACLE_ADDRESS,
    oracle_price_in_eth=False,
)

# Aave V2 Ethereum Mainnet
# V2 oracle (0xA50ba011c48153De246E5192C8f9258A2ba79Ca9) 返回 ETH 计价（18 位精度）
CONTRACTS_V2 = ProtocolContracts(
    pool=AsyncWeb3.to_checksum_address("0x7d2768dE32b0b80b7a3454c06BdAc94A69DDc7A9"),
    data_provider=AsyncWeb3.to_checksum_address(
        "0x057835Ad21a177dbdd3090bB1CAE03EaCF78Fc6d"
    ),
    oracle=AsyncWeb3.to_checksum_address("0xA50ba011c48153De246E5192C8f9258A2ba79Ca9"),
    oracle_price_in_eth=True,
)

_PROTOCOL_CONTRACTS: dict[str, ProtocolContracts] = {
    "v3": CONTRACTS_V3,
    "v2": CONTRACTS_V2,
}


def get_contracts(protocol: str = "v3") -> ProtocolContracts:
    """根据协议版本字符串返回对应合约配置。v3_borrow/v2_borrow 使用同一套合约。"""
    # 取基础协议版本：v3_borrow → v3，v2_borrow → v2
    base = protocol.lower().split("_")[0]
    c = _PROTOCOL_CONTRACTS.get(base)
    if c is None:
        raise ValueError(
            f"不支持的协议版本: {protocol!r}，可选: v2, v3, v2_borrow, v3_borrow"
        )
    return c


PUBLIC_RPCS = [
    "https://eth.llamarpc.com",
    "https://ethereum-rpc.publicnode.com",
    "https://1rpc.io/eth",
    "https://rpc.ankr.com/eth",
    "https://cloudflare-eth.com",
]

# ── ABI ──────────────────────────────────────────────────────────────────────
POOL_ABI: list[dict[str, Any]] = [
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "getUserAccountData",
        "outputs": [
            {"name": "totalCollateralBase", "type": "uint256"},
            {"name": "totalDebtBase", "type": "uint256"},
            {"name": "availableBorrowsBase", "type": "uint256"},
            {"name": "currentLiquidationThreshold", "type": "uint256"},
            {"name": "ltv", "type": "uint256"},
            {"name": "healthFactor", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

DATA_PROVIDER_ABI: list[dict[str, Any]] = [
    {
        "inputs": [],
        "name": "getAllReservesTokens",
        "outputs": [
            {
                "components": [
                    {"name": "symbol", "type": "string"},
                    {"name": "tokenAddress", "type": "address"},
                ],
                "name": "",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "asset", "type": "address"},
            {"name": "user", "type": "address"},
        ],
        "name": "getUserReserveData",
        "outputs": [
            {"name": "currentATokenBalance", "type": "uint256"},
            {"name": "currentStableDebt", "type": "uint256"},
            {"name": "currentVariableDebt", "type": "uint256"},
            {"name": "principalStableDebt", "type": "uint256"},
            {"name": "scaledVariableDebt", "type": "uint256"},
            {"name": "stableBorrowRate", "type": "uint256"},
            {"name": "liquidityRate", "type": "uint256"},
            {"name": "stableRateLastUpdated", "type": "uint40"},
            {"name": "usageAsCollateralEnabled", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "asset", "type": "address"}],
        "name": "getReserveConfigurationData",
        "outputs": [
            {"name": "decimals", "type": "uint256"},
            {"name": "ltv", "type": "uint256"},
            {"name": "liquidationThreshold", "type": "uint256"},
            {"name": "liquidationBonus", "type": "uint256"},
            {"name": "reserveFactor", "type": "uint256"},
            {"name": "usageAsCollateralEnabled", "type": "bool"},
            {"name": "borrowingEnabled", "type": "bool"},
            {"name": "stableBorrowRateEnabled", "type": "bool"},
            {"name": "isActive", "type": "bool"},
            {"name": "isFrozen", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

ORACLE_ABI: list[dict[str, Any]] = [
    {
        "inputs": [{"name": "assets", "type": "address[]"}],
        "name": "getAssetsPrices",
        "outputs": [{"name": "", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# ── 客户端工厂 ────────────────────────────────────────────────────────────────


async def build_web3(cfg: AppConfig) -> AsyncWeb3:
    """
    构建 AsyncWeb3 实例。
    若配置了自定义 rpc_url，验证其 chain_id 是否为以太主网（1）；
    若不通过或未配置，则顺序尝试公共以太节点。
    """
    timeout = cfg.crawler.rpc_timeout

    async def _try_url(url: str) -> AsyncWeb3 | None:
        w3 = AsyncWeb3(AsyncHTTPProvider(url, request_kwargs={"timeout": timeout}))
        try:
            chain_id = await w3.eth.chain_id
            if chain_id != ETH_CHAIN_ID:
                logger.warning(
                    "RPC %s chain_id=%d，不是以太主网（%d），跳过",
                    url,
                    chain_id,
                    ETH_CHAIN_ID,
                )
                return None
            logger.info("使用 RPC: %s (chain_id=1)", url)
            return w3
        except Exception as exc:
            logger.debug("RPC %s 探测失败: %s", url, exc)
            return None

    # 优先尝试自定义节点
    custom = (cfg.rpc_url or "").strip()
    if custom:
        w3 = await _try_url(custom)
        if w3:
            return w3
        logger.warning("自定义 RPC 不可用，切换到公共节点")

    # 依次尝试公共节点
    for url in PUBLIC_RPCS:
        w3 = await _try_url(url)
        if w3:
            return w3

    raise RuntimeError("所有 RPC 节点均不可用，请检查网络或 config.yaml 中的 rpc_url")


# ── 合约调用封装 ──────────────────────────────────────────────────────────────


async def get_user_account_data(
    w3: AsyncWeb3, user_address: str, contracts: ProtocolContracts = CONTRACTS_V3
) -> AccountSummary:
    contract = w3.eth.contract(address=contracts.pool, abi=POOL_ABI)
    result = await contract.functions.getUserAccountData(
        AsyncWeb3.to_checksum_address(user_address)
    ).call()
    return AccountSummary(
        total_collateral_base=result[0],
        total_debt_base=result[1],
        available_borrows_base=result[2],
        current_liquidation_threshold=result[3],
        ltv=result[4],
        health_factor=result[5],
    )


async def get_all_reserve_tokens(
    w3: AsyncWeb3, contracts: ProtocolContracts = CONTRACTS_V3
) -> list[ReserveToken]:
    contract = w3.eth.contract(address=contracts.data_provider, abi=DATA_PROVIDER_ABI)
    result = await contract.functions.getAllReservesTokens().call()
    return [ReserveToken(symbol=r[0], token_address=r[1]) for r in result]


async def get_user_reserve_data(
    w3: AsyncWeb3, asset: str, user: str, contracts: ProtocolContracts = CONTRACTS_V3
) -> UserReserveData:
    contract = w3.eth.contract(address=contracts.data_provider, abi=DATA_PROVIDER_ABI)
    r = await contract.functions.getUserReserveData(
        AsyncWeb3.to_checksum_address(asset),
        AsyncWeb3.to_checksum_address(user),
    ).call()
    return UserReserveData(
        current_atoken_balance=r[0],
        current_stable_debt=r[1],
        current_variable_debt=r[2],
        principal_stable_debt=r[3],
        scaled_variable_debt=r[4],
        stable_borrow_rate=r[5],
        liquidity_rate=r[6],
        stable_rate_last_updated=r[7],
        usage_as_collateral_enabled=r[8],
    )


async def get_reserve_config(
    w3: AsyncWeb3, asset: str, contracts: ProtocolContracts = CONTRACTS_V3
) -> ReserveConfig:
    contract = w3.eth.contract(address=contracts.data_provider, abi=DATA_PROVIDER_ABI)
    r = await contract.functions.getReserveConfigurationData(
        AsyncWeb3.to_checksum_address(asset)
    ).call()
    return ReserveConfig(
        decimals=r[0],
        ltv=r[1],
        liquidation_threshold=r[2],
        liquidation_bonus=r[3],
        reserve_factor=r[4],
        usage_as_collateral_enabled=r[5],
        borrowing_enabled=r[6],
        stable_borrow_rate_enabled=r[7],
        is_active=r[8],
        is_frozen=r[9],
    )


async def get_assets_prices(
    w3: AsyncWeb3, assets: list[str], contracts: ProtocolContracts = CONTRACTS_V3
) -> list[int]:
    contract = w3.eth.contract(address=contracts.oracle, abi=ORACLE_ABI)
    checksum_assets = [AsyncWeb3.to_checksum_address(a) for a in assets]
    return list(await contract.functions.getAssetsPrices(checksum_assets).call())


# ── 高层查询（单用户完整仓位） ────────────────────────────────────────────────

# 哨兵值：账户在 Aave 无任何仓位（totalCollateral==0 && totalDebt==0）
# 与 None（RPC 报错）区分开，供调用方分别统计
EMPTY_POSITION = object()


async def fetch_user_position(
    w3: AsyncWeb3,
    user_address: str,
    reserve_tokens: list[ReserveToken],
    reserve_configs: dict[str, ReserveConfig],
    asset_prices: dict[str, int],
    semaphore: asyncio.Semaphore,
    contracts: ProtocolContracts = CONTRACTS_V3,
) -> "UserPosition | object | None":
    """
    查询单个用户的全部 Aave 仓位。

    返回值说明：
    - UserPosition   : 有效仓位数据
    - EMPTY_POSITION : 账户当前在 Aave 无任何抵押/借贷（历史地址已平仓）
    - None           : RPC 调用失败
    """
    async with semaphore:
        try:
            summary = await get_user_account_data(w3, user_address, contracts)

            # 快速跳过：既没有抵押品也没有借贷，返回哨兵（≠ 报错）
            if summary.total_collateral_base == 0 and summary.total_debt_base == 0:
                return EMPTY_POSITION

            block = await w3.eth.block_number

            # 并发查询该用户在所有资产的仓位
            tasks = [
                get_user_reserve_data(w3, rt.token_address, user_address, contracts)
                for rt in reserve_tokens
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            reserves: list[ReservePosition] = []
            for rt, res in zip(reserve_tokens, results):
                if isinstance(res, Exception):
                    logger.debug(
                        "getUserReserveData 失败 asset=%s user=%s: %s",
                        rt.token_address,
                        user_address,
                        res,
                    )
                    continue
                # 跳过未持有该资产的仓位（供给和借贷均为 0）
                if (
                    res.current_atoken_balance == 0
                    and res.current_stable_debt == 0
                    and res.current_variable_debt == 0
                ):
                    continue
                cfg = reserve_configs.get(rt.token_address)
                reserves.append(
                    ReservePosition(
                        symbol=rt.symbol,
                        token_address=rt.token_address,
                        decimals=cfg.decimals if cfg else 18,
                        price_raw=asset_prices.get(rt.token_address, 0),
                        supply_raw=res.current_atoken_balance,
                        usage_as_collateral_enabled=res.usage_as_collateral_enabled,
                        liquidation_threshold=cfg.liquidation_threshold if cfg else 0,
                        stable_debt_raw=res.current_stable_debt,
                        variable_debt_raw=res.current_variable_debt,
                    )
                )

            return UserPosition(
                user_address=user_address.lower(),
                block_number=block,
                summary=summary,
                reserves=reserves,
            )
        except Exception as exc:
            logger.warning("fetch_user_position 失败 user=%s: %s", user_address, exc)
            return None
