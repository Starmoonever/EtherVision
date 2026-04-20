import { useEffect, useMemo, useState } from 'react';
import {
  fetchJustLendPositionAnalysisWithMeta,
  type JustLendMarketItem,
  type JustLendPositionAnalysisItem,
} from '../api/justlend';
import type { AggregatedRequestMeta } from '../api/requestMeta';
import { ChartDataStatus } from './ChartAssist';
import { justLendChartTheme } from './justlendTheme';
import { copyToClipboard } from '../shared/utils/copyToClipboard';
import { JustLendPersonalDashboard } from './JustLendPersonalDashboard';

type PositionSide = 'all' | 'collateral' | 'supply' | 'borrow';
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
  side: PositionSide;
  asset: string;
}

interface PositionAnalysisViewItem extends JustLendPositionAnalysisItem {
  healthFactorDisplay: string;
  healthFactorValue: number;
}

const PAGE_SIZE = 50;
const REFRESH_INTERVAL_SECONDS = 5 * 60;
const sortMetricOptions: Array<{
  sortBy: PositionSortBy;
  label: string;
}> = [
  { sortBy: 'total_supply_usd', label: '总存款' },
  { sortBy: 'total_borrow_usd', label: '总借款' },
  { sortBy: 'health_factor', label: '健康因子' },
  { sortBy: 'asset_value_usd', label: '资产价值' },
];
const sideOptions: PositionSide[] = ['all', 'supply', 'borrow', 'collateral'];

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
  if (borrow === 0 && (raw === '0' || health === 0)) return '∞';
  if (raw === 'inf' || raw === 'infinity') return '∞';
  const num = toNum(healthFactor);
  if (!Number.isFinite(num) || num >= 1e12) return '∞';
  return num.toFixed(2);
}

function getHealthFactorValue(
  healthFactor: string | number | null | undefined,
  totalBorrow: string | number | null | undefined,
): number {
  const formatted = formatHealthFactor(healthFactor, totalBorrow);
  if (formatted === '∞') return Infinity;
  const parsed = Number(formatted);
  return Number.isFinite(parsed) ? parsed : 0;
}

function normalizePositionItem(item: JustLendPositionAnalysisItem): PositionAnalysisViewItem {
  return {
    ...item,
    healthFactorDisplay: formatHealthFactor(item.health_factor, item.total_borrow_usd),
    healthFactorValue: getHealthFactorValue(item.health_factor, item.total_borrow_usd),
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

function buildAssetOptions(markets: JustLendMarketItem[]) {
  const seen = new Set<string>();
  return markets
    .filter((item) => item.underlying_address && item.underlying_symbol)
    .filter((item) => {
      const key = item.underlying_address;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort((a, b) => a.underlying_symbol.localeCompare(b.underlying_symbol));
}

function getHealthFactorTone(value: number, display: string) {
  if (display === '∞' || value > 2) {
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
    side: 'all',
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
          side: query.side,
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
    if (sortBy === 'asset_value_usd' && query.side === 'all') {
      setNotice(
        '资产价值排序需要指定具体 Side，已自动切换为 collateral。也可以手动选择 supply 或 borrow。',
      );
      updateQuery({ sortBy, side: 'collateral', page: 1 });
      return;
    }
    setNotice('');
    updateQuery({ sortBy, page: 1 });
  };

  const handleAssetChange = (asset: string) => {
    setError('');
    setNotice('');
    updateQuery({ asset, page: 1 });
  };

  const handleSideChange = (side: PositionSide) => {
    if (query.sortBy === 'asset_value_usd' && side === 'all') {
      setNotice('资产价值排序需要指定具体 Side，请选择 supply、borrow 或 collateral。');
      return;
    }
    setError('');
    setNotice('');
    updateQuery({ side, page: 1 });
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
                <option key={item.underlying_address} value={item.underlying_address}>
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
            <div className="switch-group" aria-label="JustLend position side">
              {sideOptions.map((side) => (
                <button
                  key={side}
                  type="button"
                  className={`switch-btn ${query.side === side ? 'active' : ''}`}
                  onClick={() => handleSideChange(side)}
                >
                  {side}
                </button>
              ))}
            </div>
          </div>

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
                <th className="right">健康因子</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: '2rem' }}>
                    <div className="spinner"></div>
                  </td>
                </tr>
              ) : items.length ? (
                items.map((item, index) => {
                  const supply = toNum(item.total_supply_usd);
                  const borrow = toNum(item.total_borrow_usd);
                  const hf = item.healthFactorValue;
                  const risky = Number.isFinite(hf) && hf <= 1.1;
                  const hfTone = getHealthFactorTone(hf, item.healthFactorDisplay);
                  return (
                    <tr
                      key={`${item.address}:${query.page}:${index}`}
                      className={risky ? 'justlend-risk-row' : ''}
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
                        className={`right mono ${hfTone.className}`}
                        style={{ color: hfTone.color, fontWeight: hfTone.fontWeight }}
                      >
                        {item.healthFactorDisplay}
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: '2rem' }}>
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

            <JustLendPersonalDashboard address={drawerAddress} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
