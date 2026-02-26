import { createPublicClient, http, formatUnits, isAddress, type Address } from 'viem';
import { mainnet } from 'viem/chains';

// ── 合约地址 (Ethereum Mainnet Aave V3) ──────────────────────────────────────
export const AAVE_ADDRESSES = {
  pool: '0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2' as Address,
  dataProvider: '0x7B4EB56E7CD4b454BA8ff71E4518426369a138a3' as Address,
};

// ── ABI ──────────────────────────────────────────────────────────────────────
const POOL_ABI = [
  {
    inputs: [{ name: 'user', type: 'address' }],
    name: 'getUserAccountData',
    outputs: [
      { name: 'totalCollateralBase', type: 'uint256' },
      { name: 'totalDebtBase', type: 'uint256' },
      { name: 'availableBorrowsBase', type: 'uint256' },
      { name: 'currentLiquidationThreshold', type: 'uint256' },
      { name: 'ltv', type: 'uint256' },
      { name: 'healthFactor', type: 'uint256' },
    ],
    stateMutability: 'view',
    type: 'function',
  },
] as const;

const DATA_PROVIDER_ABI = [
  {
    inputs: [],
    name: 'getAllReservesTokens',
    outputs: [
      {
        components: [
          { name: 'symbol', type: 'string' },
          { name: 'tokenAddress', type: 'address' },
        ],
        name: '',
        type: 'tuple[]',
      },
    ],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [
      { name: 'asset', type: 'address' },
      { name: 'user', type: 'address' },
    ],
    name: 'getUserReserveData',
    outputs: [
      { name: 'currentATokenBalance', type: 'uint256' },
      { name: 'currentStableDebt', type: 'uint256' },
      { name: 'currentVariableDebt', type: 'uint256' },
      { name: 'principalStableDebt', type: 'uint256' },
      { name: 'scaledVariableDebt', type: 'uint256' },
      { name: 'stableBorrowRate', type: 'uint256' },
      { name: 'liquidityRate', type: 'uint256' },
      { name: 'stableRateLastUpdated', type: 'uint40' },
      { name: 'usageAsCollateralEnabled', type: 'bool' },
    ],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [{ name: 'asset', type: 'address' }],
    name: 'getReserveConfigurationData',
    outputs: [
      { name: 'decimals', type: 'uint256' },
      { name: 'ltv', type: 'uint256' },
      { name: 'liquidationThreshold', type: 'uint256' },
      { name: 'liquidationBonus', type: 'uint256' },
      { name: 'reserveFactor', type: 'uint256' },
      { name: 'usageAsCollateralEnabled', type: 'bool' },
      { name: 'borrowingEnabled', type: 'bool' },
      { name: 'stableBorrowRateEnabled', type: 'bool' },
      { name: 'isActive', type: 'bool' },
      { name: 'isFrozen', type: 'bool' },
    ],
    stateMutability: 'view',
    type: 'function',
  },
] as const;

// ── 类型 ──────────────────────────────────────────────────────────────────────
export interface AccountSummary {
  totalCollateralUSD: string;
  totalDebtUSD: string;
  availableBorrowsUSD: string;
  currentLiquidationThreshold: string;
  ltv: string;
  healthFactor: string;
  healthFactorRaw: bigint;
}

export interface ReservePosition {
  symbol: string;
  tokenAddress: Address;
  decimals: number;
  // 供给
  supplyBalance: string;
  supplyBalanceRaw: bigint;
  usageAsCollateralEnabled: boolean;
  // 借贷
  stableDebt: string;
  stableDebtRaw: bigint;
  variableDebt: string;
  variableDebtRaw: bigint;
  totalDebt: string;
}

export interface UserPosition {
  summary: AccountSummary;
  reserves: ReservePosition[];
}

// ── 备用 RPC 列表（按优先级排序；配置了 VITE_ETH_RPC_URL 时优先使用）─────────────
const PUBLIC_RPCS = [
  'https://eth.llamarpc.com',
  'https://rpc.ankr.com/eth',
  'https://ethereum.publicnode.com',
  'https://1rpc.io/eth',
  'https://cloudflare-eth.com',
];

function getClient() {
  const custom = import.meta.env.VITE_ETH_RPC_URL as string | undefined;
  const rpcUrl = custom && custom.trim() ? custom.trim() : PUBLIC_RPCS[0];
  return createPublicClient({
    chain: mainnet,
    transport: http(rpcUrl, {
      timeout: 20_000,
      retryCount: 2,
      retryDelay: 1_500,
    }),
  });
}

// ── 错误分类辅助 ──────────────────────────────────────────────────────────────
function classifyRpcError(err: unknown): never {
  const msg = err instanceof Error ? err.message : String(err);

  // JSON-RPC -32603 / Internal error  →  RPC 节点自身故障或限流
  if (/internal error/i.test(msg)) {
    throw new Error(
      'RPC 节点返回内部错误（可能被限流或节点故障）。\n' +
      '建议在 .env.local 中配置 VITE_ETH_RPC_URL 使用 Infura / Alchemy 等私有节点，然后刷新页面重试。'
    );
  }

  // 超时
  if (/timeout|timed? ?out/i.test(msg)) {
    throw new Error('RPC 请求超时，请检查网络或更换 RPC 节点后重试。');
  }

  // 合约 revert
  if (/revert|execution reverted/i.test(msg)) {
    throw new Error(`合约调用失败：${msg}`);
  }

  throw err instanceof Error ? err : new Error(msg);
}

