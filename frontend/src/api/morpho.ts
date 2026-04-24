import { apiFetch, apiFetchRaw } from './client';
import type { DataWithMeta } from './requestMeta';

const MORPHO_CACHE_TTL_MS = 5 * 60 * 1000;
export const MORPHO_VAULT_SAMPLE_ADDRESS = '0x19b3cD7032B8C062E8d44EaCad661a0970DD8c55';
export const MORPHO_VAULT_V2_SAMPLE_ADDRESS = '0x9a1D6bd5b8642C41F25e0958129B85f8E1176F3e';

export type MorphoProtocol = 'blue';
export type MorphoMarketSortField =
  | 'total_market_size_usd'
  | 'utilization'
  | 'loan_symbol'
  | 'collateral_symbol';
export type MorphoMarketSortOrder = 'asc' | 'desc';

export interface MorphoPositionAsset {
  role: 'loan' | 'collateral' | string;
  token_address: string;
  symbol: string;
  decimals: number;
  amount: string;
  price_usd?: string | null;
  value_usd?: string | null;
}

export interface MorphoPositionResponse {
  protocol: string;
  market_type: string;
  chain: string;
  morpho_address: string;
  market_id: string;
  address: string;
  block_number: number;
  block_timestamp: string;
  has_position: boolean;
  is_healthy: boolean;
  loan_token: string;
  loan_token_symbol: string;
  loan_token_decimals: number;
  collateral_token: string;
  collateral_token_symbol: string;
  collateral_token_decimals: number;
  oracle: string;
  irm: string;
  lltv: string;
  lltv_ratio: string;
  supply_shares: string;
  borrow_shares: string;
  collateral_assets_raw: string;
  supply_assets: string;
  borrow_assets: string;
  collateral_assets: string;
  collateral_value_in_loan_asset: string;
  max_borrowable_in_loan_asset: string;
  health_factor: string | null;
  price_quote: string;
  data_source: string;
  assets: MorphoPositionAsset[];
}

export interface MorphoPositionReplayPoint {
  tx_hash: string;
  timestamp: string;
  block_number: number;
  operation_type: string | null;
  brief: string;
  has_position: boolean;
  is_healthy: boolean;
  collateral_value_in_loan_asset: string;
  borrow_assets: string;
  health_factor: string | null;
  assets: MorphoPositionAsset[];
}

export interface MorphoPositionReplayResponse {
  protocol: string;
  market_type: string;
  chain: string;
  market_id: string;
  address: string;
  from_time: string;
  to_time: string;
  data_source: string;
  total_points: number;
  total_tx_count: number;
  cache_hit_rate: string;
  points: MorphoPositionReplayPoint[];
}

export interface MorphoMarketConfig {
  market_id: string;
  collateral_symbol: string | null;
  loan_symbol: string | null;
  collateral_token_address?: string | null;
  loan_token_address?: string | null;
  collateral_decimals?: number | null;
  loan_decimals?: number | null;
  lltv: string | null;
  oracle: string | null;
  irm: string | null;
  pair?: string | null;
  total_market_size_usd?: string | null;
  utilization?: string | null;
}

export interface MorphoMarketState {
  market_id: string;
  total_collateral_usd: string | null;
  total_debt_usd: string | null;
  total_supply_assets: string | null;
  total_supply_assets_is_raw: boolean;
  total_borrow_assets: string | null;
  total_borrow_assets_is_raw: boolean;
  supply_apy: string | null;
  borrow_apy: string | null;
  available_liquidity: string | null;
  available_liquidity_is_raw: boolean;
  utilization: string | null;
  borrow_capacity_usage_rough: string | null;
  is_liquidatable: boolean | null;
  eth_down_liq_price_usd: string | null;
  total_market_size_usd: string | null;
  loan_symbol?: string | null;
  collateral_symbol?: string | null;
  loan_token_address?: string | null;
  collateral_token_address?: string | null;
  loan_decimals?: number | null;
  collateral_decimals?: number | null;
  lltv?: string | null;
  oracle?: string | null;
  irm?: string | null;
}

