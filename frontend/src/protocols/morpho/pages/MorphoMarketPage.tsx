import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { PageHero } from '../../../shared/components/PageHero';
import { SegmentedControl } from '../../../shared/components/SegmentedControl';
import { useMorphoData, type MorphoMarketView } from '../../../hooks/useMorphoData';
import { MorphoMarketTable } from '../components/MorphoMarketTable';

type MorphoRiskFilter = 'all' | 'liquidatable';
type MorphoSortMode = 'collateral' | 'debt' | 'borrowApy';

function parseMetric(value: string | null | undefined): number | null {
  if (!value) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatUsd(value: string | null | undefined): string {
  const numeric = parseMetric(value);
  if (numeric === null) return 'N/A';
  return `$${numeric.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatPercent(value: string | null | undefined): string {
  const numeric = parseMetric(value);
  if (numeric === null) return 'N/A';
  const normalized = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return `${normalized.toFixed(2)}%`;
}

function formatLltv(value: string | null | undefined): string {
  const numeric = parseMetric(value);
  if (numeric === null) return 'N/A';
  const normalized = numeric <= 1 ? numeric * 100 : numeric;
  return `${normalized.toFixed(2)}%`;
}

function shortAddress(value: string | null | undefined): string {
  if (!value) return 'N/A';
  if (value.length <= 14) return value;
  return `${value.slice(0, 8)}...${value.slice(-6)}`;
}

function sortMarkets(markets: MorphoMarketView[], sortMode: MorphoSortMode): MorphoMarketView[] {
  const sorted = [...markets];
  sorted.sort((left, right) => {
    const leftValue =
      sortMode === 'collateral'
        ? (parseMetric(left.total_collateral_usd) ?? -1)
        : sortMode === 'debt'
          ? (parseMetric(left.total_debt_usd) ?? -1)
          : (parseMetric(left.borrow_apy) ?? -1);
    const rightValue =
      sortMode === 'collateral'
        ? (parseMetric(right.total_collateral_usd) ?? -1)
        : sortMode === 'debt'
          ? (parseMetric(right.total_debt_usd) ?? -1)
          : (parseMetric(right.borrow_apy) ?? -1);

    return rightValue - leftValue;
  });

  return sorted;
}

export function MorphoMarketPage() {
  const { markets, loading, error, fetchedAt, fromCache, reload } = useMorphoData();
  const [riskFilter, setRiskFilter] = useState<MorphoRiskFilter>('all');
  const [sortMode, setSortMode] = useState<MorphoSortMode>('collateral');
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search);
  const [selectedMarketId, setSelectedMarketId] = useState('');

  const visibleMarkets = useMemo(() => {
    const keyword = deferredSearch.trim().toLowerCase();

    const filtered = markets.filter((market) => {
      if (riskFilter === 'liquidatable' && market.is_liquidatable !== true) {
        return false;
      }

      if (!keyword) return true;

      return [
        market.market_id,
        market.loan_symbol,
        market.collateral_symbol,
        market.pair,
        market.oracle,
        market.irm,
      ]
        .filter(Boolean)
        .some((value) => value?.toLowerCase().includes(keyword));
    });

    return sortMarkets(filtered, sortMode);
  }, [deferredSearch, markets, riskFilter, sortMode]);

  useEffect(() => {
    if (!visibleMarkets.length) {
      setSelectedMarketId('');
      return;
    }

    setSelectedMarketId((current) =>
      visibleMarkets.some((item) => item.market_id === current)
        ? current
        : visibleMarkets[0].market_id,
    );
  }, [visibleMarkets]);

  const selectedMarket = useMemo(
    () =>
      visibleMarkets.find((item) => item.market_id === selectedMarketId) ??
      visibleMarkets[0] ??
      null,
    [selectedMarketId, visibleMarkets],
  );

  const refreshedAtText = fetchedAt
    ? new Date(fetchedAt).toLocaleString('zh-CN', {
        hour12: false,
      })
    : 'N/A';

  return (
    <>
      <PageHero
        title="Morpho 市场页面"
        subtitle="聚合 Morpho 隔离市场静态配置与实时状态，快速查看规模、利率与风险标记。"
        controls={
          <div className="morpho-market-hero-controls">
            <SegmentedControl
              ariaLabel="Morpho market risk filter"
              value={riskFilter}
              onChange={setRiskFilter}
              options={[
                { value: 'all', label: '全部市场' },
                { value: 'liquidatable', label: '仅风险市场', activeClassName: 'active-purple' },
              ]}
            />
            <button type="button" className="switch-btn" onClick={() => void reload()}>
              刷新数据
            </button>
          </div>
        }
      />

      <div className="card morpho-detail-card morpho-market-toolbar">
        <div className="morpho-market-toolbar-copy">
          <strong>数据状态</strong>
          <span>
            最近更新 {refreshedAtText} {fromCache ? '· 缓存命中' : '· 实时拉取'}
          </span>
        </div>
        <div className="morpho-market-toolbar-actions">
          <label className="morpho-market-search">
            <span>搜索市场</span>
            <input
              className="address-input"
              type="text"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="market id / token / oracle / irm"
            />
          </label>
          <SegmentedControl
            ariaLabel="Morpho market sort mode"
            value={sortMode}
            onChange={setSortMode}
            options={[
              { value: 'collateral', label: '按抵押规模' },
              { value: 'debt', label: '按债务规模' },
              { value: 'borrowApy', label: '按借款利率' },
            ]}
          />
        </div>
      </div>

      <ErrorNotice message={error} />

      {loading ? (
        <div className="card morpho-market-loading-card">
          <div className="spinner"></div>
        </div>
      ) : (
        <>
          <MorphoMarketTable
            markets={visibleMarkets}
            selectedMarketId={selectedMarketId}
            onSelectMarket={setSelectedMarketId}
          />

          {selectedMarket ? (
            <section className="morpho-market-detail-grid">
              <div className="card morpho-emphasis-card morpho-market-focus-card">
                <div className="card-header">
                  <div>
                    <span className="card-title morpho-section-title">市场聚焦</span>
                    <p className="morpho-section-subtitle">
                      {selectedMarket.loan_symbol || '?'} /{' '}
                      {selectedMarket.collateral_symbol || '?'}
                    </p>
                  </div>
                  <span
                    className={
                      selectedMarket.is_liquidatable
                        ? 'pill morpho-risk-pill morpho-risk-pill-danger'
                        : 'pill morpho-risk-pill morpho-risk-pill-safe'
                    }
                  >
                    {selectedMarket.is_liquidatable ? '风险中' : '健康'}
                  </span>
                </div>

                <div className="morpho-summary-layout">
                  <div className="morpho-summary-group">
                    <span className="morpho-summary-group-title">规模</span>
                    <div className="morpho-summary-group-grid">
                      <div className="metric-box">
                        <span className="metric-label">总抵押</span>
                        <strong className="morpho-metric-strong">
                          {formatUsd(selectedMarket.total_collateral_usd)}
                        </strong>
                      </div>
                      <div className="metric-box">
                        <span className="metric-label">总债务</span>
                        <strong className="morpho-metric-strong">
                          {formatUsd(selectedMarket.total_debt_usd)}
                        </strong>
                      </div>
                    </div>
                  </div>

                  <div className="morpho-summary-group">
                    <span className="morpho-summary-group-title">利率</span>
                    <div className="morpho-summary-group-grid">
                      <div className="metric-box">
                        <span className="metric-label">Supply APY</span>
                        <strong className="morpho-metric-strong">
                          {formatPercent(selectedMarket.supply_apy)}
                        </strong>
                      </div>
                      <div className="metric-box">
                        <span className="metric-label">Borrow APY</span>
                        <strong className="morpho-metric-strong">
                          {formatPercent(selectedMarket.borrow_apy)}
                        </strong>
                      </div>
                    </div>
                  </div>

                  <div className="morpho-summary-group">
                    <span className="morpho-summary-group-title">参数</span>
                    <div className="morpho-summary-group-grid">
                      <div className="metric-box">
                        <span className="metric-label">LLTV</span>
                        <strong className="morpho-metric-strong">
                          {formatLltv(selectedMarket.lltv)}
                        </strong>
                      </div>
                      <div className="metric-box">
                        <span className="metric-label">ETH 下跌清算价</span>
                        <strong className="morpho-metric-strong">
                          {formatUsd(selectedMarket.eth_down_liq_price_usd)}
                        </strong>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="morpho-keyline">
                  <div className="morpho-keyline-item">
                    <span>Market ID</span>
                    <strong className="mono">{selectedMarket.market_id}</strong>
                  </div>
                  <div className="morpho-keyline-item">
                    <span>Oracle</span>
                    <strong className="mono" title={selectedMarket.oracle || ''}>
                      {shortAddress(selectedMarket.oracle)}
                    </strong>
                  </div>
                  <div className="morpho-keyline-item">
                    <span>IRM</span>
                    <strong className="mono" title={selectedMarket.irm || ''}>
                      {shortAddress(selectedMarket.irm)}
                    </strong>
                  </div>
                </div>

                {!selectedMarket.state_loaded ? (
                  <div className="protocol-banner protocol-banner-warn">
                    <div className="protocol-banner-title">实时状态缺失</div>
                    <div className="protocol-banner-copy">
                      当前市场静态配置已展示，但状态接口未返回完整数据；页面仍保留 market
                      id、代币对与参数信息。
                    </div>
                  </div>
                ) : null}
              </div>
            </section>
          ) : null}
        </>
      )}
    </>
  );
}
