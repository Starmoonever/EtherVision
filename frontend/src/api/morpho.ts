import { apiFetch, apiFetchRaw } from './client';
import type { DataWithMeta } from './requestMeta';

const MORPHO_CACHE_TTL_MS = 5 * 60 * 1000;

export type MorphoProtocol = 'blue';

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
  collateral_decimals?: number | null;
  loan_decimals?: number | null;
  lltv: string | null;
  oracle: string | null;
  irm: string | null;
  pair?: string | null;
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
  loan_symbol?: string | null;
  collateral_symbol?: string | null;
  loan_decimals?: number | null;
  collateral_decimals?: number | null;
  lltv?: string | null;
  oracle?: string | null;
  irm?: string | null;
}

export interface MorphoMarketsResponse {
  markets: MorphoMarketConfig[];
}

interface MorphoMarketListItemApiPayload {
  market_id?: string;
  marketId?: string;
  collateral_symbol?: string | null;
  loan_symbol?: string | null;
  pair?: string | null;
  oracle?: string | null;
  irm?: string | null;
  lltv?: string | null | { ratio?: string | null; raw?: string | null };
  lltv_ratio?: string | null;
  loanToken?: { symbol?: string | null; decimals?: number | null };
  collateralToken?: { symbol?: string | null; decimals?: number | null };
}

interface MorphoMarketListApiPayload {
  markets?: MorphoMarketListItemApiPayload[];
}

interface MorphoMetricApiPayload {
  formula?: string | null;
  value?: string | number | null;
  note?: string | null;
}

interface MorphoMarketStateApiPayload {
  market_id?: string;
  marketId?: string;
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
  loanToken?: { symbol?: string | null; decimals?: number | null };
  collateralToken?: { symbol?: string | null; decimals?: number | null };
}

const morphoPositionCache = new Map<string, { fetchedAt: number; data: MorphoPositionResponse }>();
const morphoPositionInflight = new Map<string, Promise<MorphoPositionResponse>>();
const morphoReplayCache = new Map<
  string,
  { fetchedAt: number; data: MorphoPositionReplayResponse }
>();
const morphoReplayInflight = new Map<string, Promise<MorphoPositionReplayResponse>>();
let morphoMarketsCache: { fetchedAt: number; data: MorphoMarketsResponse } | null = null;
let morphoMarketsInflight: Promise<MorphoMarketsResponse> | null = null;
const morphoMarketStateCache = new Map<string, { fetchedAt: number; data: MorphoMarketState }>();
const morphoMarketStateInflight = new Map<string, Promise<MorphoMarketState>>();

function normalizePairSymbol(pair: string | null | undefined, index: number): string | null {
  if (!pair) return null;
  const parts = pair.split('-');
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

  return {
    market_id: marketId,
    collateral_symbol:
      item.collateral_symbol ?? item.collateralToken?.symbol ?? normalizePairSymbol(item.pair, 1),
    loan_symbol: item.loan_symbol ?? item.loanToken?.symbol ?? normalizePairSymbol(item.pair, 0),
    collateral_decimals: item.collateralToken?.decimals ?? null,
    loan_decimals: item.loanToken?.decimals ?? null,
    lltv: item.lltv_ratio ?? normalizeRatioString(item.lltv),
    oracle: item.oracle ?? null,
    irm: item.irm ?? null,
    pair: item.pair ?? null,
  };
}

function normalizeMorphoMarketState(item: MorphoMarketStateApiPayload): MorphoMarketState {
  const marketId = item.market_id ?? item.marketId ?? '';
  const rawTotalSupplyAssets = normalizeDecimalString(item.totalSupplyAssets);
  const rawTotalBorrowAssets = normalizeDecimalString(item.totalBorrowAssets);
  const displayTotalSupplyAssets = normalizeDecimalString(item.marketScaleTvlLike?.value);
  const displayTotalBorrowAssets = normalizeDecimalString(item.debtScaleDebtLike?.value);
  const displayAvailableLiquidity =
    typeof item.availableLiquidity === 'object' && item.availableLiquidity !== null
      ? normalizeDecimalString(item.availableLiquidity.value)
      : normalizeDecimalString(item.availableLiquidity);

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
    available_liquidity_is_raw:
      typeof item.availableLiquidity === 'object' && item.availableLiquidity !== null
        ? inferMetricIsRaw(item.availableLiquidity, null, [
            'totalSupplyAssets-totalBorrowAssets',
            'totalSupplyAssets',
            'totalBorrowAssets',
          ])
        : false,
    utilization: normalizeMetricValue(item.utilization),
    borrow_capacity_usage_rough: normalizeMetricValue(item.borrowCapacityUsageRough),
    is_liquidatable: typeof item.is_liquidatable === 'boolean' ? item.is_liquidatable : null,
    eth_down_liq_price_usd: normalizeDecimalString(item.eth_down_liq_price_usd),
    loan_symbol: item.loan_symbol ?? item.loanToken?.symbol ?? null,
    collateral_symbol: item.collateral_symbol ?? item.collateralToken?.symbol ?? null,
    loan_decimals: item.loanToken?.decimals ?? null,
    collateral_decimals: item.collateralToken?.decimals ?? null,
    lltv: item.lltv_ratio ?? normalizeRatioString(item.lltv),
    oracle: item.oracle ?? null,
    irm: item.irm ?? null,
  };
}

function buildMorphoPositionCacheKey(
  address: string,
  marketId: string,
  protocol: MorphoProtocol,
): string {
  return `${protocol}:${marketId.toLowerCase()}:${address.toLowerCase()}`;
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

export async function fetchMorphoMarkets(
  options: { force?: boolean } = {},
): Promise<MorphoMarketsResponse> {
  const result = await fetchMorphoMarketsWithMeta(options);
  return result.data;
}

export async function fetchMorphoMarketsWithMeta(
  options: { force?: boolean } = {},
): Promise<DataWithMeta<MorphoMarketsResponse>> {
  const force = options.force === true;

  if (
    !force &&
    morphoMarketsCache &&
    Date.now() - morphoMarketsCache.fetchedAt < MORPHO_CACHE_TTL_MS
  ) {
    return {
      data: morphoMarketsCache.data,
      meta: {
        fetchedAt: morphoMarketsCache.fetchedAt,
        fromCache: true,
      },
    };
  }

  if (!force && morphoMarketsInflight) {
    return morphoMarketsInflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const request = fetchMorphoWithFallback<MorphoMarketListApiPayload>([
    '/morpho/markets',
    '/morpho/market',
  ])
    .then((payload) => ({
      markets: (payload.markets ?? [])
        .map(normalizeMorphoMarketConfig)
        .filter((item): item is MorphoMarketConfig => Boolean(item)),
    }))
    .then((data) => {
      morphoMarketsCache = { fetchedAt: Date.now(), data };
      return data;
    })
    .finally(() => {
      morphoMarketsInflight = null;
    });

  morphoMarketsInflight = request;
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