export interface MorphoMarketsResponse {
  markets: MorphoMarketConfig[];
  market_count: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface MorphoVaultAsset {
  symbol: string | null;
  address: string | null;
  decimals: number | null;
}

export interface MorphoVaultAllocation {
  market_id: string;
  loan_symbol: string | null;
  loan_address: string | null;
  collateral_symbol: string | null;
  collateral_address: string | null;
  supply_assets: string | null;
  supply_assets_usd: string | null;
  supply_shares: string | null;
  supply_cap: string | null;
  supply_cap_usd: string | null;
  liquidity_usd: string | null;
  allocation_ratio: string | null;
}

export interface MorphoVaultResponse {
  address: string;
  symbol: string | null;
  name: string | null;
  listed: boolean | null;
  chain_id: number | null;
  chain_network: string | null;
  asset: MorphoVaultAsset;
  total_assets: string | null;
  total_assets_raw: string | null;
  total_assets_usd: string | null;
  liquidity_usd: string | null;
  total_supply: string | null;
  share_price: string | null;
  share_price_usd: string | null;
  apy: string | null;
  net_apy: string | null;
  net_apy_excluding_rewards: string | null;
  avg_net_apy: string | null;
  avg_net_apy_excluding_rewards: string | null;
  timelock_seconds: string | null;
  timelock_days: string | null;
  fee: string | null;
  allocations: MorphoVaultAllocation[];
  data_source: 'api';
}

export interface MorphoVaultV2Asset {
  symbol: string | null;
  address: string | null;
  decimals: number | null;
}

export interface MorphoVaultV2Gate {
  address: string | null;
  abdicated: boolean;
  pending_abdication_executable_at: string | null;
  pending_address: string | null;
  pending_executable_at: string | null;
}

export interface MorphoVaultV2GatesConfig {
  send_shares_gate: MorphoVaultV2Gate | null;
  receive_assets_gate: MorphoVaultV2Gate | null;
  receive_shares_gate: MorphoVaultV2Gate | null;
  send_assets_gate: MorphoVaultV2Gate | null;
}

export interface MorphoVaultV2Response {
  id: string | null;
  address: string;
  symbol: string | null;
  name: string | null;
  type: string | null;
  listed: boolean | null;
  creation_block_number: number | null;
  creation_timestamp: string | null;
  asset: MorphoVaultV2Asset;
  total_assets: string | null;
  total_assets_usd: string | null;
  idle_assets: string | null;
  idle_assets_usd: string | null;
  liquidity: string | null;
  liquidity_usd: string | null;
  total_supply: string | null;
  share_price: string | null;
  apy: string | null;
  net_apy: string | null;
  net_apy_excluding_rewards: string | null;
  avg_net_apy: string | null;
  avg_net_apy_excluding_rewards: string | null;
  performance_fee: string | null;
  management_fee: string | null;
  performance_fee_recipient: string | null;
  management_fee_recipient: string | null;
  chain_id: number | null;
  chain_network: string | null;
  owner_address: string | null;
  curator_address: string | null;
  factory_address: string | null;
  gates_config: MorphoVaultV2GatesConfig;
  data_source: 'api';
}

export interface MorphoVaultReallocationPoint {
  date: string;
  reallocation_count: number;
}

export interface MorphoVaultReallocationResponse {
  address: string;
  points: MorphoVaultReallocationPoint[];
  data_source: 'api' | 'mock' | 'empty';
}

interface MorphoMarketListItemApiPayload {
  market_id?: string;
  marketId?: string;
  assets?: Array<{
    asset?: string | null;
    symbol?: string | null;
    token_address?: string | null;
    tokenAddress?: string | null;
    address?: string | null;
    role?: string | null;
    decimals?: number | null;
  }>;
  collateral_symbol?: string | null;
  loan_symbol?: string | null;
  pair?: string | null;
  total_market_size_usd?: string | number | null;
  totalMarketSizeUsd?: string | number | null;
  marketScaleTvlLike?: MorphoMetricApiPayload | null;
  utilization?: { value?: string | number | null } | string | number | null;
  oracle?: string | null;
  irm?: string | null;
  lltv?: string | null | { ratio?: string | null; raw?: string | null };
  lltv_ratio?: string | null;
  loanToken?: { address?: string | null; symbol?: string | null; decimals?: number | null };
  collateralToken?: { address?: string | null; symbol?: string | null; decimals?: number | null };
}

interface MorphoMarketListApiPayload {
  markets?: MorphoMarketListItemApiPayload[];
  market_count?: number | string | null;
  total?: number | string | null;
  total_count?: number | string | null;
  total_pages?: number | string | null;
  totalPages?: number | string | null;
  page?: number | string | null;
  page_size?: number | string | null;
  pageSize?: number | string | null;
  limit?: number | string | null;
  next?: string | null;
  next_page?: number | string | null;
  nextPage?: number | string | null;
  has_next?: boolean | null;
  hasNext?: boolean | null;
}

interface MorphoMetricApiPayload {
  formula?: string | null;
  value?: string | number | null;
  note?: string | null;
}

interface MorphoMarketStateApiPayload {
  market_id?: string;
  marketId?: string;
  total_market_size_usd?: string | number | null;
  totalMarketSizeUsd?: string | number | null;
  liquidityUsd?: string | number | null;
  liquidity_usd?: string | number | null;
  total_collateral_usd?: string | number | null;
  total_debt_usd?: string | number | null;
  totalSupplyAssets?: string | number | null;
  totalBorrowAssets?: string | number | null;
  supply_apy?: string | number | null;
  borrow_apy?: string | number | null;
  is_liquidatable?: boolean | null;
  eth_down_liq_price_usd?: string | number | null;
  marketScaleTvlLike?: MorphoMetricApiPayload | null;
  debtScaleDebtLike?: MorphoMetricApiPayload | null;
  utilization?: { value?: string | number | null } | string | number | null;
  availableLiquidity?: MorphoMetricApiPayload | string | number | null;
  borrowCapacityUsageRough?: { value?: string | number | null } | string | number | null;
  supplyApy?: string | number | null;
  borrowApy?: string | number | null;
  annualSupplyInterestRatio?: { value?: string | number | null } | string | number | null;
  annualSupplyRate?: { value?: string | number | null } | string | number | null;
  annualBorrowInterestRatio?: { value?: string | number | null } | string | number | null;
  annualBorrowRate?: { value?: string | number | null } | string | number | null;
  annualInterestRatio?: { value?: string | number | null } | string | number | null;
  loan_symbol?: string | null;
  collateral_symbol?: string | null;
  oracle?: string | null;
  irm?: string | null;
  lltv?: string | null | { ratio?: string | null; raw?: string | null };
  lltv_ratio?: string | null;
  loanToken?: { address?: string | null; symbol?: string | null; decimals?: number | null };
  collateralToken?: { address?: string | null; symbol?: string | null; decimals?: number | null };
}

interface MorphoVaultApiPayload {
  data?: {
    vaultByAddress?: MorphoVaultByAddressApiPayload | null;
  };
  vault?: MorphoVaultByAddressApiPayload | null;
  vaultByAddress?: MorphoVaultByAddressApiPayload | null;
}

interface MorphoVaultByAddressApiPayload {
  address?: string | null;
  symbol?: string | null;
  name?: string | null;
  listed?: boolean | null;
  asset?: {
    address?: string | null;
    symbol?: string | null;
    decimals?: number | null;
  } | null;
  chain?: {
    id?: number | null;
    network?: string | null;
  } | null;
  state?: {
    totalAssets?: string | number | null;
    totalAssetsUsd?: string | number | null;
    liquidityUsd?: string | number | null;
    liquidity_usd?: string | number | null;
    totalSupply?: string | number | null;
    sharePriceNumber?: string | number | null;
    sharePriceUsd?: string | number | null;
    apy?: string | number | null;
    netApy?: string | number | null;
    netApyExcludingRewards?: string | number | null;
    avgNetApy?: string | number | null;
    avgNetApyExcludingRewards?: string | number | null;
    timelock?: string | number | null;
    fee?: string | number | null;
    allocation?: MorphoVaultAllocationApiPayload[] | null;
  } | null;
}

interface MorphoVaultV2ApiPayload {
  data?: {
    vaultV2ByAddress?: MorphoVaultV2ByAddressApiPayload | null;
  };
  vaultV2ByAddress?: MorphoVaultV2ByAddressApiPayload | null;
}

interface MorphoVaultV2ByAddressApiPayload {
  id?: string | null;
  address?: string | null;
  symbol?: string | null;
  name?: string | null;
  type?: string | null;
  listed?: boolean | null;
  creationBlockNumber?: number | string | null;
  creationTimestamp?: string | null;
  totalAssets?: string | number | null;
  totalSupply?: string | number | null;
  totalAssetsUsd?: string | number | null;
  idleAssets?: string | number | null;
  idleAssetsUsd?: string | number | null;
  liquidity?: string | number | null;
  liquidityUsd?: string | number | null;
  sharePrice?: string | number | null;
  apy?: string | number | null;
  netApy?: string | number | null;
  netApyExcludingRewards?: string | number | null;
  avgNetApy?: string | number | null;
  avgNetApyExcludingRewards?: string | number | null;
  performanceFee?: string | number | null;
  managementFee?: string | number | null;
  performanceFeeRecipient?: string | null;
  managementFeeRecipient?: string | null;
  asset?: {
    address?: string | null;
    symbol?: string | null;
    decimals?: number | null;
  } | null;
  chain?: {
    id?: number | null;
    network?: string | null;
  } | null;
  owner?: { address?: string | null } | null;
  curator?: { address?: string | null } | null;
  factory?: { address?: string | null } | null;
  gatesConfig?: {
    sendSharesGate?: MorphoVaultV2GateApiPayload | null;
    receiveAssetsGate?: MorphoVaultV2GateApiPayload | null;
    receiveSharesGate?: MorphoVaultV2GateApiPayload | null;
    sendAssetsGate?: MorphoVaultV2GateApiPayload | null;
  } | null;
}

interface MorphoVaultV2GateApiPayload {
  address?: string | null;
  abdicated?: boolean | null;
  pendingAbdicationExecutableAt?: string | null;
  pendingAddress?: string | null;
  pendingExecutableAt?: string | null;
}

interface MorphoVaultAllocationApiPayload {
  market?: {
    marketId?: string | null;
    market_id?: string | null;
    uniqueKey?: string | null;
    loanAsset?: {
      symbol?: string | null;
      address?: string | null;
    } | null;
    collateralAsset?: {
      symbol?: string | null;
      address?: string | null;
    } | null;
  } | null;
  supplyAssets?: string | number | null;
  supplyAssetsUsd?: string | number | null;
  liquidityUsd?: string | number | null;
  liquidity_usd?: string | number | null;
  supplyShares?: string | number | null;
  supplyCap?: string | number | null;
  supplyCapUsd?: string | number | null;
}

interface MorphoVaultReallocationApiPayload {
  address?: string | null;
  points?: Array<{
    date?: string | null;
    timestamp?: string | null;
    reallocation_count?: number | string | null;
    count?: number | string | null;
  }> | null;
}

const morphoPositionCache = new Map<string, { fetchedAt: number; data: MorphoPositionResponse }>();
const morphoPositionInflight = new Map<string, Promise<MorphoPositionResponse>>();
const morphoReplayCache = new Map<
  string,
  { fetchedAt: number; data: MorphoPositionReplayResponse }
>();
const morphoReplayInflight = new Map<string, Promise<MorphoPositionReplayResponse>>();
const morphoMarketsCache = new Map<string, { fetchedAt: number; data: MorphoMarketsResponse }>();
const morphoMarketsInflight = new Map<string, Promise<MorphoMarketsResponse>>();
const morphoMarketStateCache = new Map<string, { fetchedAt: number; data: MorphoMarketState }>();
const morphoMarketStateInflight = new Map<string, Promise<MorphoMarketState>>();
const morphoVaultCache = new Map<string, { fetchedAt: number; data: MorphoVaultResponse }>();
const morphoVaultInflight = new Map<string, Promise<MorphoVaultResponse>>();
const morphoVaultV2Cache = new Map<string, { fetchedAt: number; data: MorphoVaultV2Response }>();
const morphoVaultV2Inflight = new Map<string, Promise<MorphoVaultV2Response>>();
const morphoVaultReallocationsCache = new Map<
  string,
  { fetchedAt: number; data: MorphoVaultReallocationResponse }
>();
const morphoVaultReallocationsInflight = new Map<
  string,
  Promise<MorphoVaultReallocationResponse>
>();

function normalizePairSymbol(pair: string | null | undefined, index: number): string | null {
  if (!pair) return null;
  const parts = pair.split(/[-/]/);
  return parts[index]?.trim() || null;
}

function normalizeRatioString(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'object') {
    const ratio = (value as { ratio?: unknown }).ratio;
    return typeof ratio === 'string' && ratio.trim() ? ratio : null;
  }

