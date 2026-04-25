import {
  Fragment,
  useEffect,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { MorphoMarketView } from '../../../hooks/useMorphoData';
import { copyToClipboard } from '../../../shared/utils/copyToClipboard';

export type MorphoSortMode =
  | 'default'
  | 'loanSymbolAsc'
  | 'loanSymbolDesc'
  | 'collateralSymbolAsc'
  | 'collateralSymbolDesc'
  | 'totalMarketSizeDesc'
  | 'totalMarketSizeAsc'
  | 'utilizationDesc'
  | 'utilizationAsc';

interface MorphoMarketTableProps {
  markets: MorphoMarketView[];
  expandedMarketId: string;
  onToggleMarket: (market: MorphoMarketView) => void;
  marketStateLoadingById: Record<string, boolean>;
  marketStateErrorById: Record<string, string>;
  title?: string;
  subtitle?: string;
  search?: string;
  onSearchChange?: (value: string) => void;
  onSearchSubmit?: () => void;
  searchPlaceholder?: string;
  marketFilters?: {
    loan: string;
    collateral: string;
  };
  onMarketFilterCommit?: (filters: { loan: string; collateral: string }) => void;
  sortMode: MorphoSortMode;
  onSortModeChange: (value: MorphoSortMode) => void;
  totalMarkets: number;
  page: number;
  totalPages: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  showSorting?: boolean;
  showPagination?: boolean;
  showColumnHeaders?: boolean;
  showSummaryRows?: boolean;
  showTableHeaderWhenEmpty?: boolean;
  emptyText?: string;
  tableError?: string;
  embedded?: boolean;
  forceExpanded?: boolean;
  statusMeta?: ReactNode;
  searchHistoryItems?: string[];
  onSearchHistorySelect?: (value: string) => void;
  onClearSearchHistory?: () => void;
}

const percentFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const MORPHO_MARKET_FILTER_HISTORY_STORAGE_KEY = 'morpho_market_filter_search_history';
const MORPHO_MARKET_FILTER_HISTORY_LIMIT = 30;

type MorphoMarketFilterHistory = {
  collateral: string[];
  loan: string[];
};

function emptyMarketFilterHistory(): MorphoMarketFilterHistory {
  return { collateral: [], loan: [] };
}

function normalizeFilterHistoryList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, MORPHO_MARKET_FILTER_HISTORY_LIMIT);
}

function loadMarketFilterHistory(): MorphoMarketFilterHistory {
  try {
    const stored = localStorage.getItem(MORPHO_MARKET_FILTER_HISTORY_STORAGE_KEY);
    if (!stored) return emptyMarketFilterHistory();
    const parsed = JSON.parse(stored) as unknown;
    if (!parsed || typeof parsed !== 'object') return emptyMarketFilterHistory();
    const record = parsed as Partial<Record<keyof MorphoMarketFilterHistory, unknown>>;
    return {
      collateral: normalizeFilterHistoryList(record.collateral),
      loan: normalizeFilterHistoryList(record.loan),
    };
  } catch {
    return emptyMarketFilterHistory();
  }
}

function saveMarketFilterHistory(history: MorphoMarketFilterHistory): void {
  try {
    localStorage.setItem(
      MORPHO_MARKET_FILTER_HISTORY_STORAGE_KEY,
      JSON.stringify({
        collateral: history.collateral.slice(0, MORPHO_MARKET_FILTER_HISTORY_LIMIT),
        loan: history.loan.slice(0, MORPHO_MARKET_FILTER_HISTORY_LIMIT),
      }),
    );
  } catch {
    // localStorage may be unavailable or full; filtering should still work.
  }
}

function parseMetric(value: string | null | undefined): number | null {
  if (!value) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function normalizeRatio(value: string | null | undefined): number | null {
  const numeric = parseMetric(value);
  if (numeric === null) return null;
  if (Math.abs(numeric) <= 1.5) return numeric;
  return numeric / 100;
}

function formatPercent(value: string | null | undefined): string {
  const ratio = normalizeRatio(value);
  if (ratio === null) return 'N/A';
  return `${percentFormatter.format(ratio * 100)}%`;
}

function formatLltv(value: string | null | undefined): string {
  return formatPercent(value);
}

function formatCompactNumber(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return 'N/A';
  const absolute = Math.abs(value);
  if (absolute >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toFixed(2).replace(/\.?0+$/, '')}B`;
  }
  if (absolute >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(2).replace(/\.?0+$/, '')}M`;
  }
  if (absolute >= 1_000) {
    return `${(value / 1_000).toFixed(2).replace(/\.?0+$/, '')}K`;
  }
  return value.toLocaleString('en-US', {
    minimumFractionDigits: value < 1 && value > -1 ? 2 : 0,
    maximumFractionDigits: 2,
  });
}

function formatUsdCompact(value: number | null): string {
  const formatted = formatCompactNumber(value);
  return formatted === 'N/A' ? formatted : `$${formatted}`;
}

function formatPercentFromNumber(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return 'N/A';
  return `${percentFormatter.format(value)}%`;
}

function resolveMarketSize(market: MorphoMarketView): number | null {
  return parseMetric(market.total_market_size_usd);
}

function resolveAvailableSpaceUsd(market: MorphoMarketView): number | null {
  const marketSize = resolveMarketSize(market);
  const borrowSize = resolveBorrowSizeUsd(market);
  if (marketSize === null || borrowSize === null) return null;
  return marketSize - borrowSize;
}

