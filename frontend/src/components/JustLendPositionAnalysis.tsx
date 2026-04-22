import { useEffect, useMemo, useState } from 'react';
import {
  fetchJustLendPositionAnalysisWithMeta,
  type JustLendMarketItem,
  type JustLendPositionAnalysisItem,
} from '../api/justlend';
import type { AggregatedRequestMeta } from '../api/requestMeta';
import { ChartDataStatus, ChartInfoButton, type ExplainItem } from './ChartAssist';
import { justLendChartTheme } from './justlendTheme';
import { copyToClipboard } from '../shared/utils/copyToClipboard';
import { JustLendPersonalDashboard } from './JustLendPersonalDashboard';

type PositionType = 'all' | 'supply' | 'borrow';
type SupplyCollateralFilter = 'all' | 'collateral' | 'not_collateral';
type PositionSortBy =
  | 'health_factor'
  | 'total_supply_usd'
  | 'total_collateral_usd'
  | 'total_borrow_usd'
  | 'asset_value_usd';
type SortOrder = 'asc' | 'desc';

interface JustLendPositionAnalysisProps {
  markets: JustLendMarketItem[];
}

interface PositionQuery {
  page: number;
  pageSize: number;
  sortBy: PositionSortBy;
  order: SortOrder;
  positionType: PositionType;
  supplyCollateralFilter: SupplyCollateralFilter;
  asset: string;
}

interface PositionAnalysisViewItem extends JustLendPositionAnalysisItem {
  healthFactorDisplay: string;
  healthFactorValue: number;
  healthFactorBlink: boolean;
  healthFactorNativeInfinity: boolean;
  ltvPct: number | null;
  ltvDisplay: string;
  liquidationThresholdPct: number | null;
  liquidationThresholdDisplay: string;
  riskBufferPct: number | null;
  riskBufferDisplay: string;
}

const PAGE_SIZE = 50;
const REFRESH_INTERVAL_SECONDS = 5 * 60;
const TRX_NATIVE_ASSET_ADDRESS = 'T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb';
const sortMetricOptions: Array<{
  sortBy: PositionSortBy;
  label: string;
}> = [
  { sortBy: 'total_supply_usd', label: '总存款' },
  { sortBy: 'total_borrow_usd', label: '总借款' },
  { sortBy: 'total_collateral_usd', label: '总抵押' },
  { sortBy: 'health_factor', label: '健康因子' },
  { sortBy: 'asset_value_usd', label: '资产价值' },
];
const positionTypeOptions: PositionType[] = ['all', 'supply', 'borrow'];
const supplyCollateralOptions: SupplyCollateralFilter[] = ['all', 'collateral', 'not_collateral'];
const healthFactorExplainItems: ExplainItem[] = [
  {
    term: '黄色闪烁',
    meaning: '表示健康因子低于 1.1，仓位已进入高风险区。',
    riskHint: '表示接近清算边界的账户地址。',
  },
  {
    term: '绿色闪烁无风险',
    meaning: '表示∞健康因子。',
    riskHint: '这类账户单独高亮为原生无风险仓位。',
  },
  {
    term: '绿色静态无风险',
    meaning: '表示健康因子>5 和 <∞的账户。',
    riskHint: '这类地址作为健康因子大于5小于∞的标识。',
  },
];