  const text = String(value).trim();
  if (!text) return null;
  const numeric = Number(text);
  if (!Number.isFinite(numeric)) return text;

  if (numeric > 10_000) {
    return (numeric / 1e18).toString();
  }

  return text;
}

function normalizeDecimalString(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number') {
    return Number.isFinite(value) ? String(value) : null;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed || null;
  }
  return null;
}

function normalizeNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  const numeric = typeof value === 'number' ? value : Number(String(value));
  return Number.isFinite(numeric) ? numeric : null;
}

function normalizeRawAssetAmount(
  value: unknown,
  decimals: number | null | undefined,
): string | null {
  const raw = normalizeDecimalString(value);
  if (!raw) return null;
  const decimalPlaces = decimals ?? 0;
  if (decimalPlaces <= 0) return raw;

  if (/^\d+$/.test(raw)) {
    const padded = raw.padStart(decimalPlaces + 1, '0');
    const whole = padded.slice(0, -decimalPlaces);
    const fraction = padded.slice(-decimalPlaces).replace(/0+$/, '');
    return fraction ? `${whole}.${fraction}` : whole;
  }

  const numeric = Number(raw);
  if (!Number.isFinite(numeric)) return raw;
  return String(numeric / 10 ** decimalPlaces);
}

function normalizeMetricValue(
  value: { value?: string | number | null } | string | number | null | undefined,
): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'object') {
    return normalizeDecimalString(value.value);
  }
  return normalizeDecimalString(value);
}