function resolveBorrowSizeUsd(market: MorphoMarketView): number | null {
  const marketSize = resolveMarketSize(market);
  const utilizationRatio = normalizeRatio(market.utilization);
  if (marketSize === null || utilizationRatio === null) return null;
  return marketSize * utilizationRatio;
}

function resolvePercentMetric(value: string | null | undefined): number | null {
  const ratio = normalizeRatio(value);
  return ratio === null ? null : ratio * 100;
}

function getPercentAxisMax(values: Array<number | null>, minimum = 1): number {
  const max = values.reduce<number>((current, value) => {
    if (value === null || !Number.isFinite(value)) return current;
    return Math.max(current, value);
  }, 0);
  if (max <= 0) return minimum;
  if (max <= 1) return Math.max(minimum, Math.ceil(max * 20) / 20);
  if (max <= 5) return Math.ceil(max * 1.25 * 10) / 10;
  if (max <= 20) return Math.ceil(max * 1.18);
  return Math.ceil((max * 1.1) / 5) * 5;
}

interface DetailChartItem {
  name: string;
  value: number;
  color: string;
  axis?: 'risk' | 'apy';
}

function DetailChartTooltip({
  active,
  payload,
  valueFormatter,
  axisLabel,
}: {
  active?: boolean;
  payload?: Array<{ payload?: DetailChartItem; value?: number | string }>;
  valueFormatter: (value: number) => string;
  axisLabel?: (item: DetailChartItem) => string;
}) {
  if (!active || !payload?.length) return null;
  const item = payload.find((entry) => entry.payload?.value !== undefined)?.payload;
  if (!item) return null;

  return (
    <div className="morpho-market-chart-tooltip">
      <div className="morpho-market-chart-tooltip-title">
        <span style={{ background: item.color }} />
        <strong>{item.name}</strong>
      </div>
      <div className="morpho-market-chart-tooltip-row">
        <span>当前值</span>
        <strong>{valueFormatter(item.value)}</strong>
      </div>
      {axisLabel ? <div className="morpho-market-chart-tooltip-note">{axisLabel(item)}</div> : null}
    </div>
  );
}

function compactMarketId(marketId: string): string {
  return `${marketId.slice(0, 10)}...${marketId.slice(-6)}`;
}

function compactAddress(address: string | null | undefined): string {
  if (!address) return 'N/A';
  return `${address.slice(0, 8)}...${address.slice(-6)}`;
}

function resolveUtilizationToneClass(value: string | null | undefined): string {
  const percent = normalizeRatio(value);
  if (percent === null) return '';
  if (percent > 0.95) return 'morpho-market-value-danger';
  if (percent > 0.8) return 'morpho-market-value-watch';
  return 'morpho-market-value-safe';
}

function getSortDirection(
  sortMode: MorphoSortMode,
  ascMode: MorphoSortMode,
  descMode: MorphoSortMode,
): 'asc' | 'desc' | 'none' {
  if (sortMode === ascMode) return 'asc';
  if (sortMode === descMode) return 'desc';
  return 'none';
}

function SortDirectionButton({
  ascMode,
  descMode,
  ascLabel,
  descLabel,
  sortMode,
  onSortModeChange,
}: {
  ascMode: MorphoSortMode;
  descMode: MorphoSortMode;
  ascLabel: string;
  descLabel: string;
  sortMode: MorphoSortMode;
  onSortModeChange: (value: MorphoSortMode) => void;
}) {
  const direction = getSortDirection(sortMode, ascMode, descMode);
  const nextMode = direction === 'desc' ? ascMode : descMode;
  const activeLabel = direction === 'asc' ? ascLabel : descLabel;

  return (
    <button
      type="button"
      className="morpho-market-sort-arrow-button"
      onClick={() => onSortModeChange(nextMode)}
      aria-pressed={direction !== 'none'}
      title={activeLabel}
      aria-label={activeLabel}
    >
      <span
        className={
          direction === 'asc'
            ? 'morpho-market-sort-arrow morpho-market-sort-arrow-up morpho-market-sort-arrow-active'
            : direction === 'desc'
              ? 'morpho-market-sort-arrow morpho-market-sort-arrow-down morpho-market-sort-arrow-active'
              : 'morpho-market-sort-arrow morpho-market-sort-arrow-down'
        }
      />
    </button>
  );
}

function SortableHeader({
  label,
  ascMode,
  descMode,
  ascLabel,
  descLabel,
  sortMode,
  onSortModeChange,
}: {
  label: string;
  ascMode: MorphoSortMode;
  descMode: MorphoSortMode;
  ascLabel: string;
  descLabel: string;
  sortMode: MorphoSortMode;
  onSortModeChange: (value: MorphoSortMode) => void;
}) {
  return (
    <span className="morpho-market-sort-header">
      <span>{label}</span>
      <SortDirectionButton
        ascMode={ascMode}
        descMode={descMode}
        ascLabel={ascLabel}
        descLabel={descLabel}
        sortMode={sortMode}
        onSortModeChange={onSortModeChange}
      />
    </span>
  );
}

