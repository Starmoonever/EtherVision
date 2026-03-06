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
    {
        "inputs": [{"name": "asset", "type": "address"}],
        "name": "getAssetPrice",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Chainlink ETH/USD 聚合器（主网，2019年起可用，比 Aave V3 oracle 更早）
CHAINLINK_ETH_USD = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"
# latestRoundData() → (roundId, answer/8dec, startedAt, updatedAt, answeredInRound)
CHAINLINK_ETH_USD_ABI: list[dict] = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId",          "type": "uint80"},
            {"name": "answer",           "type": "int256"},
            {"name": "startedAt",        "type": "uint256"},
            {"name": "updatedAt",        "type": "uint256"},
            {"name": "answeredInRound",  "type": "uint80"},
        ],
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

            # V2 oracle 返回 ETH 计价（18 位）；调用方已将 asset_prices 归一化为 USD/8dec，
            # 其中 asset_prices[WETH_ADDRESS] 即 eth_usd_raw（8 位 USD）。
            # AccountSummary 的 base 字段同样需要从 ETH/18dec 转换为 USD/8dec。
            if contracts.oracle_price_in_eth:
                eth_usd_raw = asset_prices.get(WETH_ADDRESS, 0)
                if eth_usd_raw > 0:
                    summary = AccountSummary(
                        total_collateral_base=(summary.total_collateral_base * eth_usd_raw) // (10**18),
                        total_debt_base=(summary.total_debt_base * eth_usd_raw) // (10**18),
                        available_borrows_base=(summary.available_borrows_base * eth_usd_raw) // (10**18),
                        current_liquidation_threshold=summary.current_liquidation_threshold,
                        ltv=summary.ltv,
                        health_factor=summary.health_factor,
                    )

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