function inferMetricIsRaw(
  metric: MorphoMetricApiPayload | null | undefined,
  comparedRawValue: string | null,
  rawFieldPatterns: string[],
): boolean {
  if (!metric) return false;

  const metricValue = normalizeDecimalString(metric.value);
  if (metricValue && comparedRawValue && metricValue === comparedRawValue) {
    return true;
  }

  const compactFormula = (metric.formula ?? '').replace(/\s+/g, '');
  if (!compactFormula) return false;

  return rawFieldPatterns.some((pattern) => compactFormula.includes(pattern));
}

async function readApiError(response: Response, path: string): Promise<string> {
  try {
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      const payload = (await response.json()) as { detail?: unknown; message?: unknown };
      if (typeof payload.detail === 'string' && payload.detail.trim()) return payload.detail;
      if (typeof payload.message === 'string' && payload.message.trim()) return payload.message;
    }

    const text = await response.text();
    if (text.trim()) return text;
  } catch {
    // Fall back to generic message below.
  }

  return `API error ${response.status}: ${path}`;
}

async function fetchMorphoWithFallback<T>(paths: string[]): Promise<T> {
  let lastError = 'Morpho API 请求失败';

  for (const path of paths) {
    const response = await apiFetchRaw(path);
    if (response.ok) {
      return response.json() as Promise<T>;
    }
    lastError = await readApiError(response, path);
  }

  throw new Error(lastError);
}

function normalizeMorphoMarketConfig(
  item: MorphoMarketListItemApiPayload,
): MorphoMarketConfig | null {
  const marketId = item.market_id ?? item.marketId;
  if (!marketId) return null;
  const loanAsset = item.assets?.find((asset) => asset.role === 'loan');
  const collateralAsset = item.assets?.find((asset) => asset.role === 'collateral');
  const loanSymbol =
    item.loan_symbol ?? item.loanToken?.symbol ?? loanAsset?.asset ?? loanAsset?.symbol ?? null;
  const collateralSymbol =
    item.collateral_symbol ??
    item.collateralToken?.symbol ??
    collateralAsset?.asset ??
    collateralAsset?.symbol ??
    null;

  return {
    market_id: marketId,
    collateral_symbol: collateralSymbol ?? normalizePairSymbol(item.pair, 0),
    loan_symbol: loanSymbol ?? normalizePairSymbol(item.pair, 1),
    collateral_token_address:
      item.collateralToken?.address ??
      collateralAsset?.token_address ??
      collateralAsset?.tokenAddress ??
      collateralAsset?.address ??
      null,
    loan_token_address:
      item.loanToken?.address ??
      loanAsset?.token_address ??
      loanAsset?.tokenAddress ??
      loanAsset?.address ??
      null,
    collateral_decimals: item.collateralToken?.decimals ?? collateralAsset?.decimals ?? null,
    loan_decimals: item.loanToken?.decimals ?? loanAsset?.decimals ?? null,
    lltv: item.lltv_ratio ?? normalizeRatioString(item.lltv),
    oracle: item.oracle ?? null,
    irm: item.irm ?? null,
    pair:
      collateralSymbol && loanSymbol ? `${collateralSymbol}/${loanSymbol}` : (item.pair ?? null),
    total_market_size_usd: normalizeDecimalString(
      item.total_market_size_usd ?? item.totalMarketSizeUsd,
    ),
    utilization: normalizeMetricValue(item.utilization),
  };
}

function normalizeMorphoMarketState(item: MorphoMarketStateApiPayload): MorphoMarketState {
  const marketId = item.market_id ?? item.marketId ?? '';
  const rawTotalSupplyAssets = normalizeDecimalString(item.totalSupplyAssets);
  const rawTotalBorrowAssets = normalizeDecimalString(item.totalBorrowAssets);
  const displayTotalSupplyAssets = normalizeDecimalString(item.marketScaleTvlLike?.value);
  const displayTotalBorrowAssets = normalizeDecimalString(item.debtScaleDebtLike?.value);
  const displayAvailableLiquidity = normalizeDecimalString(item.liquidityUsd ?? item.liquidity_usd);

  return {
    market_id: marketId,
    total_collateral_usd: normalizeDecimalString(
      item.total_collateral_usd ?? item.marketScaleTvlLike?.value,
    ),
    total_debt_usd: normalizeDecimalString(item.total_debt_usd ?? item.debtScaleDebtLike?.value),
    total_supply_assets: displayTotalSupplyAssets ?? rawTotalSupplyAssets,
    total_supply_assets_is_raw: displayTotalSupplyAssets
      ? inferMetricIsRaw(item.marketScaleTvlLike, rawTotalSupplyAssets, ['totalSupplyAssets'])
      : true,
    total_borrow_assets: displayTotalBorrowAssets ?? rawTotalBorrowAssets,
    total_borrow_assets_is_raw: displayTotalBorrowAssets
      ? inferMetricIsRaw(item.debtScaleDebtLike, rawTotalBorrowAssets, ['totalBorrowAssets'])
      : true,
    supply_apy: normalizeMetricValue(
      item.supply_apy ?? item.supplyApy ?? item.annualSupplyInterestRatio ?? item.annualSupplyRate,
    ),
    borrow_apy: normalizeMetricValue(
      item.borrow_apy ??
        item.borrowApy ??
        item.annualBorrowInterestRatio ??
        item.annualInterestRatio ??
        item.annualBorrowRate,
    ),
    available_liquidity: displayAvailableLiquidity,
    available_liquidity_is_raw: false,
    utilization: normalizeMetricValue(item.utilization),
    borrow_capacity_usage_rough: normalizeMetricValue(item.borrowCapacityUsageRough),
    is_liquidatable: typeof item.is_liquidatable === 'boolean' ? item.is_liquidatable : null,
    eth_down_liq_price_usd: normalizeDecimalString(item.eth_down_liq_price_usd),
    total_market_size_usd: normalizeDecimalString(
      item.total_market_size_usd ?? item.totalMarketSizeUsd,
    ),
    loan_symbol: item.loan_symbol ?? item.loanToken?.symbol ?? null,
    collateral_symbol: item.collateral_symbol ?? item.collateralToken?.symbol ?? null,
    loan_token_address: item.loanToken?.address ?? null,
    collateral_token_address: item.collateralToken?.address ?? null,
    loan_decimals: item.loanToken?.decimals ?? null,
    collateral_decimals: item.collateralToken?.decimals ?? null,
    lltv: item.lltv_ratio ?? normalizeRatioString(item.lltv),
    oracle: item.oracle ?? null,
    irm: item.irm ?? null,
  };
}