function toNum(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const raw = String(value).trim().toLowerCase();
  if (raw === 'inf' || raw === 'infinity') return Infinity;
  const parsed = typeof value === 'number' ? value : Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatFullCurrency(value: number): string {
  if (!Number.isFinite(value)) return '--';
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatUsd(value: number): string {
  return formatFullCurrency(value);
}

function compactNumber(value: number): string {
  if (!Number.isFinite(value)) return '--';
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatHealthFactor(
  healthFactor: string | number | null | undefined,
  totalBorrow: string | number | null | undefined,
): string {
  const raw = String(healthFactor ?? '')
    .trim()
    .toLowerCase();
  const borrow = Number(totalBorrow);
  const health = Number(healthFactor);
  if (borrow === 0 && (raw === '0' || health === 0)) return '无风险';
  if (raw === 'inf' || raw === 'infinity') return '无风险';
  const num = toNum(healthFactor);
  if (!Number.isFinite(num) || num > 5) return '无风险';
  return num.toFixed(2);
}

function getHealthFactorValue(
  healthFactor: string | number | null | undefined,
  totalBorrow: string | number | null | undefined,
): number {
  const raw = String(healthFactor ?? '')
    .trim()
    .toLowerCase();
  const borrow = Number(totalBorrow);
  const numericValue = Number(healthFactor);

  if (raw === 'inf' || raw === 'infinity') return Infinity;
  if (borrow === 0 && numericValue === 0) return Infinity;
  if (Number.isFinite(numericValue)) return numericValue;

  const fallback = toNum(healthFactor);
  return Number.isFinite(fallback) ? fallback : 0;
}

function shouldBlinkHealthFactorInfinity(
  healthFactor: string | number | null | undefined,
  totalBorrow: string | number | null | undefined,
  totalSupply: string | number | null | undefined,
  totalCollateral: string | number | null | undefined,
): boolean {
  if (formatHealthFactor(healthFactor, totalBorrow) !== '无风险') return false;

  const borrow = toNum(totalBorrow);
  const supply = toNum(totalSupply);
  const collateral = toNum(totalCollateral);
  if (borrow === 0 && (supply > 0 || collateral > 0)) return true;

  const parsed = Number(healthFactor);
  if (Number.isFinite(parsed) && parsed > 5) return false;

  return true;
}

function isNativeHealthFactorInfinity(
  healthFactor: string | number | null | undefined,
  totalBorrow: string | number | null | undefined,
  totalSupply: string | number | null | undefined,
  totalCollateral: string | number | null | undefined,
): boolean {
  if (formatHealthFactor(healthFactor, totalBorrow) !== '无风险') return false;

  const raw = String(healthFactor ?? '')
    .trim()
    .toLowerCase();
  if (raw === 'inf' || raw === 'infinity') return true;

  const borrow = toNum(totalBorrow);
  const supply = toNum(totalSupply);
  const collateral = toNum(totalCollateral);
  const parsed = Number(healthFactor);
  return borrow === 0 && parsed === 0 && (supply > 0 || collateral > 0);
}

function normalizePercentValue(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const raw = String(value).trim().toLowerCase();
  if (!raw || raw === 'inf' || raw === 'infinity') return null;
  const parsed = Number.parseFloat(raw);
  if (!Number.isFinite(parsed)) return null;
  return parsed <= 1 ? parsed * 100 : parsed;
}

function formatPercentValue(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '--';
  return `${value.toFixed(2)}%`;
}

function normalizePositionItem(item: JustLendPositionAnalysisItem): PositionAnalysisViewItem {
  const ltvPct = normalizePercentValue(item.ltv);
  const liquidationThresholdPct = normalizePercentValue(item.liquidation_threshold);
  const riskBufferPct =
    ltvPct !== null && liquidationThresholdPct !== null ? liquidationThresholdPct - ltvPct : null;

  return {
    ...item,
    healthFactorDisplay: formatHealthFactor(item.health_factor, item.total_borrow_usd),
    healthFactorValue: getHealthFactorValue(item.health_factor, item.total_borrow_usd),
    healthFactorBlink: shouldBlinkHealthFactorInfinity(
      item.health_factor,
      item.total_borrow_usd,
      item.total_supply_usd,
      item.total_collateral_usd,
    ),
    healthFactorNativeInfinity: isNativeHealthFactorInfinity(
      item.health_factor,
      item.total_borrow_usd,
      item.total_supply_usd,
      item.total_collateral_usd,
    ),
    ltvPct,
    ltvDisplay: formatPercentValue(ltvPct),
    liquidationThresholdPct,
    liquidationThresholdDisplay: formatPercentValue(liquidationThresholdPct),
    riskBufferPct,
    riskBufferDisplay: formatPercentValue(riskBufferPct),
  };
}

function getSortValue(item: PositionAnalysisViewItem, sortBy: PositionSortBy): number {
  if (sortBy === 'total_supply_usd') return toNum(item.total_supply_usd);
  if (sortBy === 'total_borrow_usd') return toNum(item.total_borrow_usd);
  if (sortBy === 'health_factor') return item.healthFactorValue;
  if (sortBy === 'asset_value_usd') return toNum(item.matched_asset_value_usd);
  if (sortBy === 'total_collateral_usd') return toNum(item.total_collateral_usd);
  return 0;
}

function compareSortValues(valueA: number, valueB: number, order: SortOrder): number {
  if (valueA === valueB) return 0;
  if (valueA === Infinity) return order === 'asc' ? 1 : -1;
  if (valueB === Infinity) return order === 'asc' ? -1 : 1;
  return order === 'asc' ? valueA - valueB : valueB - valueA;
}

function sortPositionItems(
  items: PositionAnalysisViewItem[],
  sortBy: PositionSortBy,
  order: SortOrder,
): PositionAnalysisViewItem[] {
  return [...items].sort((a, b) =>
    compareSortValues(getSortValue(a, sortBy), getSortValue(b, sortBy), order),
  );
}

function formatCountdown(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const restSeconds = seconds % 60;
  return `${minutes}:${String(restSeconds).padStart(2, '0')}`;
}

function shortAddress(value: string): string {
  if (value.length <= 14) return value;
  return `${value.slice(0, 7)}...${value.slice(-6)}`;
}

function resolveUnderlyingAssetAddress(item: JustLendMarketItem): string {
  if (item.underlying_address) return item.underlying_address;
  if ((item.underlying_symbol || '').trim().toUpperCase() === 'TRX') {
    return TRX_NATIVE_ASSET_ADDRESS;
  }
  return '';
}

function buildAssetOptions(markets: JustLendMarketItem[]) {
  const seen = new Set<string>();
  return markets
    .filter((item) => item.underlying_symbol && resolveUnderlyingAssetAddress(item))
    .filter((item) => {
      const key = resolveUnderlyingAssetAddress(item);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort((a, b) => a.underlying_symbol.localeCompare(b.underlying_symbol));
}

function getHealthFactorTone(value: number, display: string) {
  if (display === '无风险' || value > 2) {
    return { color: '#22c55e', className: '', fontWeight: 800 };
  }
  if (value <= 1.1) {
    return { color: '#FFBB28', className: 'justlend-hf-pulse', fontWeight: 900 };
  }
  if (value <= 1.5) {
    return { color: '#f59e0b', className: '', fontWeight: 800 };
  }
  return { color: '#e2e8f0', className: '', fontWeight: 700 };
}

export function JustLendPositionAnalysis({ markets }: JustLendPositionAnalysisProps) {
  const [query, setQuery] = useState<PositionQuery>({
    page: 1,
    pageSize: PAGE_SIZE,
    sortBy: 'total_supply_usd',
    order: 'desc',
    positionType: 'all',
    supplyCollateralFilter: 'all',
    asset: '',
  });
  const [items, setItems] = useState<PositionAnalysisViewItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [meta, setMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });
  const [copiedAddress, setCopiedAddress] = useState('');
  const [drawerAddress, setDrawerAddress] = useState('');
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [refreshCountdown, setRefreshCountdown] = useState(REFRESH_INTERVAL_SECONDS);

  const assetOptions = useMemo(() => buildAssetOptions(markets), [markets]);
  const totalPages = Math.max(1, Math.ceil(total / query.pageSize));
  const currentPageSupplyTotal = useMemo(
    () => items.reduce((sum, item) => sum + toNum(item.total_supply_usd), 0),
    [items],
  );
  const activeSortLabel =
    sortMetricOptions.find((option) => option.sortBy === query.sortBy)?.label ?? '总存款';
  const orderLabel = query.order === 'desc' ? '降序' : '升序';
  const displayTitle = useMemo(() => {
    if (query.sortBy === 'total_collateral_usd') return '核心抵押头寸 (Top Collateral Positions)';
    if (query.sortBy === 'total_supply_usd') return '顶级供给头寸 (Top Supply Positions)';
    if (query.sortBy === 'total_borrow_usd') return '主要借款头寸 (Main Borrowing Positions)';
    return '核心头寸透视 (Core Positions Insight)';
  }, [query.sortBy]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError('');
      try {
        const result = await fetchJustLendPositionAnalysisWithMeta({
          page: query.page,
          pageSize: query.pageSize,
          sortBy: query.sortBy,
          order: query.order,
          positionType: query.positionType,
          isCollateral:
            query.positionType === 'supply'
              ? query.supplyCollateralFilter === 'collateral'
                ? true
                : query.supplyCollateralFilter === 'not_collateral'
                  ? false
                  : null
              : null,
          asset: query.asset || null,
          detail: false,
          forceRefresh: refreshNonce > 0,
        });
        if (cancelled) return;
        const nextItems = sortPositionItems(
          (result.data.items ?? []).map(normalizePositionItem),
          query.sortBy,
          query.order,
        );
        setTotal(result.data.total ?? 0);
        setItems(nextItems);
        setMeta({
          lastUpdatedAt: result.meta.fetchedAt,
          cacheStatus: result.meta.fromCache ? 'hit' : 'miss',
        });
      } catch (loadError) {
        if (cancelled) return;
        setItems([]);
        setTotal(0);
        setError(loadError instanceof Error ? loadError.message : '无法加载 JustLend 仓位列表');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [query, refreshNonce]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setRefreshCountdown((current) => {
        if (current <= 1) {
          setRefreshNonce((nonce) => nonce + 1);
          return REFRESH_INTERVAL_SECONDS;
        }
        return current - 1;
      });
    }, 1000);

    return () => window.clearInterval(timer);
  }, []);

  const updateQuery = (patch: Partial<PositionQuery>) => {
    setQuery((current) => ({
      ...current,
      page: patch.page ?? 1,
      ...patch,
    }));
  };

  const handleSortMetricChange = (sortBy: PositionSortBy) => {
    if (sortBy === 'asset_value_usd' && !query.asset) {
      setNotice('请先选择一个 Asset，再按资产价值排序。');
      return;
    }
    setError('');
    if (sortBy === 'asset_value_usd' && query.positionType === 'all') {
      setNotice(
        '资产价值排序需要指定具体仓位类型，已自动切换为 supply + collateral。也可以手动选择 borrow 或调整 collateral 过滤。',
      );
      updateQuery({
        sortBy,
        positionType: 'supply',
        supplyCollateralFilter: 'collateral',
        page: 1,
      });
      return;
    }
    setNotice('');
    updateQuery({ sortBy, page: 1 });
  };

  const handleAssetChange = (asset: string) => {
    setError('');
    setNotice('');
    if (!asset && query.sortBy === 'asset_value_usd') {
      updateQuery({ asset, sortBy: 'total_supply_usd', page: 1 });
      return;
    }
    updateQuery({ asset, page: 1 });
  };

  const handlePositionTypeChange = (positionType: PositionType) => {
    if (query.sortBy === 'asset_value_usd' && positionType === 'all') {
      setNotice('资产价值排序需要指定具体仓位类型，请选择 supply 或 borrow。');
      return;
    }
    setError('');
    setNotice('');
    updateQuery({
      positionType,
      supplyCollateralFilter: positionType === 'supply' ? query.supplyCollateralFilter : 'all',
      page: 1,
    });
  };

  const handleSupplyCollateralFilterChange = (filter: SupplyCollateralFilter) => {
    setError('');
    setNotice('');
    updateQuery({
      positionType: 'supply',
      supplyCollateralFilter: filter,
      page: 1,
    });
  };

  const handleSortOrderChange = (order: SortOrder) => {
    updateQuery({ order, page: 1 });
  };

  const handlePageSizeChange = (pageSize: number) => {
    updateQuery({ pageSize, page: 1 });
  };

  const handleManualRefresh = () => {
    setRefreshCountdown(REFRESH_INTERVAL_SECONDS);
    setRefreshNonce((nonce) => nonce + 1);
  };

  const handleCopy = async (address: string) => {
    const copied = await copyToClipboard(address);
    if (!copied) return;
    setCopiedAddress(address);
    window.setTimeout(() => {
      setCopiedAddress((current) => (current === address ? '' : current));
    }, 1400);
  };

  return (
    <div className="justlend-market-board">
      <div className="card" style={{ marginBottom: 0 }}>
        <div className="card-header" style={{ gap: '1rem', flexWrap: 'wrap' }}>
          <div>
            <span className="card-title">{displayTitle}</span>
            <div className="justlend-market-copy" style={{ marginTop: '0.35rem' }}>
              实时追踪 JustLend 协议中高净值账户的资产分布、健康系数及潜在风险。
            </div>
          </div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              flexWrap: 'wrap',
              justifyContent: 'flex-end',
            }}
          >
            <ChartDataStatus meta={meta} />
            <span
              className="badge"
              style={{
                ...justLendChartTheme.badge.neutral,
                padding: '0.22rem 0.6rem',
                fontSize: '0.72rem',
                lineHeight: 1.2,
              }}
            >
              {formatCountdown(refreshCountdown)} 自动刷新
            </span>
            <button
              type="button"
              className="switch-btn active"
              onClick={handleManualRefresh}
              disabled={loading}
              title="立即同步"
              style={{ padding: '0.22rem 0.6rem', fontSize: '0.72rem', lineHeight: 1.2 }}
            >
              立即同步
            </button>
          </div>
        </div>

        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-end',
            gap: '1rem',
            flexWrap: 'wrap',
            marginTop: '1rem',
          }}
        >
          <label style={{ display: 'grid', gap: '0.35rem', minWidth: 220 }}>
            <span className="metric-label">Asset</span>
            <select
              value={query.asset}
              onChange={(event) => handleAssetChange(event.target.value)}
              style={{
                background: '#0f172a',
                border: '1px solid #334155',
                color: '#e2e8f0',
                borderRadius: '8px',
                padding: '0.55rem 0.65rem',
              }}
            >
              <option value="">全部资产</option>
              {assetOptions.map((item) => (
                <option
                  key={resolveUnderlyingAssetAddress(item)}
                  value={resolveUnderlyingAssetAddress(item)}
                >
                  {item.underlying_symbol}
                </option>
              ))}
            </select>
          </label>

          <div style={{ display: 'grid', gap: '0.35rem' }}>
            <span className="metric-label">排序维度 (Sort By)</span>
            <div className="switch-group" aria-label="JustLend position sort metric">
              {sortMetricOptions.map((option) => (
                <button
                  key={option.sortBy}
                  type="button"
                  className={`switch-btn ${query.sortBy === option.sortBy ? 'active' : ''}`}
                  onClick={() => handleSortMetricChange(option.sortBy)}
                  title={
                    option.sortBy === 'asset_value_usd'
                      ? '按当前选择 Asset 的持有价值排序'
                      : option.label
                  }
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div style={{ display: 'grid', gap: '0.35rem' }}>
            <span className="metric-label">Side</span>
            <div className="switch-group" aria-label="JustLend position type">
              {positionTypeOptions.map((positionType) => (
                <button
                  key={positionType}
                  type="button"
                  className={`switch-btn ${query.positionType === positionType ? 'active' : ''}`}
                  onClick={() => handlePositionTypeChange(positionType)}
                >
                  {positionType}
                </button>
              ))}
            </div>
          </div>

          {query.positionType === 'supply' ? (
            <div style={{ display: 'grid', gap: '0.35rem' }}>
              <span className="metric-label">Collateral</span>
              <div className="switch-group" aria-label="JustLend supply collateral filter">
                {supplyCollateralOptions.map((filter) => (
                  <button
                    key={filter}
                    type="button"
                    className={`switch-btn ${query.supplyCollateralFilter === filter ? 'active' : ''}`}
                    onClick={() => handleSupplyCollateralFilterChange(filter)}
                  >
                    {filter}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div style={{ display: 'grid', gap: '0.35rem' }}>
            <span className="metric-label">排序方向</span>
            <div className="switch-group" aria-label="JustLend position sort order">
              <button
                type="button"
                className={`switch-btn ${query.order === 'desc' ? 'active' : ''}`}
                onClick={() => handleSortOrderChange('desc')}
              >
                ↓ 从高到低
              </button>
              <button
                type="button"
                className={`switch-btn ${query.order === 'asc' ? 'active' : ''}`}
                onClick={() => handleSortOrderChange('asc')}
              >
                ↑ 从低到高
              </button>
            </div>
          </div>
        </div>

        <div className="summary-grid protocol-summary-grid" style={{ marginTop: '1rem' }}>
          <div className="metric-box">
            <span className="metric-label">当前页总覆盖资金量</span>
            <span className="metric-value green" title={formatUsd(currentPageSupplyTotal)}>
              {compactNumber(currentPageSupplyTotal)}
            </span>
          </div>
          <div className="metric-box">
            <span className="metric-label">当前页地址数</span>
            <label className="justlend-page-size-control">
              <select
                value={query.pageSize}
                onChange={(event) => handlePageSizeChange(Number(event.target.value))}
                aria-label="选择每页地址数量"
              >
                {[20, 50, 100, 200].map((size) => (
                  <option key={size} value={size}>
                    {size}
                  </option>
                ))}
              </select>
              <span className="justlend-page-size-arrow">▾</span>
            </label>
          </div>
          <div className="metric-box">
            <span className="metric-label">当前视图</span>
            <span className="metric-value justlend-current-view-value">
              {`${activeSortLabel}${orderLabel}排位`}
            </span>
          </div>
        </div>

        {error ? (
          <div className="justlend-banner justlend-banner-warn" style={{ marginTop: '1rem' }}>
            <div className="justlend-banner-title">无法读取仓位列表</div>
            <div className="justlend-banner-copy">{error}</div>
          </div>
        ) : null}

        {notice ? (
          <div className="justlend-banner justlend-banner-soft" style={{ marginTop: '1rem' }}>
            <div className="justlend-banner-title">需要选择资产</div>
            <div className="justlend-banner-copy">{notice}</div>
          </div>
        ) : null}

        <div className="table-wrap justlend-position-table-wrap" style={{ marginTop: '1rem' }}>
          <table className="pos-table">
            <thead>
              <tr>
                <th>排名</th>
                <th>地址</th>
                <th className="right">总存款</th>
                <th className="right">总借款</th>
                <th className="right">
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'flex-end',
                      gap: '0.4rem',
                    }}
                  >
                    <span>健康因子</span>
                    <ChartInfoButton title="健康因子显示说明" items={healthFactorExplainItems} />
                  </span>
                </th>
                <th className="right">LTV</th>
                <th className="right">匹配资产价值</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', padding: '2rem' }}>
                    <div className="spinner"></div>
                  </td>
                </tr>
              ) : items.length ? (
                items.map((item, index) => {
                  const supply = toNum(item.total_supply_usd);
                  const borrow = toNum(item.total_borrow_usd);
                  const matchedAssetValue = toNum(item.matched_asset_value_usd);
                  const hf = item.healthFactorValue;
                  const hfTone = getHealthFactorTone(hf, item.healthFactorDisplay);
                  const healthFactorClassName = [
                    hfTone.className,
                    item.healthFactorDisplay === '无风险' && item.healthFactorBlink
                      ? 'justlend-hf-pulse-safe'
                      : '',
                    item.healthFactorNativeInfinity ? 'justlend-hf-native-infinity' : '',
                  ]
                    .filter(Boolean)
                    .join(' ');
                  return (
                    <tr
                      key={`${item.address}:${query.page}:${index}`}
                      onClick={() => setDrawerAddress(item.address)}
                      style={{
                        cursor: 'pointer',
                      }}
                    >
                      <td>{(query.page - 1) * query.pageSize + index + 1}</td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          <span className="mono" title={item.address}>
                            {shortAddress(item.address)}
                          </span>
                          <button
                            type="button"
                            className={`switch-btn ${copiedAddress === item.address ? 'active' : ''}`}
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleCopy(item.address);
                            }}
                            style={{ padding: '0.2rem 0.45rem', fontSize: '0.72rem' }}
                          >
                            {copiedAddress === item.address ? 'Success' : '复制'}
                          </button>
                        </div>
                      </td>
                      <td className="right mono" title={formatFullCurrency(supply)}>
                        {formatFullCurrency(supply)}
                      </td>
                      <td className="right mono" title={formatFullCurrency(borrow)}>
                        {formatFullCurrency(borrow)}
                      </td>
                      <td
                        className={`right mono ${healthFactorClassName}`}
                        style={{ color: hfTone.color, fontWeight: hfTone.fontWeight }}
                      >
                        {item.healthFactorDisplay}
                      </td>
                      <td className="right mono" title={item.ltvDisplay}>
                        {item.ltvDisplay}
                      </td>
                      <td className="right mono" title={formatFullCurrency(matchedAssetValue)}>
                        {formatFullCurrency(matchedAssetValue)}
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', padding: '2rem' }}>
                    暂无匹配仓位
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '1rem',
            marginTop: '1rem',
            color: '#94a3b8',
            flexWrap: 'wrap',
          }}
        >
          <span>
            共 {total.toLocaleString()} 条，当前第 {query.page} / {totalPages} 页
          </span>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              type="button"
              className="switch-btn"
              disabled={query.page <= 1 || loading}
              onClick={() => updateQuery({ page: Math.max(1, query.page - 1) })}
            >
              上一页
            </button>
            <button
              type="button"
              className="switch-btn"
              disabled={query.page >= totalPages || loading}
              onClick={() => updateQuery({ page: Math.min(totalPages, query.page + 1) })}
            >
              下一页
            </button>
          </div>
        </div>
      </div>

      {drawerAddress ? (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(2, 6, 23, 0.68)',
            zIndex: 120,
            display: 'flex',
            justifyContent: 'flex-end',
          }}
          onClick={() => {
            setDrawerAddress('');
          }}
        >
          <div
            className="justlend-personal-analysis-drawer"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="card-header justlend-portrait-header">
              <div>
                <span className="card-title">JustLend 个人账户分析</span>
                <div className="mono justlend-portrait-address">{drawerAddress}</div>
              </div>
              <button
                type="button"
                className="justlend-portrait-close"
                onClick={() => setDrawerAddress('')}
                aria-label="关闭用户画像"
              >
                ×
              </button>
            </div>

            <JustLendPersonalDashboard address={drawerAddress} showReplayAnalysis={false} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
