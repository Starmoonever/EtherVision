import { useEffect, useState } from 'react';
import type { MorphoPositionResponse } from '../api/morpho';
import { fetchEthPrice } from '../api/price';
import { ChartInfoButton, type ExplainItem } from './ChartAssist';
import { MorphoPositionTable } from './MorphoPositionTable';
import { MorphoSummaryCard } from './MorphoSummaryCard';

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

function formatCompactAddress(value: string): string {
  if (value.length <= 16) return value;
  return `${value.slice(0, 8)}…${value.slice(-6)}`;
}

function formatNumberCompact(value: number, digits: number = 2): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
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

  if (!data.health_factor) {
    return {
      label: 'Safe',
      tone: 'safe',
      headline: '状态：安全（Safe）',
      description: '接口没有返回健康因子，通常意味着没有活跃借款或当前仓位尚未进入风险计算区间。',
    };
  }
  // 健康因子小于 1 的话，说明已经处于清算边缘了，但是没有展示
  const hf = toNum(data.health_factor);
  if (hf < 1.1) {
    return {
      label: 'Danger',
      tone: 'danger',
      headline: '状态：高风险（Danger）',
      description: '健康因子已经靠近清算边缘，需要尽快补抵押或降杠杆。',
    };
  }
  if (hf < 1.5) {
    return {
      label: 'Warning',
      tone: 'watch',
      headline: '状态：需观察（Warning）',
      description: '仓位仍有缓冲，但价格波动可能快速压缩借款安全边际。',
    };
  }

  return {
    label: 'Safe',
    tone: 'safe',
    headline: '状态：安全（Safe）',
    description: '当前仓位与 LLTV 尚有一定距离，但仍需关注抵押品价格变化。',
  };
}