function getMorphoVaultPayload(payload: MorphoVaultApiPayload): MorphoVaultByAddressApiPayload {
  const vault = payload.data?.vaultByAddress ?? payload.vaultByAddress ?? payload.vault;
  if (!vault) throw new Error('Morpho vault 数据为空');
  return vault;
}

function getMorphoVaultV2Payload(
  payload: MorphoVaultV2ApiPayload,
): MorphoVaultV2ByAddressApiPayload {
  const vault = payload.data?.vaultV2ByAddress ?? payload.vaultV2ByAddress;
  if (!vault) throw new Error('Morpho vault v2 数据为空');
  return vault;
}

function normalizeMorphoVaultV2Gate(
  gate: MorphoVaultV2GateApiPayload | null | undefined,
): MorphoVaultV2Gate | null {
  if (!gate) return null;
  return {
    address: gate.address ?? null,
    abdicated: gate.abdicated === true,
    pending_abdication_executable_at: gate.pendingAbdicationExecutableAt ?? null,
    pending_address: gate.pendingAddress ?? null,
    pending_executable_at: gate.pendingExecutableAt ?? null,
  };
}

function normalizeMorphoVaultAllocation(
  item: MorphoVaultAllocationApiPayload,
  assetDecimals: number | null | undefined,
  totalAssetsUsd: string | null,
): MorphoVaultAllocation | null {
  const market = item.market;
  const marketId = market?.marketId ?? market?.market_id ?? market?.uniqueKey ?? '';
  if (!marketId) return null;
  const supplyAssetsUsd = normalizeDecimalString(item.supplyAssetsUsd);
  const explicitLiquidityUsd = normalizeDecimalString(item.liquidityUsd ?? item.liquidity_usd);
  const supplyCapUsd = normalizeDecimalString(item.supplyCapUsd);
  const supplyAssetsUsdNumber = normalizeNumber(supplyAssetsUsd);
  const totalAssetsUsdNumber = normalizeNumber(totalAssetsUsd);

  return {
    market_id: marketId,
    loan_symbol: market?.loanAsset?.symbol ?? null,
    loan_address: market?.loanAsset?.address ?? null,
    collateral_symbol: market?.collateralAsset?.symbol ?? null,
    collateral_address: market?.collateralAsset?.address ?? null,
    supply_assets: normalizeRawAssetAmount(item.supplyAssets, assetDecimals),
    supply_assets_usd: supplyAssetsUsd,
    supply_shares: normalizeDecimalString(item.supplyShares),
    supply_cap: normalizeRawAssetAmount(item.supplyCap, assetDecimals),
    supply_cap_usd: supplyCapUsd,
    liquidity_usd: explicitLiquidityUsd,
    allocation_ratio:
      supplyAssetsUsdNumber !== null && totalAssetsUsdNumber !== null && totalAssetsUsdNumber > 0
        ? String(supplyAssetsUsdNumber / totalAssetsUsdNumber)
        : null,
  };
}

function normalizeMorphoVaultResponse(
  payload: MorphoVaultApiPayload,
  dataSource: 'api',
): MorphoVaultResponse {
  const vault = getMorphoVaultPayload(payload);
  const state = vault.state;
  const assetDecimals = vault.asset?.decimals ?? null;
  const totalAssetsUsd = normalizeDecimalString(state?.totalAssetsUsd);
  const explicitVaultLiquidityUsd = normalizeDecimalString(
    state?.liquidityUsd ?? state?.liquidity_usd,
  );
  const timelockSeconds = normalizeDecimalString(state?.timelock);
  const allocations = (state?.allocation ?? [])
    .map((item) => normalizeMorphoVaultAllocation(item, assetDecimals, totalAssetsUsd))
    .filter((item): item is MorphoVaultAllocation => Boolean(item));

  return {
    address: vault.address ?? '',
    symbol: vault.symbol ?? null,
    name: vault.name ?? null,
    listed: typeof vault.listed === 'boolean' ? vault.listed : null,
    chain_id: vault.chain?.id ?? null,
    chain_network: vault.chain?.network ?? null,
    asset: {
      symbol: vault.asset?.symbol ?? null,
      address: vault.asset?.address ?? null,
      decimals: assetDecimals,
    },
    total_assets: normalizeRawAssetAmount(state?.totalAssets, assetDecimals),
    total_assets_raw: normalizeDecimalString(state?.totalAssets),
    total_assets_usd: totalAssetsUsd,
    liquidity_usd: explicitVaultLiquidityUsd,
    total_supply: normalizeDecimalString(state?.totalSupply),
    share_price: normalizeDecimalString(state?.sharePriceNumber),
    share_price_usd: normalizeDecimalString(state?.sharePriceUsd),
    apy: normalizeDecimalString(state?.apy),
    net_apy: normalizeDecimalString(state?.netApy),
    net_apy_excluding_rewards: normalizeDecimalString(state?.netApyExcludingRewards),
    avg_net_apy: normalizeDecimalString(state?.avgNetApy),
    avg_net_apy_excluding_rewards: normalizeDecimalString(state?.avgNetApyExcludingRewards),
    timelock_seconds: timelockSeconds,
    timelock_days:
      timelockSeconds && Number.isFinite(Number(timelockSeconds))
        ? String(Number(timelockSeconds) / 86400)
        : null,
    fee: normalizeDecimalString(state?.fee),
    allocations,
    data_source: dataSource,
  };
}

