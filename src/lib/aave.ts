import { createPublicClient, http, formatUnits, isAddress, type Address } from 'viem';
import { base } from 'viem/chains';

// ── 合约地址 (Base Mainnet Aave V3) ──────────────────────────────────────────
export const AAVE_ADDRESSES = {
  pool: '0xA238Dd80C259a72e81d7e4664a9801593F98d1c5' as Address,
  dataProvider: '0x0F43731EB8d45A581f4a36DD74F5f358bc90C73A' as Address,
  oracle: '0x2Cc0Fc26eD4563A5ce5e8bdcfe1A2878676Ae156' as Address,
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

const ORACLE_ABI = [
  {
    inputs: [{ name: 'assets', type: 'address[]' }],
    name: 'getAssetsPrices',
    outputs: [{ name: '', type: 'uint256[]' }],
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
  /** 资产价格 (USD，8位精度原始值) */
  priceRaw: bigint;
  /** 资产价格 (USD 字符串，2位小数) */
  priceUSD: string;
  // 供给
  supplyBalance: string;
  supplyBalanceRaw: bigint;
  /** 供给的 USD 估值 */
  supplyValueUSD: string;
  usageAsCollateralEnabled: boolean;
  // 借贷
  stableDebt: string;
  stableDebtRaw: bigint;
  variableDebt: string;
  variableDebtRaw: bigint;
  totalDebt: string;
  /** 借贷的 USD 估值 */
  totalDebtValueUSD: string;
}

export interface UserPosition {
  summary: AccountSummary;
  reserves: ReservePosition[];
}

// ── 备用 RPC 列表（Base Mainnet，VITE_ETH_RPC_URL 优先）────────────────────────
const PUBLIC_RPCS = [
  'https://mainnet.base.org',
  'https://base.llamarpc.com',
  'https://base.publicnode.com',
  'https://1rpc.io/base',
];

function getClient() {
  const custom = import.meta.env.VITE_ETH_RPC_URL as string | undefined;
  const rpcUrl = custom && custom.trim() ? custom.trim() : PUBLIC_RPCS[0];
  return createPublicClient({
    chain: base,
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
      // 价格字段占位，稍后填充
      priceRaw: 0n,
      priceUSD: '0',
      supplyBalance: parseFloat(formatUnits(currentATokenBalance, decimals)).toFixed(6),
      supplyBalanceRaw: currentATokenBalance,
      supplyValueUSD: '0',
      usageAsCollateralEnabled,
      stableDebt: parseFloat(formatUnits(currentStableDebt, decimals)).toFixed(6),
      stableDebtRaw: currentStableDebt,
      variableDebt: parseFloat(formatUnits(currentVariableDebt, decimals)).toFixed(6),
      variableDebtRaw: currentVariableDebt,
      totalDebt: parseFloat(formatUnits(totalDebtRaw, decimals)).toFixed(6),
      totalDebtValueUSD: '0',
    });
  }

  // 5. 批量查询所有有仓位资产的价格（USD，8位精度）
  if (reserves.length > 0) {
    let prices: readonly bigint[] = [];
    try {
      prices = await client.readContract({
        address: AAVE_ADDRESSES.oracle,
        abi: ORACLE_ABI,
        functionName: 'getAssetsPrices',
        args: [reserves.map((r) => r.tokenAddress)],
      });
    } catch {
      // 价格查询失败不影响主流程，保持 priceUSD = '0'
    }

    for (let i = 0; i < reserves.length; i++) {
      const priceRaw = prices[i] ?? 0n;
      const r = reserves[i];
      const tokenAmt = parseFloat(formatUnits(r.supplyBalanceRaw, r.decimals));
      const debtAmt = parseFloat(formatUnits(r.stableDebtRaw + r.variableDebtRaw, r.decimals));
      const priceNum = parseFloat(formatUnits(priceRaw, 8));

      r.priceRaw = priceRaw;
      r.priceUSD = priceNum.toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: priceNum < 0.01 ? 8 : 2,
      });
      r.supplyValueUSD = (tokenAmt * priceNum).toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
      r.totalDebtValueUSD = (debtAmt * priceNum).toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    }
  }

  return { summary, reserves };
}