function MorphoMarketDetailCharts({
  market,
  marketSizeUsd,
  borrowSizeUsd,
  availableSpaceUsd,
}: {
  market: MorphoMarketView;
  marketSizeUsd: number | null;
  borrowSizeUsd: number | null;
  availableSpaceUsd: number | null;
}) {
  const sizeData: DetailChartItem[] = [
    { name: '市场规模', value: marketSizeUsd ?? 0, color: '#60a5fa' },
    { name: '借款规模', value: borrowSizeUsd ?? 0, color: '#fb7185' },
    { name: '可用空间', value: availableSpaceUsd ?? 0, color: '#34d399' },
  ];
  const riskData: DetailChartItem[] = [
    { name: 'LLTV', value: resolvePercentMetric(market.lltv), color: '#38bdf8' },
    { name: '利用率', value: resolvePercentMetric(market.utilization), color: '#fbbf24' },
    {
      name: '容量负载',
      value: resolvePercentMetric(market.borrow_capacity_usage_rough),
      color: '#a78bfa',
    },
  ].map((item) => ({ ...item, value: item.value ?? 0 }));
  const apyData: DetailChartItem[] = [
    { name: '贷款 APY', value: resolvePercentMetric(market.supply_apy), color: '#86efac' },
    { name: '借款 APY', value: resolvePercentMetric(market.borrow_apy), color: '#fca5a5' },
  ].map((item) => ({ ...item, value: item.value ?? 0 }));
  const percentData = [
    ...riskData.map((item) => ({ ...item, axis: 'risk' as const })),
    ...apyData.map((item) => ({ ...item, axis: 'apy' as const })),
  ];
  const riskAxisMax = Math.max(
    100,
    getPercentAxisMax(
      riskData.map((item) => item.value),
      100,
    ),
  );
  const apyAxisMax = getPercentAxisMax(
    apyData.map((item) => item.value),
    0.5,
  );

  return (
    <div className="morpho-market-detail-charts">
      <section className="morpho-market-detail-chart-card">
        <div className="morpho-market-detail-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={sizeData}
              margin={{ top: 10, right: 16, bottom: 6, left: 10 }}
              barCategoryGap="36%"
            >
              <CartesianGrid vertical={false} stroke="rgba(148, 163, 184, 0.12)" />
              <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
              <YAxis
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 11 }}
                tickFormatter={(value) => formatUsdCompact(Number(value))}
                width={48}
              />
              <Tooltip
                content={<DetailChartTooltip valueFormatter={formatUsdCompact} />}
                cursor={{ fill: 'rgba(125, 211, 252, 0.06)', radius: 8 }}
              />
              <Bar
                dataKey="value"
                barSize={34}
                maxBarSize={42}
                radius={[7, 7, 2, 2]}
                activeBar={{ fillOpacity: 1, stroke: '#f8fafc', strokeWidth: 1.4 }}
                isAnimationActive={false}
              >
                {sizeData.map((item) => (
                  <Cell key={item.name} fill={item.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="morpho-market-detail-chart-card">
        <div className="morpho-market-detail-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={percentData}
              margin={{ top: 10, right: 12, bottom: 6, left: 6 }}
              barCategoryGap="38%"
              barGap={-20}
            >
              <CartesianGrid vertical={false} stroke="rgba(148, 163, 184, 0.12)" />
              <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
              <YAxis
                yAxisId="risk"
                domain={[0, riskAxisMax]}
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 11, fill: '#94a3b8' }}
                tickFormatter={(value) => `${Number(value).toFixed(0)}%`}
                width={38}
              />
              <YAxis
                yAxisId="apy"
                orientation="right"
                domain={[0, apyAxisMax]}
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 11, fill: '#86efac' }}
                tickFormatter={(value) => `${Number(value).toFixed(1)}%`}
                width={42}
              />
              <Tooltip
                content={
                  <DetailChartTooltip
                    valueFormatter={formatPercentFromNumber}
                    axisLabel={(item) =>
                      item.axis === 'apy' ? '该指标使用右侧动态坐标轴' : '该指标使用左侧百分比轴'
                    }
                  />
                }
                cursor={{ fill: 'rgba(125, 211, 252, 0.06)', radius: 8 }}
              />
              <Bar
                yAxisId="risk"
                dataKey={(item: (typeof percentData)[number]) =>
                  item.axis === 'risk' ? (item.value ?? 0) : 0
                }
                barSize={22}
                maxBarSize={26}
                radius={[7, 7, 2, 2]}
                activeBar={{ fillOpacity: 1, stroke: '#f8fafc', strokeWidth: 1.4 }}
                isAnimationActive={false}
              >
                {riskData.map((item) => (
                  <Cell key={`risk-${item.name}`} fill={item.color} />
                ))}
                {apyData.map((item) => (
                  <Cell key={`risk-placeholder-${item.name}`} fill="transparent" />
                ))}
              </Bar>
              <Bar
                yAxisId="apy"
                dataKey={(item: (typeof percentData)[number]) =>
                  item.axis === 'apy' ? (item.value ?? 0) : 0
                }
                barSize={22}
                maxBarSize={26}
                radius={[7, 7, 2, 2]}
                activeBar={{ fillOpacity: 1, stroke: '#f8fafc', strokeWidth: 1.4 }}
                isAnimationActive={false}
              >
                {riskData.map((item) => (
                  <Cell key={`apy-placeholder-${item.name}`} fill="transparent" />
                ))}
                {apyData.map((item) => (
                  <Cell key={`apy-${item.name}`} fill={item.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
    </div>
  );
}

function HeaderFilterControl({
  value,
  onChange,
  onKeyDown,
  onFocus,
  onBlur,
  historyItems = [],
  onHistorySelect,
  onClearHistory,
  showHistory = false,
  historyLabel,
  placeholder,
  ariaLabel,
  ascMode,
  descMode,
  ascLabel,
  descLabel,
  sortMode,
  onSortModeChange,
}: {
  value: string;
  onChange: (value: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
  onFocus?: () => void;
  onBlur?: () => void;
  historyItems?: string[];
  onHistorySelect?: (value: string) => void;
  onClearHistory?: () => void;
  showHistory?: boolean;
  historyLabel: string;
  placeholder: string;
  ariaLabel: string;
  ascMode: MorphoSortMode;
  descMode: MorphoSortMode;
  ascLabel: string;
  descLabel: string;
  sortMode: MorphoSortMode;
  onSortModeChange: (value: MorphoSortMode) => void;
}) {
  return (
    <div className="morpho-market-header-filter-control">
      <label className="morpho-market-header-search-field">
        <span className="morpho-market-header-search-icon" aria-hidden="true" />
        <input
          className="morpho-market-header-filter-input"
          type="text"
          value={value}
          onFocus={onFocus}
          onBlur={onBlur}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          aria-label={ariaLabel}
        />
        {showHistory && historyItems.length > 0 ? (
          <div className="history-dropdown morpho-market-filter-history-dropdown">
            <div className="history-header">
              <span>{historyLabel} 筛选记录</span>
              {onClearHistory ? (
                <button
                  type="button"
                  className="clear-history-btn"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    onClearHistory();
                  }}
                >
                  清除记录
                </button>
              ) : null}
            </div>
            <ul className="history-list">
              {historyItems.map((item) => (
                <li
                  key={item}
                  className="history-item"
                  title={item}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    onHistorySelect?.(item);
                  }}
                >
                  {item}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </label>
      <SortDirectionButton
        ascMode={ascMode}
        descMode={descMode}
        ascLabel={ascLabel}
        descLabel={descLabel}
        sortMode={sortMode}
        onSortModeChange={onSortModeChange}
      />
    </div>
  );
}

function AssetHeader({
  label,
  value,
  onChange,
  onKeyDown,
  onFocus,
  onBlur,
  historyItems,
  onHistorySelect,
  onClearHistory,
  showHistory,
  placeholder,
  ariaLabel,
  ascMode,
  descMode,
  ascLabel,
  descLabel,
  sortMode,
  onSortModeChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
  onFocus?: () => void;
  onBlur?: () => void;
  historyItems?: string[];
  onHistorySelect?: (value: string) => void;
  onClearHistory?: () => void;
  showHistory?: boolean;
  placeholder: string;
  ariaLabel: string;
  ascMode: MorphoSortMode;
  descMode: MorphoSortMode;
  ascLabel: string;
  descLabel: string;
  sortMode: MorphoSortMode;
  onSortModeChange: (value: MorphoSortMode) => void;
}) {
  return (
    <div className="morpho-market-asset-header">
      <span className="morpho-market-sort-header">{label}</span>
      <HeaderFilterControl
        value={value}
        onChange={onChange}
        onKeyDown={onKeyDown}
        onFocus={onFocus}
        onBlur={onBlur}
        historyItems={historyItems}
        onHistorySelect={onHistorySelect}
        onClearHistory={onClearHistory}
        showHistory={showHistory}
        historyLabel={label}
        placeholder={placeholder}
        ariaLabel={ariaLabel}
        ascMode={ascMode}
        descMode={descMode}
        ascLabel={ascLabel}
        descLabel={descLabel}
        sortMode={sortMode}
        onSortModeChange={onSortModeChange}
      />
    </div>
  );
}

export function MorphoMarketTable({
  markets,
  expandedMarketId,
  onToggleMarket,
  marketStateLoadingById,
  marketStateErrorById,
  title = '市场列表',
  subtitle = '列表只展示核心指标，展开单个市场后再加载实时详情。',
  search = '',
  onSearchChange,
  onSearchSubmit,
  searchPlaceholder = '搜索货币 / 货币地址 / market id',
  marketFilters,
  onMarketFilterCommit,
  sortMode,
  onSortModeChange,
  totalMarkets,
  page,
  totalPages,
  pageSize,
  onPageChange,
  showSorting = true,
  showPagination = true,
  showColumnHeaders = true,
  showSummaryRows = true,
  showTableHeaderWhenEmpty = true,
  emptyText = '当前筛选条件下没有可展示的 Morpho 市场。',
  tableError = '',
  embedded = false,
  forceExpanded = false,
  statusMeta,
  searchHistoryItems = [],
  onSearchHistorySelect,
  onClearSearchHistory,
}: MorphoMarketTableProps) {
  const [copiedMarketId, setCopiedMarketId] = useState('');
  const [pageInput, setPageInput] = useState(String(page));
  const [loanInput, setLoanInput] = useState(marketFilters?.loan ?? '');
  const [collateralInput, setCollateralInput] = useState(marketFilters?.collateral ?? '');
  const [showSearchHistory, setShowSearchHistory] = useState(false);
  const [filterHistory, setFilterHistory] = useState<MorphoMarketFilterHistory>(() =>
    loadMarketFilterHistory(),
  );
  const [activeFilterHistory, setActiveFilterHistory] = useState<
    keyof MorphoMarketFilterHistory | null
  >(null);
  const pageStart = totalMarkets === 0 ? 0 : (page - 1) * pageSize + 1;
  const pageEnd = Math.min(page * pageSize, totalMarkets);

  useEffect(() => {
    setPageInput(String(page));
  }, [page]);

  useEffect(() => {
    setLoanInput(marketFilters?.loan ?? '');
    setCollateralInput(marketFilters?.collateral ?? '');
  }, [marketFilters?.collateral, marketFilters?.loan]);

  const commitPageInput = () => {
    const nextPage = Number(pageInput);
    if (!Number.isFinite(nextPage)) {
      setPageInput(String(page));
      return;
    }
    const clampedPage = Math.min(totalPages, Math.max(1, Math.floor(nextPage)));
    setPageInput(String(clampedPage));
    onPageChange(clampedPage);
  };

  const handleCopyValue = async (event: MouseEvent<HTMLButtonElement>, value: string) => {
    event.stopPropagation();
    const copied = await copyToClipboard(value);
    if (!copied) return;
    setCopiedMarketId(value);
    window.setTimeout(() => {
      setCopiedMarketId((current) => (current === value ? '' : current));
    }, 1400);
  };

  const rememberFilterValue = (key: keyof MorphoMarketFilterHistory, value: string) => {
    const normalizedValue = value.trim();
    if (!normalizedValue) return;
    setFilterHistory((current) => {
      const next = {
        ...current,
        [key]: [
          normalizedValue,
          ...current[key].filter((item) => item.toLowerCase() !== normalizedValue.toLowerCase()),
        ].slice(0, MORPHO_MARKET_FILTER_HISTORY_LIMIT),
      };
      saveMarketFilterHistory(next);
      return next;
    });
  };

  const clearFilterHistory = (key: keyof MorphoMarketFilterHistory) => {
    setFilterHistory((current) => {
      const next = { ...current, [key]: [] };
      saveMarketFilterHistory(next);
      return next;
    });
  };

  const commitMarketFilters = (nextFilters: { loan?: string; collateral?: string } = {}) => {
    const nextLoan = nextFilters.loan ?? loanInput;
    const nextCollateral = nextFilters.collateral ?? collateralInput;
    rememberFilterValue('loan', nextLoan);
    rememberFilterValue('collateral', nextCollateral);
    onMarketFilterCommit?.({
      loan: nextLoan.trim(),
      collateral: nextCollateral.trim(),
    });
  };

  const handleFilterKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    commitMarketFilters();
  };

  return (
    <div
      className={
        embedded
          ? 'morpho-market-table-shell morpho-market-table-shell-embedded'
          : 'card morpho-detail-card morpho-market-table-shell'
      }
    >
      {!embedded ? (
        <div className="card-header">
          <div>
            <span className="card-title morpho-section-title">{title}</span>
            <p className="morpho-section-subtitle">{subtitle}</p>
          </div>
          {onSearchChange ? (
            <div className="morpho-market-search-stack">
              <div className="morpho-market-table-controls">
                <label className="morpho-market-search morpho-market-search-inline input-wrapper">
                  <input
                    className="address-input"
                    type="text"
                    value={search}
                    onFocus={() => setShowSearchHistory(true)}
                    onBlur={() => window.setTimeout(() => setShowSearchHistory(false), 120)}
                    onChange={(event) => onSearchChange(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault();
                        onSearchSubmit?.();
                      }
                    }}
                    placeholder={searchPlaceholder}
                  />
                  {showSearchHistory && searchHistoryItems.length > 0 ? (
                    <div className="history-dropdown morpho-market-search-history-dropdown">
                      <div className="history-header">
                        <span>搜索记录</span>
                        {onClearSearchHistory ? (
                          <button
                            type="button"
                            className="clear-history-btn"
                            onMouseDown={(event) => {
                              event.preventDefault();
                              onClearSearchHistory();
                            }}
                          >
                            清除记录
                          </button>
                        ) : null}
                      </div>
                      <ul className="history-list">
                        {searchHistoryItems.map((item) => (
                          <li
                            key={item}
                            className="history-item"
                            title={item}
                            onMouseDown={(event) => {
                              event.preventDefault();
                              onSearchHistorySelect?.(item);
                              setShowSearchHistory(false);
                            }}
                          >
                            {item}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </label>
                {onSearchSubmit ? (
                  <button
                    type="button"
                    className="search-btn morpho-market-query-btn"
                    onClick={onSearchSubmit}
                  >
                    查询
                  </button>
                ) : null}
              </div>
              {statusMeta}
            </div>
          ) : statusMeta ? (
            <div className="morpho-market-table-controls">{statusMeta}</div>
          ) : null}
        </div>
      ) : null}

      <div className="table-wrap">
        <table
          className={
            embedded
              ? 'pos-table morpho-table morpho-market-table morpho-market-table-compact morpho-market-table-embedded'
              : 'pos-table morpho-table morpho-market-table morpho-market-table-compact'
          }
        >
          <colgroup>
            <col className="morpho-market-col-id" />
            <col className="morpho-market-col-asset" />
            <col className="morpho-market-col-asset" />
            <col className="morpho-market-col-size" />
            <col className="morpho-market-col-utilization" />
          </colgroup>
          {showColumnHeaders && (showTableHeaderWhenEmpty || markets.length > 0) ? (
            <thead>
              <tr>
                <th>
                  <span className="morpho-market-sort-header">Market ID</span>
                </th>
                <th>
                  {showSorting && onMarketFilterCommit ? (
                    <AssetHeader
                      label="Collateral"
                      value={collateralInput}
                      onChange={setCollateralInput}
                      onKeyDown={handleFilterKeyDown}
                      onFocus={() => setActiveFilterHistory('collateral')}
                      onBlur={() => window.setTimeout(() => setActiveFilterHistory(null), 120)}
                      historyItems={filterHistory.collateral}
                      showHistory={activeFilterHistory === 'collateral'}
                      onHistorySelect={(value) => {
                        setCollateralInput(value);
                        setActiveFilterHistory(null);
                        commitMarketFilters({ collateral: value });
                      }}
                      onClearHistory={() => clearFilterHistory('collateral')}
                      placeholder=""
                      ariaLabel="按 collateral 筛选市场"
                      ascMode="collateralSymbolAsc"
                      descMode="collateralSymbolDesc"
                      ascLabel="按 collateral_symbol 升序排序"
                      descLabel="按 collateral_symbol 降序排序"
                      sortMode={sortMode}
                      onSortModeChange={onSortModeChange}
                    />
                  ) : (
                    'Collateral'
                  )}
                </th>
                <th>
                  {showSorting && onMarketFilterCommit ? (
                    <AssetHeader
                      label="Loan"
                      value={loanInput}
                      onChange={setLoanInput}
                      onKeyDown={handleFilterKeyDown}
                      onFocus={() => setActiveFilterHistory('loan')}
                      onBlur={() => window.setTimeout(() => setActiveFilterHistory(null), 120)}
                      historyItems={filterHistory.loan}
                      showHistory={activeFilterHistory === 'loan'}
                      onHistorySelect={(value) => {
                        setLoanInput(value);
                        setActiveFilterHistory(null);
                        commitMarketFilters({ loan: value });
                      }}
                      onClearHistory={() => clearFilterHistory('loan')}
                      placeholder=""
                      ariaLabel="按 loan 筛选市场"
                      ascMode="loanSymbolAsc"
                      descMode="loanSymbolDesc"
                      ascLabel="按 loan_symbol 升序排序"
                      descLabel="按 loan_symbol 降序排序"
                      sortMode={sortMode}
                      onSortModeChange={onSortModeChange}
                    />
                  ) : (
                    'Loan'
                  )}
                </th>
                <th className="right morpho-market-metric-header">
                  {showSorting ? (
                    <SortableHeader
                      label="市场规模"
                      ascMode="totalMarketSizeAsc"
                      descMode="totalMarketSizeDesc"
                      ascLabel="按 total_market_size_usd 升序排序"
                      descLabel="按 total_market_size_usd 降序排序"
                      sortMode={sortMode}
                      onSortModeChange={onSortModeChange}
                    />
                  ) : (
                    '市场规模'
                  )}
                </th>
                <th className="right morpho-market-metric-header">
                  {showSorting ? (
                    <SortableHeader
                      label="利用率"
                      ascMode="utilizationAsc"
                      descMode="utilizationDesc"
                      ascLabel="按 utilization 升序排序"
                      descLabel="按 utilization 降序排序"
                      sortMode={sortMode}
                      onSortModeChange={onSortModeChange}
                    />
                  ) : (
                    '利用率'
                  )}
                </th>
              </tr>
            </thead>
          ) : null}
          <tbody>
            {tableError ? (
              <tr>
                <td colSpan={5}>
                  <div className="morpho-market-table-error-row">
                    <span>{tableError}</span>
                  </div>
                </td>
              </tr>
            ) : null}
            {markets.length === 0 ? (
              <tr>
                <td colSpan={5}>
                  <div className="morpho-market-inline-state">
                    <span className="empty-text">{emptyText}</span>
                  </div>
                </td>
              </tr>
            ) : (
              markets.map((market) => {
                const marketStateKey = market.market_id.toLowerCase();
                const expandedMarketKey = expandedMarketId.toLowerCase();
                const isExpanded =
                  forceExpanded && markets.length === 1
                    ? true
                    : marketStateKey === expandedMarketKey;
                const loading =
                  marketStateLoadingById[market.market_id] === true ||
                  marketStateLoadingById[marketStateKey] === true;
                const detailError =
                  marketStateErrorById[market.market_id] ?? marketStateErrorById[marketStateKey];
                const marketSizeUsd = resolveMarketSize(market);
                const borrowSizeUsd = resolveBorrowSizeUsd(market);
                const availableSpaceUsd = resolveAvailableSpaceUsd(market);
                const utilizationToneClass = resolveUtilizationToneClass(market.utilization);
                const borrowCapacityUsageRatio = normalizeRatio(market.borrow_capacity_usage_rough);
                const isBorrowCapacityOverloaded =
                  borrowCapacityUsageRatio !== null && borrowCapacityUsageRatio > 1;
                const loanTokenAddress = market.loan_token_address;
                const collateralTokenAddress = market.collateral_token_address;

                return (
                  <Fragment key={market.market_id}>
                    {showSummaryRows ? (
                      <tr
                        className={
                          isExpanded
                            ? 'morpho-market-row morpho-market-row-active'
                            : 'morpho-market-row'
                        }
                        onClick={() => {
                          if (forceExpanded && isExpanded) return;
                          onToggleMarket(market);
                        }}
                      >
                        <td>
                          <div className="morpho-market-id-cell">
                            <button
                              type="button"
                              className="morpho-market-row-toggle morpho-market-id-toggle"
                              aria-expanded={isExpanded}
                            >
                              <span className="mono morpho-market-id" title={market.market_id}>
                                {compactMarketId(market.market_id)}
                              </span>
                            </button>
                            <button
                              type="button"
                              className={
                                copiedMarketId === market.market_id
                                  ? 'morpho-market-copy-btn morpho-market-copy-btn-copied'
                                  : 'morpho-market-copy-btn'
                              }
                              onClick={(event) => void handleCopyValue(event, market.market_id)}
                              title={
                                copiedMarketId === market.market_id
                                  ? 'Market ID 已复制'
                                  : '复制 Market ID'
                              }
                              aria-label={
                                copiedMarketId === market.market_id
                                  ? 'Market ID 已复制'
                                  : '复制 Market ID'
                              }
                            >
                              <span className="morpho-market-copy-icon" aria-hidden="true" />
                            </button>
                          </div>
                        </td>
                        <td>
                          <div className="morpho-market-asset-cell">
                            <span className="token-symbol">{market.collateral_symbol || '?'}</span>
                            {collateralTokenAddress ? (
                              <>
                                <span
                                  className="mono morpho-market-token-address-text"
                                  title={collateralTokenAddress}
                                >
                                  {compactAddress(collateralTokenAddress)}
                                </span>
                                <button
                                  type="button"
                                  className={
                                    copiedMarketId === collateralTokenAddress
                                      ? 'morpho-market-copy-btn morpho-market-copy-btn-copied morpho-market-address-copy-btn'
                                      : 'morpho-market-copy-btn morpho-market-address-copy-btn'
                                  }
                                  onClick={(event) =>
                                    void handleCopyValue(event, collateralTokenAddress)
                                  }
                                  title={
                                    copiedMarketId === collateralTokenAddress
                                      ? 'Collateral 地址已复制'
                                      : `复制 ${compactAddress(collateralTokenAddress)}`
                                  }
                                  aria-label={
                                    copiedMarketId === collateralTokenAddress
                                      ? 'Collateral 地址已复制'
                                      : '复制 Collateral 地址'
                                  }
                                >
                                  <span className="morpho-market-copy-icon" aria-hidden="true" />
                                </button>
                              </>
                            ) : null}
                          </div>
                        </td>
                        <td>
                          <div className="morpho-market-asset-cell">
                            <span className="token-symbol">{market.loan_symbol || '?'}</span>
                            {loanTokenAddress ? (
                              <>
                                <span
                                  className="mono morpho-market-token-address-text"
                                  title={loanTokenAddress}
                                >
                                  {compactAddress(loanTokenAddress)}
                                </span>
                                <button
                                  type="button"
                                  className={
                                    copiedMarketId === loanTokenAddress
                                      ? 'morpho-market-copy-btn morpho-market-copy-btn-copied morpho-market-address-copy-btn'
                                      : 'morpho-market-copy-btn morpho-market-address-copy-btn'
                                  }
                                  onClick={(event) => void handleCopyValue(event, loanTokenAddress)}
                                  title={
                                    copiedMarketId === loanTokenAddress
                                      ? 'Loan 地址已复制'
                                      : `复制 ${compactAddress(loanTokenAddress)}`
                                  }
                                  aria-label={
                                    copiedMarketId === loanTokenAddress
                                      ? 'Loan 地址已复制'
                                      : '复制 Loan 地址'
                                  }
                                >
                                  <span className="morpho-market-copy-icon" aria-hidden="true" />
                                </button>
                              </>
                            ) : null}
                          </div>
                        </td>
                        <td className="right">
                          <span className="morpho-compact-metric">
                            {formatUsdCompact(marketSizeUsd)}
                          </span>
                        </td>
                        <td className="right">
                          <span className="morpho-compact-metric">
                            {formatPercent(market.utilization)}
                          </span>
                        </td>
                      </tr>
                    ) : null}

                    {isExpanded ? (
                      <tr className="morpho-market-detail-row">
                        <td colSpan={5}>
                          {loading ? (
                            <div className="morpho-market-inline-state">
                              <div className="spinner"></div>
                            </div>
                          ) : detailError ? (
                            <div className="protocol-banner protocol-banner-warn">
                              <div className="protocol-banner-title">市场详情加载失败</div>
                              <div className="protocol-banner-copy">{detailError}</div>
                            </div>
                          ) : market.state_loaded ? (
                            <div className="morpho-market-inline-detail">
                              <MorphoMarketDetailCharts
                                market={market}
                                marketSizeUsd={marketSizeUsd}
                                borrowSizeUsd={borrowSizeUsd}
                                availableSpaceUsd={availableSpaceUsd}
                              />
                              <div className="morpho-market-detail-band morpho-market-detail-band-primary">
                                <div className="metric-box morpho-market-feature-metric">
                                  <span className="metric-label">市场规模</span>
                                  <strong className="morpho-metric-strong">
                                    {formatUsdCompact(marketSizeUsd)}
                                  </strong>
                                </div>
                                <div className="metric-box morpho-market-feature-metric">
                                  <span className="metric-label">借款规模</span>
                                  <strong className="morpho-metric-strong">
                                    {formatUsdCompact(borrowSizeUsd)}
                                  </strong>
                                </div>
                                <div className="metric-box morpho-market-progress-box">
                                  <span className="metric-label">可用空间</span>
                                  <strong
                                    className={
                                      utilizationToneClass
                                        ? `morpho-metric-strong ${utilizationToneClass}`
                                        : 'morpho-metric-strong'
                                    }
                                  >
                                    {formatUsdCompact(availableSpaceUsd)}
                                  </strong>
                                </div>
                                <div className="metric-box morpho-market-progress-box">
                                  <span className="metric-label">利用率</span>
                                  <strong
                                    className={
                                      utilizationToneClass
                                        ? `morpho-metric-strong ${utilizationToneClass}`
                                        : 'morpho-metric-strong'
                                    }
                                  >
                                    {formatPercent(market.utilization)}
                                  </strong>
                                </div>
                                <div className="metric-box morpho-market-feature-metric">
                                  <span className="metric-label">LLTV</span>
                                  <strong className="morpho-metric-strong">
                                    {formatLltv(market.lltv)}
                                  </strong>
                                </div>
                                <div className="metric-box morpho-market-feature-metric">
                                  <span className="metric-label">容量负载空间</span>
                                  <strong
                                    className={
                                      isBorrowCapacityOverloaded
                                        ? 'morpho-metric-strong morpho-risk-value-danger'
                                        : 'morpho-metric-strong'
                                    }
                                  >
                                    {formatPercent(market.borrow_capacity_usage_rough)}
                                  </strong>
                                </div>
                              </div>

                              <div className="morpho-market-detail-band morpho-market-detail-band-secondary">
                                <div className="metric-box">
                                  <span className="metric-label">Supply APY</span>
                                  <strong className="morpho-metric-strong morpho-rate-line-supply">
                                    {formatPercent(market.supply_apy)}
                                  </strong>
                                </div>
                                <div className="metric-box">
                                  <span className="metric-label">Borrow APY</span>
                                  <strong className="morpho-metric-strong morpho-rate-line-borrow">
                                    {formatPercent(market.borrow_apy)}
                                  </strong>
                                </div>
                                <div className="metric-box morpho-market-price-box">
                                  <span className="metric-label">
                                    {market.loan_symbol || 'loan'} 单价
                                  </span>
                                  <strong className="morpho-metric-strong">
                                    {formatUsdCompact(parseMetric(market.loan_token_price_usd))}
                                  </strong>
                                </div>
                                <div className="metric-box morpho-market-price-box">
                                  <span className="metric-label">
                                    {market.collateral_symbol || 'collateral'} 单价
                                  </span>
                                  <strong className="morpho-metric-strong">
                                    {formatUsdCompact(
                                      parseMetric(market.collateral_token_price_usd),
                                    )}
                                  </strong>
                                </div>
                              </div>

                              <div className="morpho-market-address-row">
                                {[
                                  ['Market ID', market.market_id],
                                  ['Oracle', market.oracle],
                                  ['IRM', market.irm],
                                ].map(([label, value]) => (
                                  <div className="morpho-market-address-item" key={label}>
                                    <span>{label}</span>
                                    <strong className="mono" title={value || ''}>
                                      {compactAddress(value)}
                                    </strong>
                                    {value ? (
                                      <button
                                        type="button"
                                        className={
                                          copiedMarketId === value
                                            ? 'morpho-market-copy-btn morpho-market-copy-btn-copied morpho-market-address-copy-action'
                                            : 'morpho-market-copy-btn morpho-market-address-copy-action'
                                        }
                                        onClick={(event) => void handleCopyValue(event, value)}
                                        title={`复制 ${label}`}
                                        aria-label={`复制 ${label}`}
                                      >
                                        <span
                                          className="morpho-market-copy-icon"
                                          aria-hidden="true"
                                        />
                                      </button>
                                    ) : null}
                                  </div>
                                ))}
                                {[
                                  [`${market.loan_symbol || 'Loan'} 地址`, loanTokenAddress],
                                  [
                                    `${market.collateral_symbol || 'Collateral'} 地址`,
                                    collateralTokenAddress,
                                  ],
                                ].map(([label, value]) => (
                                  <div
                                    className="morpho-market-address-item morpho-market-address-item-token"
                                    key={label}
                                  >
                                    <span>{label}</span>
                                    <strong className="mono" title={value || ''}>
                                      {compactAddress(value)}
                                    </strong>
                                    {value ? (
                                      <button
                                        type="button"
                                        className={
                                          copiedMarketId === value
                                            ? 'morpho-market-copy-btn morpho-market-copy-btn-copied morpho-market-address-copy-action'
                                            : 'morpho-market-copy-btn morpho-market-address-copy-action'
                                        }
                                        onClick={(event) => void handleCopyValue(event, value)}
                                        title={`复制 ${label}`}
                                        aria-label={`复制 ${label}`}
                                      >
                                        <span
                                          className="morpho-market-copy-icon"
                                          aria-hidden="true"
                                        />
                                      </button>
                                    ) : null}
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : (
                            <div className="morpho-market-inline-state">
                              <span className="empty-text">展开后将加载该市场实时详情。</span>
                            </div>
                          )}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {showPagination ? (
        <div className="morpho-market-pagination">
          <span>
            显示 {pageStart.toLocaleString()}-{pageEnd.toLocaleString()} /{' '}
            {totalMarkets.toLocaleString()}，第 {page} / {totalPages} 页
          </span>
          <div className="morpho-market-pagination-actions">
            <button
              type="button"
              className="switch-btn"
              disabled={page <= 1}
              onClick={() => onPageChange(Math.max(1, page - 1))}
            >
              上一页
            </button>
            <label className="morpho-market-page-jump">
              <span>跳至</span>
              <input
                className="morpho-market-page-input"
                type="number"
                min={1}
                max={totalPages}
                value={pageInput}
                onChange={(event) => setPageInput(event.target.value)}
                onBlur={commitPageInput}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.currentTarget.blur();
                  }
                }}
                aria-label="跳转页码"
              />
              <span>页</span>
            </label>
            <button
              type="button"
              className="switch-btn"
              disabled={page >= totalPages}
              onClick={() => onPageChange(Math.min(totalPages, page + 1))}
            >
              下一页
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