function normalizeMorphoVaultV2Response(
  payload: MorphoVaultV2ApiPayload,
  dataSource: 'api',
): MorphoVaultV2Response {
  const vault = getMorphoVaultV2Payload(payload);
  const assetDecimals = vault.asset?.decimals ?? null;

  return {
    id: vault.id ?? null,
    address: vault.address ?? '',
    symbol: vault.symbol ?? null,
    name: vault.name ?? null,
    type: vault.type ?? null,
    listed: typeof vault.listed === 'boolean' ? vault.listed : null,
    creation_block_number: normalizeNumber(vault.creationBlockNumber),
    creation_timestamp: vault.creationTimestamp ?? null,
    asset: {
      symbol: vault.asset?.symbol ?? null,
      address: vault.asset?.address ?? null,
      decimals: assetDecimals,
    },
    total_assets: normalizeRawAssetAmount(vault.totalAssets, assetDecimals),
    total_assets_usd: normalizeDecimalString(vault.totalAssetsUsd),
    idle_assets: normalizeRawAssetAmount(vault.idleAssets, assetDecimals),
    idle_assets_usd: normalizeDecimalString(vault.idleAssetsUsd),
    liquidity: normalizeRawAssetAmount(vault.liquidity, assetDecimals),
    liquidity_usd: normalizeDecimalString(vault.liquidityUsd),
    total_supply: normalizeDecimalString(vault.totalSupply),
    share_price: normalizeDecimalString(vault.sharePrice),
    apy: normalizeDecimalString(vault.apy),
    net_apy: normalizeDecimalString(vault.netApy),
    net_apy_excluding_rewards: normalizeDecimalString(vault.netApyExcludingRewards),
    avg_net_apy: normalizeDecimalString(vault.avgNetApy),
    avg_net_apy_excluding_rewards: normalizeDecimalString(vault.avgNetApyExcludingRewards),
    performance_fee: normalizeDecimalString(vault.performanceFee),
    management_fee: normalizeDecimalString(vault.managementFee),
    performance_fee_recipient: vault.performanceFeeRecipient ?? null,
    management_fee_recipient: vault.managementFeeRecipient ?? null,
    chain_id: vault.chain?.id ?? null,
    chain_network: vault.chain?.network ?? null,
    owner_address: vault.owner?.address ?? null,
    curator_address: vault.curator?.address ?? null,
    factory_address: vault.factory?.address ?? null,
    gates_config: {
      send_shares_gate: normalizeMorphoVaultV2Gate(vault.gatesConfig?.sendSharesGate),
      receive_assets_gate: normalizeMorphoVaultV2Gate(vault.gatesConfig?.receiveAssetsGate),
      receive_shares_gate: normalizeMorphoVaultV2Gate(vault.gatesConfig?.receiveSharesGate),
      send_assets_gate: normalizeMorphoVaultV2Gate(vault.gatesConfig?.sendAssetsGate),
    },
    data_source: dataSource,
  };
}

function normalizeMorphoVaultReallocations(
  payload: MorphoVaultReallocationApiPayload,
  fallbackAddress: string,
): MorphoVaultReallocationResponse {
  const points = (payload.points ?? [])
    .map((point) => {
      const count = normalizeNumber(point.reallocation_count ?? point.count);
      const date = point.date ?? point.timestamp?.slice(0, 10) ?? '';
      if (!date || count === null) return null;
      return {
        date,
        reallocation_count: count,
      };
    })
    .filter((item): item is MorphoVaultReallocationPoint => Boolean(item));

  return {
    address: payload.address ?? fallbackAddress,
    points,
    data_source: points.length > 0 ? 'api' : 'empty',
  };
}

function buildMorphoPositionCacheKey(
  address: string,
  marketId: string,
  protocol: MorphoProtocol,
): string {
  return `${protocol}:${marketId.toLowerCase()}:${address.toLowerCase()}`;
}

function parsePositiveInteger(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  const parsed = typeof value === 'number' ? value : Number(String(value));
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return Math.floor(parsed);
}

function appendQueryParams(path: string, params: Record<string, string | number>): string {
  const separator = path.includes('?') ? '&' : '?';
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    query.set(key, String(value));
  });
  return `${path}${separator}${query.toString()}`;
}

function resolveMorphoMarketTotalPages(payload: MorphoMarketListApiPayload): number | null {
  const explicit = parsePositiveInteger(payload.total_pages ?? payload.totalPages);
  if (explicit !== null) return explicit;

  const total = parsePositiveInteger(payload.total ?? payload.total_count ?? payload.market_count);
  const pageSize =
    parsePositiveInteger(payload.page_size ?? payload.pageSize ?? payload.limit) ??
    (payload.markets?.length || null);
  if (total !== null && pageSize !== null && pageSize > 0) {
    return Math.max(1, Math.ceil(total / pageSize));
  }
  return null;
}

function resolveMorphoMarketPageSize(payload: MorphoMarketListApiPayload): number | null {
  return (
    parsePositiveInteger(payload.page_size ?? payload.pageSize ?? payload.limit) ??
    (payload.markets?.length || null)
  );
}

function resolveMorphoMarketTotalCount(
  payload: MorphoMarketListApiPayload,
  fallbackCount: number,
): number {
  return (
    parsePositiveInteger(payload.total ?? payload.total_count ?? payload.market_count) ??
    fallbackCount
  );
}

function normalizeMorphoMarketsResponse(
  payload: MorphoMarketListApiPayload,
  requestedPage: number,
  requestedPageSize: number,
): MorphoMarketsResponse {
  const markets = (payload.markets ?? [])
    .map(normalizeMorphoMarketConfig)
    .filter((item): item is MorphoMarketConfig => Boolean(item));
  const page = parsePositiveInteger(payload.page) ?? requestedPage;
  const pageSize = resolveMorphoMarketPageSize(payload) ?? requestedPageSize;
  const marketCount = resolveMorphoMarketTotalCount(payload, markets.length);
  const totalPages =
    resolveMorphoMarketTotalPages(payload) ??
    Math.max(1, Math.ceil(marketCount / Math.max(1, pageSize)));

  return {
    markets,
    market_count: marketCount,
    page,
    page_size: pageSize,
    total_pages: totalPages,
  };
}

