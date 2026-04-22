import { Fragment, useEffect, useState, type KeyboardEvent, type MouseEvent } from 'react';
import type { MorphoMarketView } from '../../../hooks/useMorphoData';
import { copyToClipboard } from '../../../shared/utils/copyToClipboard';

export type MorphoSortMode =
  | 'default'
  | 'loanSymbolDesc'
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
  showTableHeaderWhenEmpty?: boolean;
  emptyText?: string;
  tableError?: string;
}

const percentFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

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

function resolvePair(market: MorphoMarketView): string {
  if (market.pair) return market.pair;
  return `${market.loan_symbol || '?'}-${market.collateral_symbol || '?'}`;
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

function SortableHeader({
  label,
  upMode,
  downMode,
  upLabel,
  downLabel,
  sortMode,
  onSortModeChange,
}: {
  label: string;
  upMode: MorphoSortMode;
  downMode: MorphoSortMode;
  upLabel: string;
  downLabel: string;
  sortMode: MorphoSortMode;
  onSortModeChange: (value: MorphoSortMode) => void;
}) {
  const isUpActive = sortMode === upMode;
  const isDownActive = sortMode === downMode;
  const toggleSortMode = (nextMode: MorphoSortMode) => {
    onSortModeChange(sortMode === nextMode ? 'default' : nextMode);
  };

  return (
    <span className="morpho-market-sort-header">
      <span>{label}</span>
      <span className="morpho-market-sort-arrows">
        <button
          type="button"
          className="morpho-market-sort-arrow-button"
          onClick={() => toggleSortMode(upMode)}
          aria-pressed={isUpActive}
          title={upLabel}
          aria-label={upLabel}
        >
          <span
            className={
              isUpActive
                ? 'morpho-market-sort-arrow morpho-market-sort-arrow-up morpho-market-sort-arrow-active'
                : 'morpho-market-sort-arrow morpho-market-sort-arrow-up'
            }
          />
        </button>
        <button
          type="button"
          className="morpho-market-sort-arrow-button"
          onClick={() => toggleSortMode(downMode)}
          aria-pressed={isDownActive}
          title={downLabel}
          aria-label={downLabel}
        >
          <span
            className={
              isDownActive
                ? 'morpho-market-sort-arrow morpho-market-sort-arrow-down morpho-market-sort-arrow-active'
                : 'morpho-market-sort-arrow morpho-market-sort-arrow-down'
            }
          />
        </button>
      </span>
    </span>
  );
}

function MarketHeader({
  sortMode,
  onSortModeChange,
  marketFilters,
  onMarketFilterCommit,
}: {
  sortMode: MorphoSortMode;
  onSortModeChange: (value: MorphoSortMode) => void;
  marketFilters?: {
    loan: string;
    collateral: string;
  };
  onMarketFilterCommit?: (filters: { loan: string; collateral: string }) => void;
}) {
  const [loanInput, setLoanInput] = useState(marketFilters?.loan ?? '');
  const [collateralInput, setCollateralInput] = useState(marketFilters?.collateral ?? '');

  useEffect(() => {
    setLoanInput(marketFilters?.loan ?? '');
    setCollateralInput(marketFilters?.collateral ?? '');
  }, [marketFilters?.collateral, marketFilters?.loan]);

  const commitFilters = () => {
    onMarketFilterCommit?.({
      loan: loanInput.trim(),
      collateral: collateralInput.trim(),
    });
  };

  const handleFilterKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    commitFilters();
  };

  return (
    <div className="morpho-market-header-stack">
      <SortableHeader
        label="市场"
        upMode="loanSymbolDesc"
        downMode="collateralSymbolDesc"
        upLabel="按 loan_symbol 降序排序"
        downLabel="按 collateral_symbol 降序排序"
        sortMode={sortMode}
        onSortModeChange={onSortModeChange}
      />
      {onMarketFilterCommit ? (
        <div className="morpho-market-header-filters">
          <input
            className="morpho-market-header-filter-input"
            type="text"
            value={loanInput}
            onChange={(event) => setLoanInput(event.target.value)}
            onKeyDown={handleFilterKeyDown}
            placeholder="loan"
            aria-label="按 loan 筛选市场"
          />
          <input
            className="morpho-market-header-filter-input"
            type="text"
            value={collateralInput}
            onChange={(event) => setCollateralInput(event.target.value)}
            onKeyDown={handleFilterKeyDown}
            placeholder="collateral"
            aria-label="按 collateral 筛选市场"
          />
        </div>
      ) : null}
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
  showTableHeaderWhenEmpty = true,
  emptyText = '当前筛选条件下没有可展示的 Morpho 市场。',
  tableError = '',
}: MorphoMarketTableProps) {
  const [copiedMarketId, setCopiedMarketId] = useState('');
  const [pageInput, setPageInput] = useState(String(page));
  const pageStart = totalMarkets === 0 ? 0 : (page - 1) * pageSize + 1;
  const pageEnd = Math.min(page * pageSize, totalMarkets);

  useEffect(() => {
    setPageInput(String(page));
  }, [page]);

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

  return (
    <div className="card morpho-detail-card">
      <div className="card-header">
        <div>
          <span className="card-title morpho-section-title">{title}</span>
          <p className="morpho-section-subtitle">{subtitle}</p>
        </div>
        {onSearchChange ? (
          <div className="morpho-market-table-controls">
            <label className="morpho-market-search morpho-market-search-inline">
              <input
                className="address-input"
                type="text"
                value={search}
                onChange={(event) => onSearchChange(event.target.value)}
                placeholder={searchPlaceholder}
              />
            </label>
          </div>
        ) : null}
      </div>

      <div className="table-wrap">
        <table className="pos-table morpho-table morpho-market-table morpho-market-table-compact">
          {showTableHeaderWhenEmpty || markets.length > 0 ? (
            <thead>
              <tr>
                <th>
                  {showSorting ? (
                    <MarketHeader
                      sortMode={sortMode}
                      onSortModeChange={onSortModeChange}
                      marketFilters={marketFilters}
                      onMarketFilterCommit={onMarketFilterCommit}
                    />
                  ) : (
                    '市场'
                  )}
                </th>
                <th className="right">
                  {showSorting ? (
                    <SortableHeader
                      label="市场规模"
                      upMode="totalMarketSizeAsc"
                      downMode="totalMarketSizeDesc"
                      upLabel="按 total_market_size_usd 升序排序"
                      downLabel="按 total_market_size_usd 降序排序"
                      sortMode={sortMode}
                      onSortModeChange={onSortModeChange}
                    />
                  ) : (
                    '市场规模'
                  )}
                </th>
                <th className="right">
                  {showSorting ? (
                    <SortableHeader
                      label="利用率"
                      upMode="utilizationAsc"
                      downMode="utilizationDesc"
                      upLabel="按 utilization 升序排序"
                      downLabel="按 utilization 降序排序"
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
                <td colSpan={3}>
                  <div className="morpho-market-table-error-row">
                    <span>{tableError}</span>
                  </div>
                </td>
              </tr>
            ) : null}
            {markets.length === 0 ? (
              <tr>
                <td colSpan={3}>
                  <div className="morpho-market-inline-state">
                    <span className="empty-text">{emptyText}</span>
                  </div>
                </td>
              </tr>
            ) : (
              markets.map((market) => {
                const isExpanded = market.market_id === expandedMarketId;
                const loading = marketStateLoadingById[market.market_id] === true;
                const detailError = marketStateErrorById[market.market_id];
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
                    <tr
                      className={
                        isExpanded
                          ? 'morpho-market-row morpho-market-row-active'
                          : 'morpho-market-row'
                      }
                      onClick={() => onToggleMarket(market)}
                    >
                      <td>
                        <div className="morpho-market-pair-cell">
                          <button
                            type="button"
                            className="morpho-market-row-toggle"
                            aria-expanded={isExpanded}
                          >
                            <span className="morpho-market-row-chevron" aria-hidden="true">
                              {isExpanded ? '-' : '+'}
                            </span>
                            <strong className="token-symbol">{resolvePair(market)}</strong>
                          </button>
                          <div className="morpho-market-id-line">
                            <span className="mono morpho-market-id" title={market.market_id}>
                              {compactMarketId(market.market_id)}
                            </span>
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

                    {isExpanded ? (
                      <tr className="morpho-market-detail-row">
                        <td colSpan={3}>
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
                                  {loanTokenAddress ? (
                                    <button
                                      type="button"
                                      className={
                                        copiedMarketId === loanTokenAddress
                                          ? 'morpho-market-copy-btn morpho-market-copy-btn-copied morpho-market-price-copy-btn'
                                          : 'morpho-market-copy-btn morpho-market-price-copy-btn'
                                      }
                                      onClick={(event) =>
                                        void handleCopyValue(event, loanTokenAddress)
                                      }
                                      title={`复制 ${market.loan_symbol || 'loan'} 地址`}
                                      aria-label={`复制 ${market.loan_symbol || 'loan'} 地址`}
                                    >
                                      <span
                                        className="morpho-market-copy-icon"
                                        aria-hidden="true"
                                      />
                                    </button>
                                  ) : null}
                                  <strong className="morpho-metric-strong">
                                    {formatUsdCompact(parseMetric(market.loan_token_price_usd))}
                                  </strong>
                                </div>
                                <div className="metric-box morpho-market-price-box">
                                  <span className="metric-label">
                                    {market.collateral_symbol || 'collateral'} 单价
                                  </span>
                                  {collateralTokenAddress ? (
                                    <button
                                      type="button"
                                      className={
                                        copiedMarketId === collateralTokenAddress
                                          ? 'morpho-market-copy-btn morpho-market-copy-btn-copied morpho-market-price-copy-btn'
                                          : 'morpho-market-copy-btn morpho-market-price-copy-btn'
                                      }
                                      onClick={(event) =>
                                        void handleCopyValue(event, collateralTokenAddress)
                                      }
                                      title={`复制 ${market.collateral_symbol || 'collateral'} 地址`}
                                      aria-label={`复制 ${market.collateral_symbol || 'collateral'} 地址`}
                                    >
                                      <span
                                        className="morpho-market-copy-icon"
                                        aria-hidden="true"
                                      />
                                    </button>
                                  ) : null}
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
                                            ? 'morpho-market-copy-btn morpho-market-copy-btn-copied'
                                            : 'morpho-market-copy-btn'
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
