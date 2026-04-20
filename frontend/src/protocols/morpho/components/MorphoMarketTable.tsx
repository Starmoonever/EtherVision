import type { MorphoMarketView } from '../../../hooks/useMorphoData';

interface MorphoMarketTableProps {
  markets: MorphoMarketView[];
  selectedMarketId: string;
  onSelectMarket: (marketId: string) => void;
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

function normalizeTokenAmount(
  value: string | null | undefined,
  decimals: number | null | undefined,
  isRaw: boolean,
): number | null {
  if (!value) return null;
  if (!isRaw) {
    return parseMetric(value);
  }

  const safeDecimals = Number.isInteger(decimals) ? Number(decimals) : 0;
  const trimmed = value.trim();
  if (!trimmed) return null;

  const negative = trimmed.startsWith('-');
  const digits = negative ? trimmed.slice(1) : trimmed;
  if (!/^\d+$/.test(digits)) {
    return parseMetric(value);
  }

  const paddedDigits = digits.padStart(safeDecimals + 1, '0');
  const integerPart =
    safeDecimals === 0 ? paddedDigits : paddedDigits.slice(0, paddedDigits.length - safeDecimals);
  const fractionalPart =
    safeDecimals === 0 ? '' : paddedDigits.slice(-safeDecimals).replace(/0+$/, '');
  const normalizedText = `${negative ? '-' : ''}${integerPart}${fractionalPart ? `.${fractionalPart}` : ''}`;
  const numeric = Number(normalizedText);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatPercent(value: string | null | undefined): string {
  const numeric = parseMetric(value);
  if (numeric === null) return 'N/A';
  const normalized = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return `${percentFormatter.format(normalized)}%`;
}

function formatLltv(value: string | null | undefined): string {
  const numeric = parseMetric(value);
  if (numeric === null) return 'N/A';
  const normalized = numeric <= 1 ? numeric * 100 : numeric;
  return `${percentFormatter.format(normalized)}%`;
}

function formatCompactTokenAmount(
  value: string | null | undefined,
  decimals: number | null | undefined,
  isRaw: boolean,
  symbol: string | null | undefined,
): string {
  const normalized = normalizeTokenAmount(value, decimals, isRaw);
  if (normalized === null) return 'N/A';
  const absolute = Math.abs(normalized);
  let amount: string;

  if (absolute >= 1_000_000_000) {
    amount = `${(normalized / 1_000_000_000).toFixed(2).replace(/\.?0+$/, '')}B`;
  } else if (absolute >= 1_000_000) {
    amount = `${(normalized / 1_000_000).toFixed(2).replace(/\.?0+$/, '')}M`;
  } else if (absolute >= 1_000) {
    amount = `${(normalized / 1_000).toFixed(2).replace(/\.?0+$/, '')}K`;
  } else {
    amount = normalized.toLocaleString('en-US', {
      minimumFractionDigits: normalized < 1 && normalized > -1 ? 2 : 0,
      maximumFractionDigits: 2,
    });
  }

  return symbol ? `${amount} ${symbol}` : amount;
}

function formatPercentNumber(value: string | null | undefined): number | null {
  const numeric = parseMetric(value);
  if (numeric === null) return null;
  return Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
}

function clampPercent(value: number | null): number {
  if (value === null) return 0;
  return Math.max(0, Math.min(value, 100));
}

export function MorphoMarketTable({
  markets,
  selectedMarketId,
  onSelectMarket,
}: MorphoMarketTableProps) {
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
            紧凑视图展示利率、流动性与容量占用，点击行可查看详情。
          </p>
        </div>
        <span className="badge badge-brand-soft">{markets.length} Markets</span>
      </div>

      <div className="table-wrap">
        <table className="pos-table morpho-table morpho-market-table morpho-market-table-compact">
          <thead>
            <tr>
              <th>市场</th>
              <th className="right">LLTV</th>
              <th className="right">存款总量 / 借款总量</th>
              <th className="right">存款 APY / 借款 APY</th>
              <th className="right">可用空间</th>
              <th>利用率</th>
              <th className="right">容量负载空间</th>
            </tr>
          </thead>
          <tbody>
            {markets.map((market) => {
              const isSelected = market.market_id === selectedMarketId;
              const utilizationPercent = formatPercentNumber(market.utilization);
              const borrowCapacityUsagePercent = formatPercentNumber(
                market.borrow_capacity_usage_rough,
              );
              const isOverBorrowCapacity =
                borrowCapacityUsagePercent !== null && borrowCapacityUsagePercent > 100;

              return (
                <tr
                  key={market.market_id}
                  className={
                    isSelected ? 'morpho-market-row morpho-market-row-active' : 'morpho-market-row'
                  }
                  onClick={() => onSelectMarket(market.market_id)}
                >
                  <td>
                    <div className="morpho-market-name-cell">
                      <strong className="token-symbol">
                        {market.collateral_symbol || '?'} / {market.loan_symbol || '?'}
                      </strong>
                      <span className="mono morpho-market-id">
                        {market.market_id.slice(0, 10)}...{market.market_id.slice(-6)}
                      </span>
                    </div>
                  </td>
                  <td className="right">
                    <span className="morpho-compact-metric">{formatLltv(market.lltv)}</span>
                  </td>
                  <td className="right">
                    <div className="morpho-rate-stack">
                      <span className="morpho-rate-line morpho-rate-line-supply">
                        存款{' '}
                        {formatCompactTokenAmount(
                          market.total_supply_assets,
                          market.loan_decimals,
                          market.total_supply_assets_is_raw,
                          market.loan_symbol,
                        )}
                      </span>
                      <span className="morpho-rate-line morpho-rate-line-borrow">
                        借款{' '}
                        {formatCompactTokenAmount(
                          market.total_borrow_assets,
                          market.loan_decimals,
                          market.total_borrow_assets_is_raw,
                          market.loan_symbol,
                        )}
                      </span>
                    </div>
                  </td>
                  <td className="right">
                    <div className="morpho-rate-stack">
                      <span className="morpho-rate-line morpho-rate-line-supply">
                        存款 {formatPercent(market.supply_apy)}
                      </span>
                      <span className="morpho-rate-line morpho-rate-line-borrow">
                        借款 {formatPercent(market.borrow_apy)}
                      </span>
                    </div>
                  </td>
                  <td className="right">
                    <span className="morpho-compact-metric">
                      {formatCompactTokenAmount(
                        market.available_liquidity,
                        market.loan_decimals,
                        market.available_liquidity_is_raw,
                        market.loan_symbol,
                      )}
                    </span>
                  </td>
                  <td>
                    <div className="morpho-utilization-cell">
                      <div className="morpho-utilization-bar" aria-hidden="true">
                        <span
                          className="morpho-utilization-fill"
                          style={{ width: `${clampPercent(utilizationPercent)}%` }}
                        />
                      </div>
                      <span className="morpho-utilization-value">
                        {utilizationPercent === null
                          ? 'N/A'
                          : `${percentFormatter.format(utilizationPercent)}%`}
                      </span>
                    </div>
                  </td>
                  <td className="right">
                    <span
                      className={
                        isOverBorrowCapacity
                          ? 'morpho-compact-metric morpho-compact-metric-danger'
                          : 'morpho-compact-metric'
                      }
                    >
                      {borrowCapacityUsagePercent === null
                        ? 'N/A'
                        : `${percentFormatter.format(borrowCapacityUsagePercent)}%`}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
