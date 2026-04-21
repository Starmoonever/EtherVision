import { Fragment, useEffect, useState, type MouseEvent } from 'react';
import type { MorphoMarketView } from '../../../hooks/useMorphoData';
import { SegmentedControl } from '../../../shared/components/SegmentedControl';
import { copyToClipboard } from '../../../shared/utils/copyToClipboard';

type MorphoSortMode = 'default' | 'totalMarketSize' | 'utilization';

interface MorphoMarketTableProps {
  markets: MorphoMarketView[];
  expandedMarketId: string;
  onToggleMarket: (market: MorphoMarketView) => void;
  marketStateLoadingById: Record<string, boolean>;
  marketStateErrorById: Record<string, string>;
  search: string;
  onSearchChange: (value: string) => void;
  sortMode: MorphoSortMode;
  onSortModeChange: (value: MorphoSortMode) => void;
  totalMarkets: number;
  page: number;
  totalPages: number;
  pageSize: number;
  onPageChange: (page: number) => void;
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
  return parseMetric(market.available_space_usd);
}

function resolveBorrowSizeUsd(market: MorphoMarketView): number | null {
  return parseMetric(market.borrow_market_size_usd);
}

function resolveAvailableSpacePercent(market: MorphoMarketView): number | null {
  const marketSize = resolveMarketSize(market);
  const availableSpace = resolveAvailableSpaceUsd(market);
  if (marketSize === null || marketSize <= 0 || availableSpace === null) return null;
  return Math.max(0, Math.min(100, (availableSpace / marketSize) * 100));
}

function formatPercentFromNumber(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return 'N/A';
  return `${percentFormatter.format(value)}%`;
}

function resolveRatioPercent(value: string | null | undefined): number | null {
  const ratio = normalizeRatio(value);
  return ratio === null ? null : ratio * 100;
}

function clampPercent(value: number | null): number {
  if (value === null || !Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(value, 100));
}

function compactMarketId(marketId: string): string {
  return `${marketId.slice(0, 10)}...${marketId.slice(-6)}`;
}

function compactAddress(address: string | null | undefined): string {
  if (!address) return 'N/A';
  return `${address.slice(0, 8)}...${address.slice(-6)}`;
}

export function MorphoMarketTable({
  markets,
  expandedMarketId,
  onToggleMarket,
  marketStateLoadingById,
  marketStateErrorById,
  search,
  onSearchChange,
  sortMode,
  onSortModeChange,
  totalMarkets,
  page,
  totalPages,
  pageSize,
  onPageChange,
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

  if (!markets.length) {
    return (
      <div className="card morpho-detail-card">
        <p className="empty-text">当前筛选条件下没有可展示的 Morpho 市场。</p>
      </div>
    );
  }

  return (
    <div className="card morpho-detail-card">
      <div className="card-header">
        <div>
          <span className="card-title morpho-section-title">市场列表</span>
          <p className="morpho-section-subtitle">
            列表只展示核心指标，展开单个市场后再加载实时详情。
          </p>
        </div>
        <div className="morpho-market-table-controls">
          <label className="morpho-market-search morpho-market-search-inline">
            <input
              className="address-input"
              type="text"
              value={search}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="搜索 pair / market id / token / oracle / irm"
            />
          </label>
          <SegmentedControl
            ariaLabel="Morpho market sort mode"
            value={sortMode}
            onChange={(value) => onSortModeChange(value as MorphoSortMode)}
            options={[
              { value: 'default', label: '默认' },
              { value: 'totalMarketSize', label: '市场规模' },
              { value: 'utilization', label: '利用率' },
            ]}
          />
          <span className="badge badge-brand-soft">{totalMarkets} Markets</span>
        </div>
      </div>

      <div className="table-wrap">
        <table className="pos-table morpho-table morpho-market-table morpho-market-table-compact">
          <thead>
            <tr>
              <th>Pair</th>
              <th className="right">市场规模</th>
              <th className="right">利用率</th>
            </tr>
          </thead>
          <tbody>
            {markets.map((market) => {
              const isExpanded = market.market_id === expandedMarketId;
              const loading = marketStateLoadingById[market.market_id] === true;
              const detailError = marketStateErrorById[market.market_id];
              const marketSizeUsd = resolveMarketSize(market);
              const borrowSizeUsd = resolveBorrowSizeUsd(market);
              const availableSpaceUsd = resolveAvailableSpaceUsd(market);
              const availableSpacePercent = resolveAvailableSpacePercent(market);
              const utilizationPercent = resolveRatioPercent(market.utilization);
              const isUtilizationDanger = utilizationPercent !== null && utilizationPercent > 95;
              const borrowCapacityUsageRatio = normalizeRatio(market.borrow_capacity_usage_rough);
              const isBorrowCapacityOverloaded =
                borrowCapacityUsageRatio !== null && borrowCapacityUsageRatio > 1;

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
                                <strong className="morpho-metric-strong">
                                  {formatUsdCompact(availableSpaceUsd)}
                                </strong>
                                <div className="morpho-utilization-cell morpho-market-detail-progress">
                                  <div className="morpho-utilization-bar" aria-hidden="true">
                                    <span
                                      className={
                                        isUtilizationDanger
                                          ? 'morpho-utilization-fill morpho-utilization-fill-available morpho-utilization-fill-danger'
                                          : 'morpho-utilization-fill morpho-utilization-fill-available'
                                      }
                                      style={{ width: `${clampPercent(availableSpacePercent)}%` }}
                                    />
                                  </div>
                                  <span className="morpho-utilization-value">
                                    {formatPercentFromNumber(availableSpacePercent)}
                                  </span>
                                </div>
                              </div>
                              <div className="metric-box morpho-market-progress-box">
                                <span className="metric-label">利用率</span>
                                <strong className="morpho-metric-strong">
                                  {formatPercent(market.utilization)}
                                </strong>
                                <div className="morpho-utilization-cell morpho-market-detail-progress">
                                  <div className="morpho-utilization-bar" aria-hidden="true">
                                    <span
                                      className={
                                        isUtilizationDanger
                                          ? 'morpho-utilization-fill morpho-utilization-fill-danger'
                                          : 'morpho-utilization-fill'
                                      }
                                      style={{ width: `${clampPercent(utilizationPercent)}%` }}
                                    />
                                  </div>
                                  <span className="morpho-utilization-value">
                                    {formatPercentFromNumber(utilizationPercent)}
                                  </span>
                                </div>
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
                              <div className="metric-box">
                                <span className="metric-label">
                                  {market.loan_symbol || 'loan'} 单价
                                </span>
                                <strong className="morpho-metric-strong">
                                  {formatUsdCompact(parseMetric(market.loan_token_price_usd))}
                                </strong>
                              </div>
                              <div className="metric-box">
                                <span className="metric-label">
                                  {market.collateral_symbol || 'collateral'} 单价
                                </span>
                                <strong className="morpho-metric-strong">
                                  {formatUsdCompact(parseMetric(market.collateral_token_price_usd))}
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
            })}
          </tbody>
        </table>
      </div>

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
    </div>
  );
}
