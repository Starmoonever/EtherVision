import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import { fetchAssetPrice } from '../../../api/price';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { PageHero } from '../../../shared/components/PageHero';
import { useMorphoData, type MorphoMarketView } from '../../../hooks/useMorphoData';
import { MorphoMarketTable } from '../components/MorphoMarketTable';

type MorphoSortMode = 'supplyScale' | 'borrowScale' | 'supplyApy' | 'borrowApy';

function parseMetric(value: string | null | undefined): number | null {
  if (!value) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatPercent(value: string | null | undefined): string {
  const numeric = parseMetric(value);
  if (numeric === null) return 'N/A';
  const normalized = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return `${normalized.toFixed(2)}%`;
}

function formatCapacityUsagePercent(value: string | null | undefined): string {
  const numeric = parseMetric(value);
  if (numeric === null) return 'N/A';
  const normalized = numeric * 100;
  return `${normalized.toFixed(2)}%`;
}

function formatLltv(value: string | null | undefined): string {
  const numeric = parseMetric(value);
  if (numeric === null) return 'N/A';
  const normalized = numeric <= 1 ? numeric * 100 : numeric;
  return `${normalized.toFixed(2)}%`;
}

function normalizeTokenAmount(
  value: string | null | undefined,
  decimals: number | null | undefined,
  isRaw: boolean,
): number | null {
  if (!value) return null;
  if (!isRaw) return parseMetric(value);

  const safeDecimals = Number.isInteger(decimals) ? Number(decimals) : 0;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const negative = trimmed.startsWith('-');
  const digits = negative ? trimmed.slice(1) : trimmed;
  if (!/^\d+$/.test(digits)) return parseMetric(value);

  const paddedDigits = digits.padStart(safeDecimals + 1, '0');
  const integerPart =
    safeDecimals === 0 ? paddedDigits : paddedDigits.slice(0, paddedDigits.length - safeDecimals);
  const fractionalPart =
    safeDecimals === 0 ? '' : paddedDigits.slice(-safeDecimals).replace(/0+$/, '');
  const normalizedText = `${negative ? '-' : ''}${integerPart}${fractionalPart ? `.${fractionalPart}` : ''}`;
  const numeric = Number(normalizedText);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatAmount(value: number | null, symbol?: string | null): string {
  if (value === null) return 'N/A';
  const amount = value.toLocaleString('en-US', {
    minimumFractionDigits: value >= 1 ? 2 : 4,
    maximumFractionDigits: 6,
  });
  return symbol ? `${amount} ${symbol}` : amount;
}

function formatUsdFromNumber(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return 'N/A';
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function sortMarkets(
  markets: MorphoMarketView[],
  sortMode: MorphoSortMode,
  loanTokenPricesUsd: Record<string, number | null>,
): MorphoMarketView[] {
  const resolveUsdScale = (market: MorphoMarketView, kind: 'supply' | 'borrow'): number => {
    const loanSymbol = market.loan_symbol?.trim().toUpperCase() ?? '';
    const price = loanSymbol ? (loanTokenPricesUsd[loanSymbol] ?? null) : null;
    if (price === null) return -1;
    const amount =
      kind === 'supply'
        ? normalizeTokenAmount(
            market.total_supply_assets,
            market.loan_decimals,
            market.total_supply_assets_is_raw,
          )
        : normalizeTokenAmount(
            market.total_borrow_assets,
            market.loan_decimals,
            market.total_borrow_assets_is_raw,
          );
    if (amount === null) return -1;
    return amount * price;
  };

  const sorted = [...markets];
  sorted.sort((left, right) => {
    const leftValue =
      sortMode === 'supplyScale'
        ? resolveUsdScale(left, 'supply')
        : sortMode === 'borrowScale'
          ? resolveUsdScale(left, 'borrow')
          : sortMode === 'supplyApy'
            ? (parseMetric(left.supply_apy) ?? -1)
            : (parseMetric(left.borrow_apy) ?? -1);
    const rightValue =
      sortMode === 'supplyScale'
        ? resolveUsdScale(right, 'supply')
        : sortMode === 'borrowScale'
          ? resolveUsdScale(right, 'borrow')
          : sortMode === 'supplyApy'
            ? (parseMetric(right.supply_apy) ?? -1)
            : (parseMetric(right.borrow_apy) ?? -1);

    return rightValue - leftValue;
  });

  return sorted;
}

export function MorphoMarketPage() {
  const { markets, loading, error, fetchedAt, fromCache, reload } = useMorphoData();
  const [sortMode, setSortMode] = useState<MorphoSortMode>('supplyScale');
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search);
  const [selectedMarketId, setSelectedMarketId] = useState('');
  const [loanTokenPricesUsd, setLoanTokenPricesUsd] = useState<Record<string, number | null>>({});

  const filteredMarkets = useMemo(() => {
    const keyword = deferredSearch.trim().toLowerCase();

    const filtered = markets.filter((market) => {
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

    return filtered;
  }, [deferredSearch, markets]);

  const visibleMarkets = useMemo(
    () => sortMarkets(filteredMarkets, sortMode, loanTokenPricesUsd),
    [filteredMarkets, loanTokenPricesUsd, sortMode],
  );

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

  useEffect(() => {
    let cancelled = false;
    const loanSymbols = Array.from(
      new Set(
        filteredMarkets
          .map((item) => item.loan_symbol?.trim().toUpperCase() ?? '')
          .filter((symbol) => Boolean(symbol)),
      ),
    );

    if (!loanSymbols.length) {
      setLoanTokenPricesUsd({});
      return;
    }

    const loadPrices = async () => {
      const settled = await Promise.allSettled(
        loanSymbols.map((symbol) => fetchAssetPrice(symbol)),
      );
      if (cancelled) return;

      const next: Record<string, number | null> = {};
      loanSymbols.forEach((symbol, index) => {
        const result = settled[index];
        next[symbol] = result.status === 'fulfilled' ? result.value : null;
      });
      setLoanTokenPricesUsd(next);
    };

    void loadPrices();
    return () => {
      cancelled = true;
    };
  }, [filteredMarkets]);

  const selectedMarket = useMemo(
    () =>
      visibleMarkets.find((item) => item.market_id === selectedMarketId) ??
      visibleMarkets[0] ??
      null,
    [selectedMarketId, visibleMarkets],
  );

  const selectedMarketMetrics = useMemo(() => {
    if (!selectedMarket) return null;
    const loanSymbol = selectedMarket.loan_symbol?.trim().toUpperCase() ?? '';
    const loanPriceUsd = loanSymbol ? (loanTokenPricesUsd[loanSymbol] ?? null) : null;
    const supplyAmount = normalizeTokenAmount(
      selectedMarket.total_supply_assets,
      selectedMarket.loan_decimals,
      selectedMarket.total_supply_assets_is_raw,
    );
    const borrowAmount = normalizeTokenAmount(
      selectedMarket.total_borrow_assets,
      selectedMarket.loan_decimals,
      selectedMarket.total_borrow_assets_is_raw,
    );
    const availableLiquidityAmount = normalizeTokenAmount(
      selectedMarket.available_liquidity,
      selectedMarket.loan_decimals,
      selectedMarket.available_liquidity_is_raw,
    );

    return {
      loanPriceUsd,
      supplyAmount,
      borrowAmount,
      availableLiquidityAmount,
      supplyUsd:
        supplyAmount !== null && loanPriceUsd !== null ? supplyAmount * loanPriceUsd : null,
      borrowUsd:
        borrowAmount !== null && loanPriceUsd !== null ? borrowAmount * loanPriceUsd : null,
      liquidityUsd:
        availableLiquidityAmount !== null && loanPriceUsd !== null
          ? availableLiquidityAmount * loanPriceUsd
          : null,
    };
  }, [loanTokenPricesUsd, selectedMarket]);

  const refreshedAtText = fetchedAt
    ? new Date(fetchedAt).toLocaleString('zh-CN', {
        hour12: false,
      })
    : 'N/A';

  return (
    <>
      <PageHero
        title="Morpho 市场页面"
        subtitle="聚合 Morpho 隔离市场静态配置与实时状态，快速查看总量、利率与风险标记。"
      />

      <div className="card morpho-detail-card morpho-market-toolbar">
        <div className="morpho-market-toolbar-copy">
          <strong>数据状态</strong>
          <span>
            最近更新 {refreshedAtText} {fromCache ? '· 缓存命中' : '· 实时拉取'}
          </span>
        </div>
        <div className="morpho-market-toolbar-actions">
          <button type="button" className="switch-btn" onClick={() => void reload()}>
            刷新数据
          </button>
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
            loanTokenPricesUsd={loanTokenPricesUsd}
            search={search}
            onSearchChange={setSearch}
            sortMode={sortMode}
            onSortModeChange={setSortMode}
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
                    <span className="morpho-summary-group-title">总量</span>
                    <div className="morpho-summary-group-grid">
                      <div className="metric-box">
                        <span className="metric-label">存款总量 (USD)</span>
                        <strong className="morpho-metric-strong">
                          {formatUsdFromNumber(selectedMarketMetrics?.supplyUsd ?? null)}
                        </strong>
                        <span className="justlend-caption">
                          {formatAmount(
                            selectedMarketMetrics?.supplyAmount ?? null,
                            selectedMarket.loan_symbol,
                          )}{' '}
                          × {formatUsdFromNumber(selectedMarketMetrics?.loanPriceUsd ?? null)}
                        </span>
                      </div>
                      <div className="metric-box">
                        <span className="metric-label">借款总量 (USD)</span>
                        <strong className="morpho-metric-strong">
                          {formatUsdFromNumber(selectedMarketMetrics?.borrowUsd ?? null)}
                        </strong>
                        <span className="justlend-caption">
                          {formatAmount(
                            selectedMarketMetrics?.borrowAmount ?? null,
                            selectedMarket.loan_symbol,
                          )}{' '}
                          × {formatUsdFromNumber(selectedMarketMetrics?.loanPriceUsd ?? null)}
                        </span>
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
                        <span className="metric-label">可用流动性 (USD)</span>
                        <strong className="morpho-metric-strong">
                          {formatUsdFromNumber(selectedMarketMetrics?.liquidityUsd ?? null)}
                        </strong>
                        <span className="justlend-caption">
                          {formatAmount(
                            selectedMarketMetrics?.availableLiquidityAmount ?? null,
                            selectedMarket.loan_symbol,
                          )}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="morpho-market-focus-extra">
                  <div className="morpho-market-focus-extra-title">市场关键指标</div>
                  <div className="table-wrap">
                    <table className="pos-table morpho-table morpho-market-focus-table">
                      <tbody>
                        <tr>
                          <th>利用率</th>
                          <td className="right">{formatPercent(selectedMarket.utilization)}</td>
                          <th>容量负载空间</th>
                          <td className="right">
                            {formatCapacityUsagePercent(selectedMarket.borrow_capacity_usage_rough)}
                          </td>
                        </tr>
                        <tr>
                          <th>loan token 单价</th>
                          <td className="right">
                            {formatUsdFromNumber(selectedMarketMetrics?.loanPriceUsd ?? null)}
                          </td>
                          <th></th>
                          <td className="right"></td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="morpho-keyline">
                  <div className="morpho-keyline-item">
                    <span>Market ID</span>
                    <strong className="mono">{selectedMarket.market_id}</strong>
                  </div>
                  <div className="morpho-keyline-item">
                    <span>Oracle</span>
                    <strong
                      className="mono morpho-full-address"
                      title={selectedMarket.oracle || ''}
                    >
                      {selectedMarket.oracle || 'N/A'}
                    </strong>
                  </div>
                  <div className="morpho-keyline-item">
                    <span>IRM</span>
                    <strong className="mono morpho-full-address" title={selectedMarket.irm || ''}>
                      {selectedMarket.irm || 'N/A'}
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