// ── 核心查询函数 ──────────────────────────────────────────────────────────────
export async function fetchUserPosition(userAddress: string): Promise<UserPosition> {
  if (!isAddress(userAddress)) {
    throw new Error('无效的以太坊地址');
  }

  const client = getClient();
  const user = userAddress as Address;

  // 1. 获取账户汇总数据
  let accountData: readonly [bigint, bigint, bigint, bigint, bigint, bigint];
  try {
    accountData = await client.readContract({
      address: AAVE_ADDRESSES.pool,
      abi: POOL_ABI,
      functionName: 'getUserAccountData',
      args: [user],
    });
  } catch (err) {
    classifyRpcError(err);
  }

  const [
    totalCollateralBase,
    totalDebtBase,
    availableBorrowsBase,
    currentLiquidationThreshold,
    ltvRaw,
    healthFactor,
  ] = accountData!;

  const summary: AccountSummary = {
    totalCollateralUSD: formatUnits(totalCollateralBase, 8),
    totalDebtUSD: formatUnits(totalDebtBase, 8),
    availableBorrowsUSD: formatUnits(availableBorrowsBase, 8),
    currentLiquidationThreshold: (Number(currentLiquidationThreshold) / 100).toFixed(2),
    ltv: (Number(ltvRaw) / 100).toFixed(2),
    healthFactor:
      healthFactor >= BigInt('115792089237316195423570985008687907853269984665640564039457584007913129639935')
        ? '∞'
        : parseFloat(formatUnits(healthFactor, 18)).toFixed(4),
    healthFactorRaw: healthFactor,
  };

  // 2. 获取所有储备资产列表
  let reserveTokens: readonly { symbol: string; tokenAddress: Address }[];
  try {
    reserveTokens = await client.readContract({
      address: AAVE_ADDRESSES.dataProvider,
      abi: DATA_PROVIDER_ABI,
      functionName: 'getAllReservesTokens',
    });
  } catch (err) {
    classifyRpcError(err);
  }

  // 3. 批量查询 - 用户储备数据 + 储备配置（获取 decimals）
  const userReservesCalls = reserveTokens!.map((token) => ({
    address: AAVE_ADDRESSES.dataProvider,
    abi: DATA_PROVIDER_ABI,
    functionName: 'getUserReserveData' as const,
    args: [token.tokenAddress, user] as [Address, Address],
  }));

  const configCalls = reserveTokens!.map((token) => ({
    address: AAVE_ADDRESSES.dataProvider,
    abi: DATA_PROVIDER_ABI,
    functionName: 'getReserveConfigurationData' as const,
    args: [token.tokenAddress] as [Address],
  }));


  type McResult = { status: 'success'; result: unknown } | { status: 'failure'; error: Error };
  let userReservesResults: McResult[];

  let configResults: McResult[];
  try {
    [userReservesResults, configResults] = await Promise.all([
      client.multicall({ contracts: userReservesCalls, allowFailure: true }),
      client.multicall({ contracts: configCalls, allowFailure: true }),
    ]) as [McResult[], McResult[]];
  } catch (err) {
    classifyRpcError(err);
  }

  // 4. 整合数据，过滤出有仓位的资产
  const reserves: ReservePosition[] = [];

  for (let i = 0; i < reserveTokens!.length; i++) {
    const token = reserveTokens![i];
    const reserveResult = userReservesResults![i];
    const configResult = configResults![i];

    if (reserveResult.status !== 'success' || configResult.status !== 'success') continue;

    const [
      currentATokenBalance,
      currentStableDebt,
      currentVariableDebt,
      ,
      ,
      ,
      ,
      ,
      usageAsCollateralEnabled,
    ] = reserveResult.result as readonly [
      bigint,
      bigint,
      bigint,
      bigint,
      bigint,
      bigint,
      bigint,
      number,
      boolean,
    ];

    const [decimalsRaw] = configResult.result as readonly [
      bigint,
      bigint,
      bigint,
      bigint,
      bigint,
      boolean,
      boolean,
      boolean,
      boolean,
      boolean,
    ];

    const decimals = Number(decimalsRaw);
    const totalDebtRaw = currentStableDebt + currentVariableDebt;

    // 过滤掉没有任何仓位的资产
    if (currentATokenBalance === 0n && totalDebtRaw === 0n) continue;

    reserves.push({
      symbol: token.symbol,
      tokenAddress: token.tokenAddress,
      decimals,
      supplyBalance: parseFloat(formatUnits(currentATokenBalance, decimals)).toFixed(6),
      supplyBalanceRaw: currentATokenBalance,
      usageAsCollateralEnabled,
      stableDebt: parseFloat(formatUnits(currentStableDebt, decimals)).toFixed(6),
      stableDebtRaw: currentStableDebt,
      variableDebt: parseFloat(formatUnits(currentVariableDebt, decimals)).toFixed(6),
      variableDebtRaw: currentVariableDebt,
      totalDebt: parseFloat(formatUnits(totalDebtRaw, decimals)).toFixed(6),
    });
  }

  return { summary, reserves };
}