export function MorphoPersonalDashboard({
  address,
  marketId,
  protocol = 'blue',
  data,
  loading,
  notFound,
}: MorphoPersonalDashboardProps) {
  const risk = buildRiskTone(data);
  const riskToneClass =
    risk.tone === 'safe'
      ? 'justlend-risk-safe'
      : risk.tone === 'watch'
        ? 'justlend-risk-watch'
        : risk.tone === 'danger'
          ? 'justlend-risk-danger'
          : 'justlend-risk-neutral';

  const [externalEthPrice, setExternalEthPrice] = useState<number | null>(null);

  useEffect(() => {
    if (!data || data.loan_token_symbol.toUpperCase() !== 'WETH') return;
    let cancelled = false;
    void fetchEthPrice()
      .then((price) => !cancelled && setExternalEthPrice(price))
      .catch(() => !cancelled && setExternalEthPrice(null));
    return () => {
      cancelled = true;
    };
  }, [data]);

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
      <div className="card justlend-overview-card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <span className="card-title">Morpho 个人账户分析</span>
            <ChartInfoButton title="Morpho 指标说明" items={explainItems} />
            <span className="badge" style={{ background: '#0f172a', color: '#cbd5e1' }}>
              {protocol.toUpperCase()}
            </span>
          </div>
          <span className="address-badge">{formatCompactAddress(address)}</span>
        </div>
        <div className="justlend-banner justlend-banner-soft">
          <div className="justlend-banner-title">没有找到可用仓位</div>
          <div className="justlend-banner-copy">
            当前地址在这个 market id 下没有返回可展示的 Morpho Blue 仓位数据。
          </div>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const borrowAssets = toNum(data.borrow_assets);
  const supplyAssets = toNum(data.supply_assets);
  const collateralAssets = toNum(data.collateral_assets);
  const collateralValueInLoanAsset = toNum(data.collateral_value_in_loan_asset);
  const maxBorrowable = toNum(data.max_borrowable_in_loan_asset);
  const currentPrice = toNum(data.price_quote);
  const currentHF = data.health_factor ? toNum(data.health_factor) : null;
  const lltvRatio = toNum(data.lltv_ratio);
  const lltvPercent = clamp(lltvRatio * 100, 0, 100);

  const borrowUtilPercent =
    maxBorrowable <= 0 ? 0 : clamp((borrowAssets / maxBorrowable) * 100, 0, 100);

  const riskGap = Math.max(0, lltvPercent - borrowUtilPercent);
  const bulletMarkersTooClose = Math.abs(lltvPercent - borrowUtilPercent) < 10;

  const liquidationPrice =
    borrowAssets <= 0 || collateralAssets <= 0 || lltvRatio <= 0
      ? null
      : borrowAssets / (collateralAssets * lltvRatio);

  const liquidationBuffer =
    liquidationPrice === null || currentPrice <= 0
      ? null
      : Math.max(0, ((currentPrice - liquidationPrice) / currentPrice) * 100);

  const borrowHeadroom = Math.max(0, maxBorrowable - borrowAssets);

  return (
    <div className="justlend-dashboard">
      <div className="card justlend-overview-card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <span className="card-title">Morpho 个人账户分析</span>
            <ChartInfoButton title="Morpho 指标说明" items={explainItems} />
            <span className="badge" style={{ background: '#0f172a', color: '#cbd5e1' }}>
              {protocol.toUpperCase()}
            </span>
            <span className={`badge ${riskToneClass}`}>{risk.label}</span>
          </div>
          <span className="address-badge" title={address}>
            {formatCompactAddress(address)}
          </span>
        </div>

        <div className="justlend-overview-grid">
          <div className="justlend-overview-copy">
            <div className="justlend-market-kicker">Single Market (Morpho Blue)</div>
            <h2 className="justlend-market-title">{risk.headline}</h2>
            <p className="justlend-market-copy">{risk.description}</p>
          </div>

          <div className="justlend-overview-side">
            <div className="justlend-overview-pills">
              <div className="justlend-overview-pill">
                <span className="justlend-overview-pill-label">Market ID</span>
                <span className="justlend-overview-pill-value mono" title={marketId}>
                  {marketId.slice(0, 10)}…{marketId.slice(-8)}
                </span>
              </div>
              <div className="justlend-overview-pill">
                <span className="justlend-overview-pill-label">数据源</span>
                <span className="justlend-overview-pill-value">
                  {data.data_source ? data.data_source.toUpperCase() : 'RPC'}
                </span>
              </div>
              <div className="justlend-overview-pill">
                <span className="justlend-overview-pill-label">快照时间</span>
                <span className="justlend-overview-pill-value" title={data.block_timestamp}>
                  {data.block_timestamp ? formatDateTime(data.block_timestamp) : '--'}
                </span>
              </div>
            </div>

            <div className="justlend-overview-tags">
              <div className="justlend-overview-tag">
                <span className="justlend-overview-tag-label">抵押资产</span>
                <span className="justlend-overview-tag-value">
                  {data.collateral_token_symbol} · {formatNumberCompact(collateralAssets, 6)}
                </span>
              </div>
              <div className="justlend-overview-tag">
                <span className="justlend-overview-tag-label">借款资产</span>
                <span className="justlend-overview-tag-value">
                  {data.loan_token_symbol} · {formatNumberCompact(borrowAssets, 6)}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="summary-grid justlend-summary-grid">
        <div className="metric-box">
          <span className="metric-label">健康因子</span>
          <span className="metric-value" style={{ color: gaugeColor(currentHF) }}>
            {formatHealthFactorText(data)}
          </span>
        </div>
        <div className="metric-box">
          <span className="metric-label">借款使用率</span>
          <span className="metric-value blue">{formatNumberCompact(borrowUtilPercent, 2)}%</span>
        </div>
        <div className="metric-box">
          <span className="metric-label">LLTV 上限</span>
          <span className="metric-value blue">{formatNumberCompact(lltvPercent, 2)}%</span>
        </div>
        <div className="metric-box">
          <span className="metric-label">剩余安全边际</span>
          <span className="metric-value blue">{formatNumberCompact(riskGap, 2)}%</span>
        </div>
        <div className="metric-box">
          <span className="metric-label">最大可借</span>
          <span className="metric-value blue">{formatNumberCompact(maxBorrowable, 6)}</span>
        </div>
        <div className="metric-box">
          <span className="metric-label">可借余量</span>
          <span className="metric-value blue">{formatNumberCompact(borrowHeadroom, 6)}</span>
        </div>
      </div>

      <div className="justlend-risk-layout">
        <div className="card justlend-risk-hero morpho-panel-card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">风险判断</span>
            <span className={`badge ${riskToneClass}`}>{risk.label}</span>
          </div>

          <div className="justlend-risk-hero-top">
            <div>
              <div className="justlend-market-kicker">Health Factor</div>
              <div className="justlend-risk-health" style={{ color: gaugeColor(currentHF) }}>
                {formatHealthFactorText(data)}
              </div>
            </div>
            <div className="justlend-risk-health-copy">
              当前抵押折算价值约为{' '}
              <strong>{formatNumberCompact(collateralValueInLoanAsset, 6)}</strong>{' '}
              {data.loan_token_symbol}，借款规模为{' '}
              <strong>{formatNumberCompact(borrowAssets, 6)}</strong> {data.loan_token_symbol}
              。当借款使用率接近 LLTV 上限时，价格波动会快速压缩安全边际。
            </div>
          </div>

          <div className="justlend-bullet-shell">
            <div className="justlend-bullet-header">
              <span className="justlend-bullet-title">借款使用率 vs LLTV</span>
              <strong>
                {formatNumberCompact(borrowUtilPercent, 2)}% / {formatNumberCompact(lltvPercent, 2)}
                %
              </strong>
            </div>
            <div className="justlend-bullet-track">
              <div
                className={`justlend-bullet-marker justlend-bullet-marker-current ${
                  bulletMarkersTooClose ? 'justlend-bullet-marker-stagger-left' : ''
                }`}
                style={{ left: `${borrowUtilPercent}%` }}
              >
                <span>当前</span>
              </div>
              <div
                className={`justlend-bullet-marker justlend-bullet-marker-threshold ${
                  bulletMarkersTooClose ? 'justlend-bullet-marker-stagger-right' : ''
                }`}
                style={{ left: `${lltvPercent}%` }}
              >
                <span>LLTV</span>
              </div>
            </div>
            <div className="justlend-bullet-footer">
              <span>安全区</span>
              <span>观察区</span>
              <span>敏感区</span>
            </div>
          </div>

          <div className="justlend-risk-markers">
            <div className="justlend-risk-marker">
              <span className="justlend-risk-dot" style={{ background: '#38bdf8' }} />
              <span>当前借款使用率</span>
              <strong>{formatNumberCompact(borrowUtilPercent, 2)}%</strong>
            </div>
            <div className="justlend-risk-marker">
              <span className="justlend-risk-dot" style={{ background: '#ef4444' }} />
              <span>LLTV 上限</span>
              <strong>{formatNumberCompact(lltvPercent, 2)}%</strong>
            </div>
            <div className="justlend-risk-marker">
              <span className="justlend-risk-dot" style={{ background: '#22c55e' }} />
              <span>剩余安全边际</span>
              <strong>{formatNumberCompact(riskGap, 2)}%</strong>
            </div>
          </div>
        </div>

        <div className="justlend-risk-side">
          <div className="justlend-insight-grid">
            <div className="metric-box">
              <span className="metric-label">Oracle 报价</span>
              <span className="metric-value blue">${formatNumberCompact(currentPrice, 6)}</span>
            </div>
            <div className="metric-box">
              <span className="metric-label">清算触发价</span>
              <span className="metric-value red">
                {liquidationPrice === null ? '--' : `$${formatNumberCompact(liquidationPrice, 6)}`}
              </span>
            </div>
            <div className="metric-box">
              <span className="metric-label">清算缓冲</span>
              <span className="metric-value blue">
                {liquidationBuffer === null
                  ? borrowAssets > 0
                    ? '--'
                    : '∞'
                  : `${formatNumberCompact(liquidationBuffer, 2)}%`}
              </span>
            </div>
            <div className="metric-box">
              <span className="metric-label">外部 ETH 参考价</span>
              <span className="metric-value blue">
                {externalEthPrice ? `$${formatNumberCompact(externalEthPrice, 2)}` : '--'}
              </span>
            </div>
          </div>

          <div className="justlend-banner justlend-banner-soft">
            <div className="justlend-banner-title">快速解读</div>
            <div className="justlend-banner-copy">
              当前供应为 <strong>{formatNumberCompact(supplyAssets, 6)}</strong>，抵押为{' '}
              <strong>{formatNumberCompact(collateralAssets, 6)}</strong>，借款为{' '}
              <strong>{formatNumberCompact(borrowAssets, 6)}</strong>
              。若借款持续上升或抵押折算价值下滑，请优先关注“借款使用率 vs LLTV”的差距是否快速收敛。
            </div>
          </div>
        </div>
      </div>

      <MorphoSummaryCard
        address={address}
        marketId={marketId}
        protocol={protocol}
        data={data}
        loading={loading}
        notFound={notFound}
      />
      <MorphoPositionTable data={data} loading={loading} notFound={notFound} protocol={protocol} />
    </div>
  );
}
