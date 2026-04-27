import { useEffect, useState } from 'react';
import { fetchAssetPrice } from '../../../api';
import type { MorphoPositionResponse } from '../../../api/morpho';
import { ChartInfoButton, type ExplainItem } from '../../../components/ChartAssist';
import { AutoFitText } from '../../../shared/components/AutoFitText';
import { MorphoLtvRiskScale } from './MorphoLtvRiskScale';
import { MorphoPositionHistoryChart } from './MorphoPositionHistoryChart';
import { MorphoPositionTable } from './MorphoPositionTable';
import { PriceGauge } from './PriceGauge';

interface MorphoPersonalDashboardProps {
  address: string;
  marketId: string;
  protocol?: 'blue';
  data: MorphoPositionResponse | null;
  loading: boolean;
  notFound: boolean;
}

function toNum(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function formatDateTime(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return new Date(timestamp).toLocaleString();
}

function formatNumberCompact(value: number, digits: number = 2): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function isUsdLikeToken(symbol: string): boolean {
  const upper = symbol.trim().toUpperCase();
  return ['USDC', 'USDT', 'DAI', 'FRAX', 'TUSD', 'LUSD', 'GUSD', 'USDE', 'USDS', 'SUSD'].includes(
    upper,
  );
}

function gaugeColor(hf: number | null): string {
  if (hf === null) return '#94a3b8';
  if (hf <= 1.2) return '#ef4444';
  if (hf <= 1.8) return '#f59e0b';
  return '#22c55e';
}

function formatHealthFactorText(data: MorphoPositionResponse): string {
  if (!data.has_position) return '--';
  if (data.health_factor === null) {
    return toNum(data.borrow_assets) > 0 ? '--' : '∞';
  }
  return formatNumberCompact(toNum(data.health_factor), 2);
}

interface RiskState {
  label: string;
  tone: 'safe' | 'watch' | 'danger' | 'neutral';
  headline: string;
  description: string;
}

const explainItems: ExplainItem[] = [
  {
    term: 'LLTV',
    formula: 'Liquidation Loan-To-Value',
    meaning: '表示这组抵押资产在当前市场下能承受的最大借款比率，越接近上限越危险。',
    riskHint: '借款占可借上限比例越高，价格波动越容易把仓位推向清算边缘。',
  },
  {
    term: '健康因子',
    formula: '由协议返回，衡量仓位距离风险边界的安全缓冲',
    meaning: '大于 1 通常说明尚未触发清算，越高越安全。',
    riskHint: '若为空且没有借款，通常表示当前没有形成真实清算压力。',
  },
  {
    term: '抵押折算借款资产价值',
    formula: 'collateral_value_in_loan_asset',
    meaning: '把抵押品按 oracle 价格折算成借款资产口径后的价值，便于直接和借款规模比较。',
    riskHint: '它比单看抵押数量更适合判断实际融资空间。',
  },
];

function buildRiskTone(data: MorphoPositionResponse | null): RiskState {
  if (!data) {
    return {
      label: '等待查询',
      tone: 'neutral',
      headline: '等待 Morpho 单市场仓位结果',
      description: '输入地址和 market id 后即可查看 Morpho Blue 单市场仓位。',
    };
  }

  if (!data.has_position) {
    return {
      label: 'Safe',
      tone: 'neutral',
      headline: '状态：无仓位（Safe）',
      description: '该地址在当前 market id 下没有非零仓位，适合作为空仓基线检查。',
    };
  }

  if (!data.is_healthy) {
    return {
      label: 'Danger',
      tone: 'danger',
      headline: '状态：高风险（Danger）',
      description:
        '接口返回 is_healthy=false，当前仓位已被协议标记为不健康，需要尽快补抵押或降杠杆。',
    };
  }

  return {
    label: 'Safe',
    tone: 'safe',
    headline: '状态：安全（Safe）',
    description: '接口返回 is_healthy=true，当前仓位被协议标记为健康，但仍需关注抵押品价格变化。',
  };
}

export function MorphoPersonalDashboard({
  protocol = 'blue',
  data,
  loading,
  notFound,
}: MorphoPersonalDashboardProps) {
  const [loanTokenPrice, setLoanTokenPrice] = useState<number | undefined>(undefined);
  const risk = buildRiskTone(data);
  const riskToneClass =
    risk.tone === 'safe'
      ? 'morpho-risk-status-safe'
      : risk.tone === 'watch'
        ? 'morpho-risk-status-watch'
        : risk.tone === 'danger'
          ? 'morpho-risk-status-danger'
          : 'morpho-risk-status-neutral';

  useEffect(() => {
    if (!data?.loan_token) {
      setLoanTokenPrice(undefined);
      return;
    }

    let cancelled = false;

    fetchAssetPrice(data.loan_token)
      .then((price) => {
        if (!cancelled) setLoanTokenPrice(price);
      })
      .catch(() => {
        if (!cancelled) setLoanTokenPrice(undefined);
      });

    return () => {
      cancelled = true;
    };
  }, [data?.loan_token]);

  if (loading) {
    return (
      <div
        className="card"
        style={{ height: 420, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      >
        <div className="spinner"></div>
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="card morpho-overview-card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <span className="card-title">Morpho 个人账户分析</span>
            <ChartInfoButton title="Morpho 指标说明" items={explainItems} />
            <span className="badge" style={{ background: '#0f172a', color: '#cbd5e1' }}>
              {protocol.toUpperCase()}
            </span>
          </div>
        </div>
        <div className="morpho-banner morpho-banner-soft">
          <div className="morpho-banner-title">没有找到可用仓位</div>
          <div className="morpho-banner-copy">
            当前地址在这个 market id 下没有返回可展示的 Morpho Blue 仓位数据。
          </div>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const borrowAssets = toNum(data.borrow_assets);
  const debtValueUsd =
    loanTokenPrice !== undefined ? Math.abs(borrowAssets) * loanTokenPrice : undefined;
  const collateralAssets = toNum(data.collateral_assets);
  const collateralValueInLoanAsset = toNum(data.collateral_value_in_loan_asset);
  const currentPrice = toNum(data.price_quote);
  const oraclePredictedPrice = currentPrice;
  const currentHF = data.health_factor ? toNum(data.health_factor) : null;
  const lltvRatio = toNum(data.lltv_ratio);
  const lltvPercent = clamp(lltvRatio * 100, 0, 100);
  const quoteLooksUsd = isUsdLikeToken(data.loan_token_symbol);
  const priceUnit = `${data.loan_token_symbol}/${data.collateral_token_symbol}`;

  const currentLtvPercent =
    collateralValueInLoanAsset <= 0 ? 0 : (borrowAssets / collateralValueInLoanAsset) * 100;
  const liquidationThresholdPercent = lltvPercent;

  const liquidationPrice =
    borrowAssets <= 0 || collateralAssets <= 0 || lltvRatio <= 0
      ? null
      : borrowAssets / (collateralAssets * lltvRatio);

  const formatGaugePrice = (price: number) =>
    `${quoteLooksUsd ? '$' : ''}${formatNumberCompact(price, 4)}`;

  return (
    <div className="morpho-dashboard">
      <div className="card morpho-overview-card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <span className="card-title">Morpho 个人账户分析</span>
            <ChartInfoButton title="Morpho 指标说明" items={explainItems} />
            <span className="badge" style={{ background: '#0f172a', color: '#cbd5e1' }}>
              {protocol.toUpperCase()}
            </span>
            <span className={`badge ${riskToneClass}`}>{risk.label}</span>
          </div>
        </div>

        <div className="morpho-overview-grid">
          <div className="morpho-overview-copy">
            <div className="morpho-kicker">Single Market (Morpho Blue)</div>
            <h2 className="morpho-title">{risk.headline}</h2>
            <p className="morpho-copy">{risk.description}</p>
          </div>

          <div className="morpho-overview-side">
            <div className="morpho-overview-pills">
              <div className="morpho-overview-pill">
                <span className="morpho-overview-pill-label">数据源</span>
                <span className="morpho-overview-pill-value">
                  {data.data_source ? data.data_source.toUpperCase() : 'RPC'}
                </span>
              </div>
              <div className="morpho-overview-pill">
                <span className="morpho-overview-pill-label">快照时间</span>
                <span className="morpho-overview-pill-value" title={data.block_timestamp}>
                  {data.block_timestamp ? formatDateTime(data.block_timestamp) : '--'}
                </span>
              </div>
            </div>

            <div className="morpho-overview-tags">
              <div className="morpho-overview-tag">
                <span className="morpho-overview-tag-label">抵押资产</span>
                <span className="morpho-overview-tag-value">
                  {data.collateral_token_symbol} · {formatNumberCompact(collateralAssets, 6)}
                </span>
              </div>
              <div className="morpho-overview-tag">
                <span className="morpho-overview-tag-label">借款资产</span>
                <span className="morpho-overview-tag-value">
                  {data.loan_token_symbol} · {formatNumberCompact(borrowAssets, 6)}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="morpho-risk-layout morpho-risk-layout-focused">
        <div className="card morpho-risk-hero morpho-panel-card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">风险判断</span>
            <span className={`badge ${riskToneClass}`}>{risk.label}</span>
          </div>

          <div className="morpho-risk-hero-top">
            <div>
              <div className="morpho-kicker">Health Factor</div>
              <AutoFitText
                className="morpho-risk-health"
                text={formatHealthFactorText(data)}
                maxFontSizePx={64}
                minFontSizePx={28}
                fontWeight={800}
                style={{ color: gaugeColor(currentHF) }}
                useScientificWhenOverflow
                scientificIntegerDigitsThreshold={6}
              />
            </div>
            <div className="morpho-risk-health-copy">
              当前抵押折算价值约为{' '}
              <strong>{formatNumberCompact(collateralValueInLoanAsset, 6)}</strong>{' '}
              {data.loan_token_symbol}，借款规模为{' '}
              <strong>
                {debtValueUsd !== undefined
                  ? `$${formatNumberCompact(debtValueUsd, 2)}`
                  : formatNumberCompact(Math.abs(borrowAssets), 6)}
              </strong>
              {debtValueUsd === undefined && <> {data.loan_token_symbol}</>}
              。当当前报价接近清算阈值时，价格波动会快速压缩安全边际。
            </div>
          </div>

          <div className="morpho-risk-gauge-grid">
            <section className="morpho-risk-gauge-card morpho-risk-gauge-card-price">
              <div className="morpho-risk-gauge-heading">
                <span>清算缓冲</span>
                <span className="morpho-risk-gauge-tag">Buffer</span>
              </div>
              <p className="morpho-risk-gauge-note">
                左侧红点是清算价格，指针与高亮点表示当前报价；越靠右，安全边界越充足。
              </p>
              <PriceGauge
                className="price-gauge-no-stats"
                currentPrice={currentPrice}
                liquidationPrice={liquidationPrice}
                predictedPrice={oraclePredictedPrice}
                formatPrice={formatGaugePrice}
                priceUnit={priceUnit}
                showStats={false}
              />
            </section>

            <section className="morpho-risk-gauge-card morpho-risk-gauge-card-ltv">
              <MorphoLtvRiskScale
                currentLtvPercent={currentLtvPercent}
                lltvPercent={lltvPercent}
                liquidationThresholdPercent={liquidationThresholdPercent}
                isHealthy={data.is_healthy}
                formatPercent={(value) => `${formatNumberCompact(value, 2)}%`}
              />
            </section>
          </div>
        </div>
      </div>

      <MorphoPositionTable data={data} loading={loading} notFound={notFound} protocol={protocol} />

      <MorphoPositionHistoryChart
        address={data.address}
        marketId={data.market_id}
        protocol={protocol}
        loanTokenSymbol={data.loan_token_symbol}
        collateralTokenSymbol={data.collateral_token_symbol}
        debtAmount={Math.abs(borrowAssets)}
        collateralAmount={collateralAssets}
        lltv={lltvRatio}
      />
    </div>
  );
}