async function fetchMorphoMarketListPagePayload(
  basePath: string,
  page: number,
  pageSize: number,
  sortBy?: MorphoMarketSortField,
  sortOrder?: MorphoMarketSortOrder,
  loan?: string,
  collateral?: string,
): Promise<MorphoMarketListApiPayload> {
  const path = appendQueryParams(basePath, {
    page,
    page_size: pageSize,
    ...(sortBy ? { sort_by: sortBy } : {}),
    ...(sortBy && sortOrder ? { sort_order: sortOrder } : {}),
    ...(loan ? { loan } : {}),
    ...(collateral ? { collateral } : {}),
  });
  const response = await apiFetchRaw(path);
  if (!response.ok) {
    throw new Error(await readApiError(response, path));
  }

  return response.json() as Promise<MorphoMarketListApiPayload>;
}

export async function fetchMorphoPosition(
  address: string,
  marketId: string,
  protocol: MorphoProtocol = 'blue',
  options: { force?: boolean } = {},
): Promise<MorphoPositionResponse> {
  const result = await fetchMorphoPositionWithMeta(address, marketId, protocol, options);
  return result.data;
}

export async function fetchMorphoPositionWithMeta(
  address: string,
  marketId: string,
  protocol: MorphoProtocol = 'blue',
  options: { force?: boolean } = {},
): Promise<DataWithMeta<MorphoPositionResponse>> {
  const key = buildMorphoPositionCacheKey(address, marketId, protocol);
  const cached = morphoPositionCache.get(key);
  const force = options.force === true;

  if (!force && cached && Date.now() - cached.fetchedAt < MORPHO_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = morphoPositionInflight.get(key);
  if (!force && inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const params = new URLSearchParams({
    address,
    market_id: marketId,
    protocol,
  });

  const request = apiFetch<MorphoPositionResponse>(`/morpho/position?${params.toString()}`)
    .then((data) => {
      morphoPositionCache.set(key, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      morphoPositionInflight.delete(key);
    });

  morphoPositionInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

function buildMorphoReplayCacheKey(
  address: string,
  marketId: string,
  start: string,
  end: string,
  protocol: MorphoProtocol,
  detail: boolean,
): string {
  return [
    protocol,
    marketId.toLowerCase(),
    address.toLowerCase(),
    start,
    end,
    detail ? 'detail' : 'summary',
  ].join(':');
}

export async function fetchMorphoPositionReplay(
  address: string,
  marketId: string,
  start: string,
  end: string,
  protocol: MorphoProtocol = 'blue',
  options: { force?: boolean; detail?: boolean; useCache?: boolean } = {},
): Promise<MorphoPositionReplayResponse> {
  const result = await fetchMorphoPositionReplayWithMeta(
    address,
    marketId,
    start,
    end,
    protocol,
    options,
  );
  return result.data;
}

export async function fetchMorphoPositionReplayWithMeta(
  address: string,
  marketId: string,
  start: string,
  end: string,
  protocol: MorphoProtocol = 'blue',
  options: { force?: boolean; detail?: boolean; useCache?: boolean } = {},
): Promise<DataWithMeta<MorphoPositionReplayResponse>> {
  const detail = options.detail === true;
  const useCache = options.useCache !== false;
  const key = buildMorphoReplayCacheKey(address, marketId, start, end, protocol, detail);
  const cached = morphoReplayCache.get(key);
  const force = options.force === true;

  if (!force && cached && Date.now() - cached.fetchedAt < MORPHO_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = morphoReplayInflight.get(key);
  if (!force && inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const params = new URLSearchParams({
    address,
    market_id: marketId,
    start,
    end,
    protocol,
    use_cache: String(useCache),
    detail: String(detail),
  });

  const request = apiFetch<MorphoPositionReplayResponse>(
    `/morpho/position/replay?${params.toString()}`,
  )
    .then((data) => {
      morphoReplayCache.set(key, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      morphoReplayInflight.delete(key);
    });

  morphoReplayInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

function buildMorphoMarketsCacheKey(
  page: number,
  pageSize: number,
  sortBy?: MorphoMarketSortField,
  sortOrder?: MorphoMarketSortOrder,
  loan?: string,
  collateral?: string,
): string {
  return [
    `page:${page}`,
    `pageSize:${pageSize}`,
    `sortBy:${sortBy ?? 'default'}`,
    `sortOrder:${sortOrder ?? 'default'}`,
    `loan:${loan ?? 'default'}`,
    `collateral:${collateral ?? 'default'}`,
  ].join(':');
}

export async function fetchMorphoMarkets(
  options: {
    force?: boolean;
    page?: number;
    pageSize?: number;
    sortBy?: MorphoMarketSortField;
    sortOrder?: MorphoMarketSortOrder;
    loan?: string;
    collateral?: string;
  } = {},
): Promise<MorphoMarketsResponse> {
  const result = await fetchMorphoMarketsWithMeta(options);
  return result.data;
}

export async function fetchMorphoMarketsWithMeta(
  options: {
    force?: boolean;
    page?: number;
    pageSize?: number;
    sortBy?: MorphoMarketSortField;
    sortOrder?: MorphoMarketSortOrder;
    loan?: string;
    collateral?: string;
  } = {},
): Promise<DataWithMeta<MorphoMarketsResponse>> {
  const force = options.force === true;
  const page = parsePositiveInteger(options.page) ?? 1;
  const pageSize = parsePositiveInteger(options.pageSize) ?? 10;
  const sortBy = options.sortBy;
  const sortOrder = sortBy ? (options.sortOrder ?? 'desc') : undefined;
  const loan = options.loan?.trim() || undefined;
  const collateral = options.collateral?.trim() || undefined;
  const cacheKey = buildMorphoMarketsCacheKey(page, pageSize, sortBy, sortOrder, loan, collateral);
  const cached = morphoMarketsCache.get(cacheKey);

  if (!force && cached && Date.now() - cached.fetchedAt < MORPHO_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = morphoMarketsInflight.get(cacheKey);
  if (!force && inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const request = fetchMorphoMarketListPagePayload(
    '/morpho/markets',
    page,
    pageSize,
    sortBy,
    sortOrder,
    loan,
    collateral,
  )
    .catch(() =>
      fetchMorphoMarketListPagePayload(
        '/morpho/market',
        page,
        pageSize,
        sortBy,
        sortOrder,
        loan,
        collateral,
      ),
    )
    .then((payload) => normalizeMorphoMarketsResponse(payload, page, pageSize))
    .then((data) => {
      morphoMarketsCache.set(cacheKey, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      morphoMarketsInflight.delete(cacheKey);
    });

  morphoMarketsInflight.set(cacheKey, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchMorphoMarketState(
  marketId: string,
  options: { force?: boolean } = {},
): Promise<MorphoMarketState> {
  const result = await fetchMorphoMarketStateWithMeta(marketId, options);
  return result.data;
}

export async function fetchMorphoMarketStateWithMeta(
  marketId: string,
  options: { force?: boolean } = {},
): Promise<DataWithMeta<MorphoMarketState>> {
  const normalizedMarketId = marketId.trim().toLowerCase();
  const force = options.force === true;
  const cached = morphoMarketStateCache.get(normalizedMarketId);

  if (!force && cached && Date.now() - cached.fetchedAt < MORPHO_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = morphoMarketStateInflight.get(normalizedMarketId);
  if (!force && inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const params = new URLSearchParams({ market_id: marketId });
  const request = fetchMorphoWithFallback<MorphoMarketStateApiPayload>([
    `/morpho/market/state?${params.toString()}`,
    `/morpho/state?${params.toString()}`,
  ])
    .then(normalizeMorphoMarketState)
    .then((data) => {
      morphoMarketStateCache.set(normalizedMarketId, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      morphoMarketStateInflight.delete(normalizedMarketId);
    });

  morphoMarketStateInflight.set(normalizedMarketId, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchMorphoVault(
  address: string,
  options: { force?: boolean } = {},
): Promise<MorphoVaultResponse> {
  const result = await fetchMorphoVaultWithMeta(address, options);
  return result.data;
}

export async function fetchMorphoVaultWithMeta(
  address: string,
  options: { force?: boolean } = {},
): Promise<DataWithMeta<MorphoVaultResponse>> {
  const normalizedAddress = address.trim().toLowerCase();
  const force = options.force === true;
  const cached = morphoVaultCache.get(normalizedAddress);

  if (!force && cached && Date.now() - cached.fetchedAt < MORPHO_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = morphoVaultInflight.get(normalizedAddress);
  if (!force && inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const params = new URLSearchParams({ address });
  const request = fetchMorphoWithFallback<MorphoVaultApiPayload>([
    `/morpho/vault/v1/state?${params.toString()}`,
  ])
    .then((payload) => normalizeMorphoVaultResponse(payload, 'api'))
    .then((data) => {
      morphoVaultCache.set(normalizedAddress, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      morphoVaultInflight.delete(normalizedAddress);
    });

  morphoVaultInflight.set(normalizedAddress, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchMorphoVaultReallocations(
  address: string,
  options: { force?: boolean; start?: string; end?: string } = {},
): Promise<MorphoVaultReallocationResponse> {
  const normalizedAddress = address.trim().toLowerCase();
  const cacheKey = [normalizedAddress, options.start ?? 'default', options.end ?? 'default'].join(
    ':',
  );
  const force = options.force === true;
  const cached = morphoVaultReallocationsCache.get(cacheKey);

  if (!force && cached && Date.now() - cached.fetchedAt < MORPHO_CACHE_TTL_MS) {
    return cached.data;
  }

  const inflight = morphoVaultReallocationsInflight.get(cacheKey);
  if (!force && inflight) return inflight;

  const params = new URLSearchParams({
    address,
    ...(options.start ? { start: options.start } : {}),
    ...(options.end ? { end: options.end } : {}),
  });
  const request = fetchMorphoWithFallback<MorphoVaultReallocationApiPayload>([
    `/morpho/vault/reallocations?${params.toString()}`,
  ])
    .then((payload) => normalizeMorphoVaultReallocations(payload, address))
    .catch(() => ({
      address,
      points: [],
      data_source: 'empty' as const,
    }))
    .then((data) => {
      morphoVaultReallocationsCache.set(cacheKey, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      morphoVaultReallocationsInflight.delete(cacheKey);
    });

  morphoVaultReallocationsInflight.set(cacheKey, request);
  return request;
}

export async function fetchMorphoVaultV2(
  address: string,
  options: { force?: boolean } = {},
): Promise<MorphoVaultV2Response> {
  const result = await fetchMorphoVaultV2WithMeta(address, options);
  return result.data;
}

export async function fetchMorphoVaultV2WithMeta(
  address: string,
  options: { force?: boolean } = {},
): Promise<DataWithMeta<MorphoVaultV2Response>> {
  const normalizedAddress = address.trim().toLowerCase();
  const force = options.force === true;
  const cached = morphoVaultV2Cache.get(normalizedAddress);

  if (!force && cached && Date.now() - cached.fetchedAt < MORPHO_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = morphoVaultV2Inflight.get(normalizedAddress);
  if (!force && inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const params = new URLSearchParams({ address });
  const request = fetchMorphoWithFallback<MorphoVaultV2ApiPayload>([
    `/morpho/vault/v2/state?${params.toString()}`,
  ])
    .then((payload) => normalizeMorphoVaultV2Response(payload, 'api'))
    .then((data) => {
      morphoVaultV2Cache.set(normalizedAddress, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      morphoVaultV2Inflight.delete(normalizedAddress);
    });

  morphoVaultV2Inflight.set(normalizedAddress, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}