async def fetch_user_position_at_block(
    w3: AsyncWeb3,
    user_address: str,
    reserve_tokens: list[ReserveToken],
    reserve_configs: dict[str, ReserveConfig],
    block_number: int,
    semaphore: asyncio.Semaphore,
    contracts: ProtocolContracts = CONTRACTS_V3,
) -> "tuple[UserPosition, int] | object | None":
    """RPC 重放：用 eth_call 查询用户在指定区块时刻的链上仓位（真实值，无利息误差）。

    返回值：
    - (UserPosition, eth_price_raw) : 有效仓位，eth_price_raw 为 WETH 8 位 USD 原始值
    - EMPTY_POSITION               : 该区块用户无仓位（collateral == debt == 0）
    - None                         : RPC 调用失败
    """
    async with semaphore:
        try:
            pool_contract = w3.eth.contract(address=contracts.pool, abi=POOL_ABI)
            raw = await pool_contract.functions.getUserAccountData(
                AsyncWeb3.to_checksum_address(user_address)
            ).call(block_identifier=block_number)

            summary = AccountSummary(
                total_collateral_base=raw[0],
                total_debt_base=raw[1],
                available_borrows_base=raw[2],
                current_liquidation_threshold=raw[3],
                ltv=raw[4],
                health_factor=raw[5],
            )

            if summary.total_collateral_base == 0 and summary.total_debt_base == 0:
                return EMPTY_POSITION

            token_addresses = [rt.token_address for rt in reserve_tokens]
            data_contract = w3.eth.contract(
                address=contracts.data_provider, abi=DATA_PROVIDER_ABI
            )
            oracle_contract = w3.eth.contract(address=contracts.oracle, abi=ORACLE_ABI)

            # 并发：所有 reserve 明细 + 全量价格（均 at block_number）
            reserve_tasks = [
                data_contract.functions.getUserReserveData(
                    AsyncWeb3.to_checksum_address(rt.token_address),
                    AsyncWeb3.to_checksum_address(user_address),
                ).call(block_identifier=block_number)
                for rt in reserve_tokens
            ]
            # 逐资产查询价格：历史块上新上线的 token 在老版 oracle 中不存在会 revert，
            # 批量接口 getAssetsPrices 一旦有任意未知地址就整体失败；
            # 改用单资产 getAssetPrice 并发 + return_exceptions，过滤失败项。
            price_tasks = [
                oracle_contract.functions.getAssetPrice(
                    AsyncWeb3.to_checksum_address(a)
                ).call(block_identifier=block_number)
                for a in token_addresses
            ]

            all_results = await asyncio.gather(
                *reserve_tasks, *price_tasks, return_exceptions=True
            )
            reserve_results = all_results[: len(reserve_tasks)]
            price_results  = all_results[len(reserve_tasks):]

            asset_prices: dict[str, int] = {
                addr: p
                for addr, p in zip(token_addresses, price_results)
                if not isinstance(p, Exception) and isinstance(p, int) and p > 0
            }

            if not asset_prices:
                logger.warning(
                    "fetch_user_position_at_block: block %d 所有资产价格查询均失败",
                    block_number,
                )
                return None

            # V2 oracle 返回 ETH 计价 → 归一化为 USD（8 位精度）
            # V2 getUserAccountData 同样返回 ETH/Wei（18 位），需一并归一化：
            #   (eth_wei * eth_usd_raw) // 10^18 → USD/8dec，与 V3 格式统一
            # 优先使用 Chainlink ETH/USD 聚合器，因其从 2019 年起即可用；
            # V3 Aave oracle 于 2023-01 才部署，无法用于更早的历史块。
            if contracts.oracle_price_in_eth:
                eth_usd_raw: int = 0

                # 1️⃣ Chainlink ETH/USD（主备）
                try:
                    cl_feed = w3.eth.contract(
                        address=CHAINLINK_ETH_USD, abi=CHAINLINK_ETH_USD_ABI
                    )
                    _round = await cl_feed.functions.latestRoundData().call(
                        block_identifier=block_number
                    )
                    # answer 为 int256，正常情况 > 0
                    if _round[1] > 0:
                        eth_usd_raw = int(_round[1])
                except Exception as _cl_exc:
                    logger.debug(
                        "Chainlink ETH/USD 查询失败 block=%d: %s", block_number, _cl_exc
                    )

                # 2️⃣ 若 Chainlink 失败，降级到 V3 Aave oracle
                if eth_usd_raw == 0:
                    try:
                        v3_oracle = w3.eth.contract(
                            address=CONTRACTS_V3.oracle, abi=ORACLE_ABI
                        )
                        eth_usd_raw = await v3_oracle.functions.getAssetPrice(
                            WETH_ADDRESS
                        ).call(block_identifier=block_number)
                    except Exception as _v3_exc:
                        logger.warning(
                            "V2 ETH/USD 归一化失败 block=%d (Chainlink+V3均失败): %s",
                            block_number, _v3_exc,
                        )

                if eth_usd_raw == 0:
                    # 两个数据源均失败：V2 oracle 价格仍为 ETH/18dec 原始值，
                    # 无法归一化为 USD，继续写入会产生严重失真（如 $100亿）。
                    # 返回 None 让调用方跳过本 tx，等下次重试。
                    logger.warning(
                        "V2 ETH/USD 归一化失败 block=%d，跳过本仓位",
                        block_number,
                    )
                    return None

                asset_prices = {
                    addr: (price * eth_usd_raw) // (10**18)
                    for addr, price in asset_prices.items()
                }
                # AccountSummary 三个 "base" 字段同步归一化为 USD/8dec
                summary = AccountSummary(
                    total_collateral_base=(summary.total_collateral_base * eth_usd_raw) // (10**18),
                    total_debt_base=(summary.total_debt_base * eth_usd_raw) // (10**18),
                    available_borrows_base=(summary.available_borrows_base * eth_usd_raw) // (10**18),
                    current_liquidation_threshold=summary.current_liquidation_threshold,
                    ltv=summary.ltv,
                    health_factor=summary.health_factor,
                )

            reserves: list[ReservePosition] = []
            for rt, res in zip(reserve_tokens, reserve_results):
                if isinstance(res, Exception):
                    continue
                # res: tuple from getUserReserveData
                if res[0] == 0 and res[1] == 0 and res[2] == 0:
                    continue
                cfg = reserve_configs.get(rt.token_address)
                reserves.append(
                    ReservePosition(
                        symbol=rt.symbol,
                        token_address=rt.token_address,
                        decimals=cfg.decimals if cfg else 18,
                        price_raw=asset_prices.get(rt.token_address, 0),
                        supply_raw=res[0],
                        usage_as_collateral_enabled=res[8],
                        liquidation_threshold=cfg.liquidation_threshold if cfg else 0,
                        stable_debt_raw=res[1],
                        variable_debt_raw=res[2],
                    )
                )

            # ETH/USD 价格（8 位精度）：V3 直接取 WETH oracle 价格；
            # V2 已在上方归一化，用 WETH_ADDRESS 取归一化后的值
            eth_price_raw = asset_prices.get(WETH_ADDRESS, 0)
            if eth_price_raw == 0:
                # fallback: 遍历找第一个 ETH 系资产价格
                _eth_syms = {"WETH", "ETH", "CBETH", "WSTETH", "RETH"}
                for rt in reserve_tokens:
                    if rt.symbol.upper() in _eth_syms:
                        eth_price_raw = asset_prices.get(rt.token_address, 0)
                        if eth_price_raw:
                            break

            pos = UserPosition(
                user_address=user_address.lower(),
                block_number=block_number,
                summary=summary,
                reserves=reserves,
            )
            return pos, eth_price_raw

        except Exception as exc:
            logger.warning(
                "fetch_user_position_at_block 失败 user=%s block=%d: %s",
                user_address,
                block_number,
                exc,
            )
            return None
