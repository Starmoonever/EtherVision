import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  fetchJustLendPositionWithMeta,
  type JustLendPositionAsset,
  type JustLendPositionResponse,
} from '../api/justlend';
import { mergeRequestMetas, type AggregatedRequestMeta } from '../api/requestMeta';
import { ChartDataStatus, ChartInfoButton, type ExplainItem } from './ChartAssist';
import { JustLendPositionReplayChart } from './JustLendPositionReplayChart';
import { AutoFitText } from '../shared/components/AutoFitText';
import { justLendChartTheme } from './justlendTheme';

interface JustLendPersonalDashboardProps {
  address: string;
}

interface AllocationItem {
  name: string;
  value: number;
  amount: number;
  valueUsd: number;
}

interface ExposureItem {
  asset: string;
  collateral: number;
  borrow: number;
}

interface RiskState {
  label: string;
  tone: 'safe' | 'watch' | 'danger' | 'neutral';
  headline: string;
  description: string;
}

const collateralColors = justLendChartTheme.palettes.collateral;
const borrowColors = justLendChartTheme.palettes.borrow;

const explainItems: ExplainItem[] = [
  {
    term: '总抵押 / 总债务',
    formula: 'sum(collateral value_usd) / sum(borrow value_usd)',
    meaning: '衡量账户当前在 JustLend 的抵押规模与借款规模。',
    riskHint: '总债务若持续接近总抵押可承受上限，健康因子会快速恶化。',
  },
  {
    term: 'LTV 与 清算阈值',
    formula: 'ltv / liquidation_threshold',
    meaning: 'LTV 表示当前借款使用率，清算阈值表示仓位被清算的边界。',
    riskHint: 'LTV 越靠近清算阈值，账户价格波动容忍度越低。',
  },
  {
    term: '资产构成',
    formula: '按 side=collateral 或 borrow 聚合 value_usd',
    meaning: '帮助你看清仓位集中在哪些抵押资产和债务资产。',
    riskHint: '单一资产过度集中时，局部波动会显著放大账户风险。',
  },
];

const riskScoreExplainItems: ExplainItem[] = [
  {
    term: '风险评分基准',
    formula: 'score = 96 - hfPenalty - gapPenalty - concentrationPenalty',
    meaning:
      '前端从 96 分起步，再根据健康因子、安全边际和集中度逐项扣分，最后把结果限制在 6 到 99 之间。',
    riskHint: '分数越高代表越稳健，越低代表越接近风险区。',
  },
  {
    term: '健康因子扣分',
    formula: 'health_factor 越低，hfPenalty 越高',
    meaning: '健康因子是最核心的安全指标，越接近 1，扣分越明显；无穷大时这项不扣分。',
    riskHint: '如果健康因子已经接近 1，分数会快速下滑。',
  },
  {
    term: '安全边际扣分',
    formula: 'riskGap = liquidation_threshold - ltv',
    meaning: 'LTV 越接近清算阈值，说明剩余缓冲越薄，系统会增加 gapPenalty。',
    riskHint: '即使健康因子暂时不差，LTV 太贴近阈值也会把分数拉低。',
  },
  {
    term: '集中度扣分',
    formula: 'max(topCollateralShare, topBorrowShare)',
    meaning: '如果抵押或债务过度集中在单一资产上，会增加 concentrationPenalty。',
    riskHint: '单一资产占比过高时，局部波动更容易伤到整个仓位。',
  },
];

function toNum(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function ratioToPercent(value: string | number): number {
  const num = toNum(value);
  return num <= 1 ? num * 100 : num;
}

function formatUsd(value: string | number): string {
  return `$${toNum(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatVaultNumber(value: string | number, options: { currency?: boolean } = {}): string {
  const num = toNum(value);
  if (!Number.isFinite(num)) return options.currency ? '$--' : '--';

  const sign = num < 0 ? '-' : '';
  const absolute = Math.abs(num);
  const prefix = options.currency ? '$' : '';

  if (absolute > 1_000_000_000_000_000) {
    return `${sign}${prefix}${absolute.toExponential(2)}`;
  }

  if (absolute < 1_000_000_000) {
    return `${sign}${prefix}${absolute.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }

  const suffixes = [
    { threshold: 1_000_000_000_000_000, suffix: 'Q' },
    { threshold: 1_000_000_000_000, suffix: 'T' },
    { threshold: 1_000_000_000, suffix: 'B' },
  ];

  const matched = suffixes.find((item) => absolute >= item.threshold);
  if (matched) {
    return `${sign}${prefix}${(absolute / matched.threshold).toFixed(1)}${matched.suffix}`;
  }

  return `${sign}${prefix}${absolute.toExponential(1)}`;
}

function formatUsdAxis(value: number): string {
  const absolute = Math.abs(value);
  return `$${Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: absolute >= 1000 ? 1 : 0,
  }).format(absolute)}`;
}

function formatPercentRatio(value: string | number): string {
  return `${ratioToPercent(value).toFixed(2)}%`;
}

function formatHealthFactor(value: string | number): string {
  const raw = String(value).trim().toLowerCase();
  if (raw === 'inf' || raw === 'infinity') return '∞';
  const parsed = toNum(value);
  if (!Number.isFinite(parsed) || parsed >= 1e12) return '∞';
  return parsed.toFixed(2);
}

function formatDateTime(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return new Date(timestamp).toLocaleString();
}

function summarizeAssets(
  assets: JustLendPositionAsset[],
  side: 'collateral' | 'borrow',
): AllocationItem[] {
  const aggregated = new Map<string, { amount: number; valueUsd: number }>();

  for (const asset of assets) {
    if (asset.side !== side) continue;
    const symbol = asset.symbol || asset.asset_address;
    const current = aggregated.get(symbol) || { amount: 0, valueUsd: 0 };
    current.amount += toNum(asset.amount);
    current.valueUsd += toNum(asset.value_usd);
    aggregated.set(symbol, current);
  }

  const total = Array.from(aggregated.values()).reduce((sum, item) => sum + item.valueUsd, 0);
  return Array.from(aggregated.entries())
    .map(([name, item]) => ({
      name,
      value: total > 0 ? (item.valueUsd / total) * 100 : 0,
      amount: item.amount,
      valueUsd: item.valueUsd,
    }))
    .sort((a, b) => b.value - a.value);
}

function buildExposureData(assets: JustLendPositionAsset[]): ExposureItem[] {
  const aggregated = new Map<string, ExposureItem>();

  for (const asset of assets) {
    const key = asset.symbol || asset.asset_address;
    const current = aggregated.get(key) || {
      asset: key,
      collateral: 0,
      borrow: 0,
    };

    if (asset.side === 'collateral') {
      current.collateral += toNum(asset.value_usd);
    } else if (asset.side === 'borrow') {
      current.borrow += toNum(asset.value_usd);
    }

    aggregated.set(key, current);
  }

  return Array.from(aggregated.values()).sort(
    (a, b) => b.collateral + b.borrow - (a.collateral + a.borrow),
  );
}

function sumTopShare(items: AllocationItem[], count: number): number {
  return items.slice(0, count).reduce((sum, item) => sum + item.value, 0);
}

function buildRiskState(
  data: JustLendPositionResponse,
  riskGap: number,
  totalCollateralUsd: number,
  totalDebtUsd: number,
): RiskState {
  const healthFactor = formatHealthFactor(data.health_factor);

  if (totalDebtUsd <= 0) {
    return {
      label: '无借款风险',
      tone: 'neutral',
      headline: '当前账户没有活跃债务',
      description: '仓位目前主要是抵押资产展示，不存在逼近清算线的借款压力。',
    };
  }

  if (totalCollateralUsd <= 0) {
    return {
      label: '异常仓位',
      tone: 'danger',
      headline: '检测到债务但缺少抵押',
      description: '当前返回结果不具备正常借贷结构，建议先回查后端数据源与地址状态。',
    };
  }

  if (healthFactor === '∞') {
    return {
      label: '安全缓冲充足',
      tone: 'safe',
      headline: '健康因子显示为无穷大',
      description: '当前账户对价格波动的容忍度较高，短期内没有明显清算压力。',
    };
  }

  const hf = toNum(data.health_factor);
  if (hf < 1.1 || riskGap < 5) {
    return {
      label: '高风险',
      tone: 'danger',
      headline: 'LTV 已经逼近清算阈值',
      description: '需要尽快补充抵押或降低债务，否则价格波动会迅速压缩安全边际。',
    };
  }

  if (hf < 1.5 || riskGap < 12) {
    return {
      label: '需重点观察',
      tone: 'watch',
      headline: '账户仍有缓冲，但已经进入敏感区',
      description: '仓位还能承受有限波动，不过单一资产回撤或债务放大都会明显恶化风险。',
    };
  }

  return {
    label: '相对稳健',
    tone: 'safe',
    headline: `当前健康因子为 ${formatHealthFactor(data.health_factor)}`,
    description: '账户离清算阈值仍有一定距离，建议继续关注资产集中度和借款扩张速度。',
  };
}

function buildRiskScore(
  data: JustLendPositionResponse,
  riskGap: number,
  totalCollateralUsd: number,
  totalDebtUsd: number,
  topCollateralShare: number,
  topBorrowShare: number,
): number {
  if (totalDebtUsd <= 0) return 96;
  if (totalCollateralUsd <= 0) return 8;

  const raw = String(data.health_factor).trim().toLowerCase();
  const healthFactor = toNum(data.health_factor);
  const infiniteHealth =
    raw === 'inf' || raw === 'infinity' || !Number.isFinite(healthFactor) || healthFactor >= 1e12;

  const hfPenalty = infiniteHealth
    ? 0
    : clamp((1.4 - healthFactor) * 30, 0, 42) + clamp((2.2 - healthFactor) * 5, 0, 12);
  const gapPenalty = clamp((12 - riskGap) * 3.2, 0, 36) + clamp((25 - riskGap) * 0.8, 0, 10);
  const concentrationPenalty = clamp(
    (Math.max(topCollateralShare, topBorrowShare) - 45) * 0.7,
    0,
    18,
  );

  return Math.round(clamp(96 - hfPenalty - gapPenalty - concentrationPenalty, 6, 99));
}

function riskScoreLabel(score: number): string {
  if (score >= 85) return '稳健';
  if (score >= 70) return '可控';
  if (score >= 55) return '需关注';
  return '高压';
}

function riskScoreTone(score: number): string {
  if (score >= 85) return '#22c55e';
  if (score >= 70) return '#38bdf8';
  if (score >= 55) return '#f59e0b';
  return '#ef4444';
}

export function JustLendPersonalDashboard({ address }: JustLendPersonalDashboardProps) {
  const [data, setData] = useState<JustLendPositionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [meta, setMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError('');

      try {
        const result = await fetchJustLendPositionWithMeta(address, 'trx');
        if (cancelled) return;
        setData(result.data);
        setMeta(mergeRequestMetas([result.meta]));
      } catch (loadError) {
        if (cancelled) return;
        setData(null);
        setError(loadError instanceof Error ? loadError.message : '无法加载 JustLend 仓位');
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    if (address) {
      void load();
    }

    return () => {
      cancelled = true;
    };
  }, [address]);

  const collateralData = useMemo(() => summarizeAssets(data?.assets || [], 'collateral'), [data]);
  const borrowData = useMemo(() => summarizeAssets(data?.assets || [], 'borrow'), [data]);
  const exposureData = useMemo(() => buildExposureData(data?.assets || []), [data]);

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

  if (error) {
    return (
      <div className="card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <span className="card-title">JustLend 个人账户分析</span>
            <span className="badge green-badge">TRON</span>
          </div>
          <span className="address-badge">{address}</span>
        </div>
        <div className="justlend-banner justlend-banner-warn">
          <div className="justlend-banner-title">后端暂未返回可用仓位数据</div>
          <div className="justlend-banner-copy">{error}</div>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div
        className="card"
        style={{ height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      >
        <span style={{ color: '#94a3b8' }}>暂无 JustLend 仓位数据</span>
      </div>
    );
  }

  const totalCollateralUsd = toNum(data.total_collateral_usd);
  const totalDebtUsd = toNum(data.total_debt_usd);
  const availableBorrowUsd = toNum(data.available_borrow_usd);
  const ltvPercent = ratioToPercent(data.ltv);
  const thresholdPercent = ratioToPercent(data.liquidation_threshold);
  const riskGap = Math.max(0, thresholdPercent - ltvPercent);
  const collateralCount = data.assets.filter((asset) => asset.side === 'collateral').length;
  const borrowCount = data.assets.filter((asset) => asset.side === 'borrow').length;
  const riskState = buildRiskState(data, riskGap, totalCollateralUsd, totalDebtUsd);
  const topCollateral = collateralData[0];
  const topBorrow = borrowData[0];
  const topCollateralShare = topCollateral?.value ?? 0;
  const topBorrowShare = topBorrow?.value ?? 0;
  const collateralTop3Share = sumTopShare(collateralData, 3);
  const borrowTop3Share = sumTopShare(borrowData, 3);
  const riskScore = buildRiskScore(
    data,
    riskGap,
    totalCollateralUsd,
    totalDebtUsd,
    topCollateralShare,
    topBorrowShare,
  );
  const riskScoreColor = riskScoreTone(riskScore);
  const capacityBase = totalDebtUsd + availableBorrowUsd;
  const capacityUsedPct = capacityBase > 0 ? (totalDebtUsd / capacityBase) * 100 : 0;
  const capacityRemainingPct = capacityBase > 0 ? (availableBorrowUsd / capacityBase) * 100 : 0;
  const bilateralData = exposureData.slice(0, 8).map((item) => ({
    asset: item.asset,
    collateral: item.collateral,
    borrow: item.borrow * -1,
  }));
  const bilateralDomainMax =
    Math.max(
      1,
      ...bilateralData.map((item) => Math.max(Math.abs(item.collateral), Math.abs(item.borrow))),
    ) * 1.15;
  const bulletMarkersTooClose = Math.abs(thresholdPercent - ltvPercent) < 10;

  const summaryItems = [
    {
      label: '总抵押价值',
      value: formatVaultNumber(data.total_collateral_usd, { currency: true }),
      tone: 'green' as const,
    },
    {
      label: '总债务价值',
      value: formatVaultNumber(data.total_debt_usd, { currency: true }),
      tone: 'red' as const,
    },
    {
      label: '剩余可借额度',
      value: formatVaultNumber(data.available_borrow_usd, { currency: true }),
      tone: 'blue' as const,
    },
    { label: '健康因子', value: formatHealthFactor(data.health_factor), tone: 'blue' as const },
    { label: 'LTV', value: formatPercentRatio(data.ltv), tone: 'blue' as const },
    {
      label: '清算阈值',
      value: formatPercentRatio(data.liquidation_threshold),
      tone: 'blue' as const,
    },
  ];

  const insightItems = [
    {
      label: '剩余安全边际',
      value: `${riskGap.toFixed(2)}%`,
      toneClass: 'blue',
    },
    {
      label: '最大抵押集中度',
      value: topCollateral ? `${topCollateral.name} ${topCollateral.value.toFixed(2)}%` : '--',
      toneClass: 'green',
    },
    {
      label: '最大债务集中度',
      value: topBorrow ? `${topBorrow.name} ${topBorrow.value.toFixed(2)}%` : '--',
      toneClass: 'red',
    },
    {
      label: '仓位明细数量',
      value: `${data.assets.length} 项`,
      toneClass: 'blue',
    },
  ];
  const concentrationRows = [
    {
      label: '最大抵押集中度',
      percent: topCollateralShare,
      hint: topCollateral ? `${topCollateral.name} 为第一大抵押资产` : '暂无抵押资产',
      tone: 'green',
    },
    {
      label: '最大债务集中度',
      percent: topBorrowShare,
      hint: topBorrow ? `${topBorrow.name} 为第一大债务资产` : '暂无债务资产',
      tone: 'red',
    },
    {
      label: '抵押前 3 占比',
      percent: collateralTop3Share,
      hint: `${collateralCount} 个抵押仓位`,
      tone: 'blue',
    },
    {
      label: '债务前 3 占比',
      percent: borrowTop3Share,
      hint: `${borrowCount} 个债务仓位`,
      tone: 'blue',
    },
  ];

  const riskToneClass =
    riskState.tone === 'safe'
      ? 'justlend-risk-safe'
      : riskState.tone === 'watch'
        ? 'justlend-risk-watch'
        : riskState.tone === 'danger'
          ? 'justlend-risk-danger'
          : 'justlend-risk-neutral';
  const overviewMetaItems = [
    { label: '地址', value: data.address, mono: true },
    { label: '快照时间', value: formatDateTime(data.snapshot_at) },
    { label: '底层数据时间', value: formatDateTime(data.block_timestamp) },
    { label: '数据来源', value: data.data_source },
  ];
  const overviewCountItems = [
    { label: '抵押资产数', value: `${collateralCount}` },
    { label: '债务资产数', value: `${borrowCount}` },
  ];

  return (
    <div className="justlend-dashboard">
      <div className="card justlend-overview-card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <span className="card-title">JustLend 个人账户分析</span>
            <ChartInfoButton title="JustLend 指标说明" items={explainItems} />
            <span className="badge green-badge">{String(data.chain).toUpperCase()}</span>
            <span className="badge" style={{ background: '#0f172a', color: '#cbd5e1' }}>
              {data.protocol}
            </span>
            <span className={`badge ${riskToneClass}`}>{riskState.label}</span>
          </div>
          <ChartDataStatus meta={meta} />
        </div>

        <div className="justlend-overview-grid">
          <div className="justlend-overview-copy">
            <div className="justlend-market-kicker">Position Overview</div>
            <h2 className="justlend-market-title">{riskState.headline}</h2>
            <p className="justlend-market-copy">{riskState.description}</p>
          </div>

          <div className="justlend-overview-side">
            <div className="justlend-overview-pills">
              {overviewMetaItems.map((item) => (
                <div key={item.label} className="justlend-overview-pill">
                  <span className="justlend-overview-pill-label">{item.label}</span>
                  <span
                    className={`justlend-overview-pill-value ${item.mono ? 'mono' : ''}`}
                    title={item.value}
                  >
                    {item.value}
                  </span>
                </div>
              ))}
            </div>

            <div className="justlend-overview-tags">
              {overviewCountItems.map((item) => (
                <div key={item.label} className="justlend-overview-tag">
                  <span className="justlend-overview-tag-label">{item.label}</span>
                  <span className="justlend-overview-tag-value" title={item.value}>
                    {item.value}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="summary-grid justlend-summary-grid">
        {summaryItems.map((item) => (
          <div key={item.label} className="metric-box">
            <span className="metric-label">{item.label}</span>
            <span className={`metric-value ${item.tone}`}>{item.value}</span>
          </div>
        ))}
      </div>

      <div className="justlend-analytics-grid">
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
              <span className="card-title">风险评分</span>
              <ChartInfoButton title="风险评分说明" items={riskScoreExplainItems} />
            </div>
            <span className={`badge ${riskToneClass}`}>{riskScoreLabel(riskScore)}</span>
          </div>
          <div className="justlend-score-layout">
            <div
              className="justlend-score-ring"
              style={{
                background: `conic-gradient(${riskScoreColor} 0 ${riskScore}%, #1e293b ${riskScore}% 100%)`,
              }}
            >
              <div className="justlend-score-ring-inner">
                <strong>{riskScore}</strong>
                <span>Score</span>
              </div>
            </div>
            <div className="justlend-score-copy">
              <div className="justlend-market-kicker">Composite Risk</div>
              <div className="justlend-score-headline">
                {riskScoreLabel(riskScore)}，核心受健康因子、安全边际和资产集中度共同影响
              </div>
              <div className="justlend-market-copy">
                这不是协议原生指标，而是前端基于现有 JustLend
                数据推导出来的风险摘要，目的是帮你更快判断账户是否需要进一步排查。
              </div>
            </div>
          </div>
        </div>

        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">借款容量</span>
            <span className="badge" style={{ background: '#0f172a', color: '#cbd5e1' }}>
              Capacity
            </span>
          </div>
          <div className="justlend-capacity-layout">
            <div className="justlend-capacity-bar">
              <div
                className="justlend-capacity-segment justlend-capacity-used"
                style={{ width: `${clamp(capacityUsedPct, 0, 100)}%` }}
              />
              <div
                className="justlend-capacity-segment justlend-capacity-available"
                style={{ width: `${clamp(capacityRemainingPct, 0, 100)}%` }}
              />
            </div>
            <div className="justlend-capacity-legend">
              <div className="justlend-capacity-item">
                <span className="justlend-risk-dot" style={{ background: '#f87171' }} />
                <span>已使用额度</span>
                <strong>{formatVaultNumber(totalDebtUsd, { currency: true })}</strong>
              </div>
              <div className="justlend-capacity-item">
                <span className="justlend-risk-dot" style={{ background: '#22c55e' }} />
                <span>剩余可借额度</span>
                <strong>{formatVaultNumber(availableBorrowUsd, { currency: true })}</strong>
              </div>
              <div className="justlend-capacity-item">
                <span className="justlend-risk-dot" style={{ background: '#94a3b8' }} />
                <span>已使用比例</span>
                <strong>{capacityUsedPct.toFixed(2)}%</strong>
              </div>
            </div>
            <div className="justlend-caption">
              {capacityBase > 0
                ? '容量条展示当前已使用借款额度与剩余可借空间的相对关系，越偏向红色，说明账户越接近融资上限。'
                : '当前没有形成有效的借款容量基数，通常意味着账户还未发生借款，或后端没有返回可借空间。'}
            </div>
          </div>
        </div>

        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">资产集中度</span>
            <span className="badge" style={{ background: '#0f172a', color: '#cbd5e1' }}>
              Concentration
            </span>
          </div>
          <div className="justlend-concentration-list">
            {concentrationRows.map((item) => (
              <div key={item.label} className="justlend-concentration-item">
                <div className="justlend-concentration-head">
                  <span>{item.label}</span>
                  <strong
                    className={
                      item.tone === 'red' ? 'red-text' : item.tone === 'green' ? 'green-text' : ''
                    }
                  >
                    {item.percent.toFixed(2)}%
                  </strong>
                </div>
                <div className="justlend-concentration-bar">
                  <div
                    className={`justlend-concentration-fill justlend-concentration-fill-${item.tone}`}
                    style={{ width: `${clamp(item.percent, 0, 100)}%` }}
                  />
                </div>
                <div className="justlend-caption">{item.hint}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="justlend-risk-layout">
        <div className="card justlend-risk-hero" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">风险判断</span>
            <span className={`badge ${riskToneClass}`}>{riskState.label}</span>
          </div>

          <div className="justlend-risk-hero-top">
            <div>
              <div className="justlend-market-kicker">Health Factor</div>
              <AutoFitText
                className="justlend-risk-health"
                text={formatHealthFactor(data.health_factor)}
                maxFontSizePx={64}
                minFontSizePx={28}
                fontWeight={800}
                useScientificWhenOverflow
                scientificIntegerDigitsThreshold={6}
              />
            </div>
            <div className="justlend-risk-health-copy">
              账户当前总抵押为{' '}
              <strong>{formatVaultNumber(totalCollateralUsd, { currency: true })}</strong>，总债务为{' '}
              <strong>{formatVaultNumber(totalDebtUsd, { currency: true })}</strong>
              。如果借款使用率继续向清算阈值靠近， 仓位的抗波动空间会迅速压缩。
            </div>
          </div>

          <div className="justlend-bullet-shell">
            <div className="justlend-bullet-header">
              <span className="justlend-bullet-title">当前 LTV</span>
              <strong>{formatPercentRatio(data.ltv)}</strong>
            </div>
            <div className="justlend-bullet-track">
              <div
                className={`justlend-bullet-marker justlend-bullet-marker-current ${
                  bulletMarkersTooClose ? 'justlend-bullet-marker-stagger-left' : ''
                }`}
                style={{ left: `${Math.min(100, Math.max(0, ltvPercent))}%` }}
              >
                <span>当前</span>
              </div>
              <div
                className={`justlend-bullet-marker justlend-bullet-marker-threshold ${
                  bulletMarkersTooClose ? 'justlend-bullet-marker-stagger-right' : ''
                }`}
                style={{ left: `${Math.min(100, Math.max(0, thresholdPercent))}%` }}
              >
                <span>阈值</span>
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
              <strong>{formatPercentRatio(data.ltv)}</strong>
            </div>
            <div className="justlend-risk-marker">
              <span className="justlend-risk-dot" style={{ background: '#ef4444' }} />
              <span>清算阈值</span>
              <strong>{formatPercentRatio(data.liquidation_threshold)}</strong>
            </div>
            <div className="justlend-risk-marker">
              <span className="justlend-risk-dot" style={{ background: '#22c55e' }} />
              <span>剩余安全边际</span>
              <strong>{riskGap.toFixed(2)}%</strong>
            </div>
          </div>
        </div>

        <div className="justlend-risk-side">
          <div className="justlend-insight-grid">
            {insightItems.map((item) => (
              <div key={item.label} className="metric-box">
                <span className="metric-label">{item.label}</span>
                <span className={`metric-value ${item.toneClass}`}>{item.value}</span>
              </div>
            ))}
          </div>

          <div className="justlend-banner justlend-banner-soft">
            <div className="justlend-banner-title">风险解读</div>
            <div className="justlend-banner-copy">
              当前可借空间为{' '}
              <strong>{formatVaultNumber(availableBorrowUsd, { currency: true })}</strong>
              。抵押侧最集中的资产是 <strong>{topCollateral?.name ?? '暂无'}</strong>
              ，债务侧最集中的资产是 <strong>{topBorrow?.name ?? '暂无'}</strong>
              。这两个集中点会决定账户对局部价格波动的敏感度。
            </div>
          </div>

          {totalDebtUsd <= 0 ? (
            <div className="justlend-banner justlend-banner-soft">
              <div className="justlend-banner-title">当前无活跃借款</div>
              <div className="justlend-banner-copy">
                页面仍会展示抵押结构，但没有债务时，健康因子和 LTV
                的风险解释更偏向“仓位快照”而不是“清算压力”。
              </div>
            </div>
          ) : null}

          {totalCollateralUsd <= 0 && totalDebtUsd > 0 ? (
            <div className="justlend-banner justlend-banner-warn">
              <div className="justlend-banner-title">检测到异常结构</div>
              <div className="justlend-banner-copy">
                该地址返回了债务但没有抵押，前端会继续展示明细，但这通常意味着数据尚未完整同步。
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <div className="justlend-structure-grid">
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">抵押资产构成</span>
            <span className="badge" style={justLendChartTheme.badge.success}>
              Collateral
            </span>
          </div>
          <div style={{ height: 280 }}>
            {collateralData.length ? (
              <div className="justlend-allocation-layout">
                <div className="justlend-allocation-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={collateralData}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={58}
                        outerRadius={92}
                        paddingAngle={0.8}
                        stroke={justLendChartTheme.stroke.asset}
                        strokeWidth={1}
                      >
                        {collateralData.map((entry, index) => (
                          <Cell
                            key={entry.name}
                            fill={collateralColors[index % collateralColors.length]}
                          />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{
                          backgroundColor: justLendChartTheme.tooltip.background,
                          borderColor: justLendChartTheme.tooltip.border,
                          color: justLendChartTheme.tooltip.text,
                        }}
                        formatter={(value: unknown, name: unknown) => [
                          `${Number(value ?? 0).toFixed(2)}%`,
                          `${String(name)} 占比`,
                        ]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="justlend-allocation-list">
                  {collateralData.map((item, index) => (
                    <div key={item.name} className="justlend-allocation-item">
                      <div className="justlend-allocation-main">
                        <span
                          className="justlend-risk-dot"
                          style={{ background: collateralColors[index % collateralColors.length] }}
                        />
                        <span className="token-symbol">{item.name}</span>
                        <span className="justlend-allocation-share">{item.value.toFixed(2)}%</span>
                      </div>
                      <div className="justlend-allocation-meta">
                        <span className="mono">数量 {formatVaultNumber(item.amount)}</span>
                        <span className="mono">
                          {formatVaultNumber(item.valueUsd, { currency: true })}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="justlend-empty-state">暂无抵押资产数据</div>
            )}
          </div>
        </div>

        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">债务资产分布</span>
            <span className="badge" style={justLendChartTheme.badge.danger}>
              Borrow
            </span>
          </div>
          <div style={{ height: 280 }}>
            {borrowData.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={borrowData}
                  layout="vertical"
                  barCategoryGap="58%"
                  margin={{ left: 12, right: 16, top: 6, bottom: 6 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke={justLendChartTheme.grid} />
                  <XAxis
                    type="number"
                    stroke={justLendChartTheme.axis.primary}
                    tickFormatter={(value) => `${value}%`}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    stroke={justLendChartTheme.axis.secondary}
                    width={64}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: justLendChartTheme.tooltip.background,
                      borderColor: justLendChartTheme.tooltip.border,
                      color: justLendChartTheme.tooltip.text,
                    }}
                    itemStyle={{ color: justLendChartTheme.tooltip.accent }}
                    cursor={{ fill: 'transparent' }}
                    formatter={(value: unknown, name: unknown) => [
                      `${Number(value ?? 0).toFixed(2)}%`,
                      String(name ?? '债务占比'),
                    ]}
                  />
                  <Bar
                    dataKey="value"
                    name="债务占比"
                    radius={[0, 6, 6, 0]}
                    maxBarSize={22}
                    activeBar={false}
                  >
                    {borrowData.map((entry, index) => (
                      <Cell key={entry.name} fill={borrowColors[index % borrowColors.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="justlend-empty-state">暂无债务资产数据</div>
            )}
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <span className="card-title">资产双侧对照</span>
          <span className="badge" style={justLendChartTheme.badge.neutral}>
            Bilateral
          </span>
        </div>
        <div style={{ height: 320 }}>
          {bilateralData.length ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={bilateralData}
                layout="vertical"
                stackOffset="sign"
                barCategoryGap="40%"
                margin={{ top: 10, right: 20, left: 8, bottom: 4 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke={justLendChartTheme.grid} />
                <ReferenceLine
                  x={0}
                  stroke={justLendChartTheme.axis.reference}
                  strokeOpacity={0.85}
                />
                <XAxis
                  type="number"
                  stroke={justLendChartTheme.axis.primary}
                  domain={[-bilateralDomainMax, bilateralDomainMax]}
                  tickFormatter={(value) => formatUsdAxis(Number(value))}
                />
                <YAxis
                  type="category"
                  dataKey="asset"
                  stroke={justLendChartTheme.axis.primary}
                  width={72}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: justLendChartTheme.tooltip.background,
                    borderColor: justLendChartTheme.tooltip.border,
                    color: justLendChartTheme.tooltip.text,
                  }}
                  cursor={{ fill: 'transparent' }}
                  formatter={(value: unknown, name: unknown) => [
                    formatUsd(Math.abs(Number(value ?? 0))),
                    String(name),
                  ]}
                />
                <Legend wrapperStyle={{ color: justLendChartTheme.legend.text }} />
                <Bar
                  dataKey="borrow"
                  name="借款价值"
                  fill={justLendChartTheme.series.borrow}
                  stackId="bilateral"
                  barSize={18}
                >
                  {bilateralData.map((entry) => (
                    <Cell key={`borrow-${entry.asset}`} fill={justLendChartTheme.series.borrow} />
                  ))}
                </Bar>
                <Bar
                  dataKey="collateral"
                  name="抵押价值"
                  fill={justLendChartTheme.series.collateral}
                  stackId="bilateral"
                  barSize={18}
                >
                  {bilateralData.map((entry) => (
                    <Cell
                      key={`collateral-${entry.asset}`}
                      fill={justLendChartTheme.series.collateral}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="justlend-empty-state">暂无可展示的资产结构</div>
          )}
        </div>
      </div>

      <div className="card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <span className="card-title">逐资产仓位明细</span>
          <span className="badge" style={justLendChartTheme.badge.neutral}>
            {data.assets.length} 项
          </span>
        </div>
        <div className="table-wrap">
          <table className="pos-table">
            <thead>
              <tr>
                <th>资产</th>
                <th>方向</th>
                <th className="right">数量</th>
                <th className="right">价格</th>
                <th className="right">价值</th>
              </tr>
            </thead>
            <tbody>
              {data.assets.length ? (
                data.assets.map((asset) => (
                  <tr key={`${asset.asset_address}-${asset.side}`}>
                    <td className="token-symbol">{asset.symbol || 'Unknown'}</td>
                    <td>{asset.side}</td>
                    <td className="right mono">
                      {toNum(asset.amount).toLocaleString(undefined, {
                        maximumFractionDigits: 6,
                      })}
                    </td>
                    <td className="right mono">{formatUsd(asset.price_usd)}</td>
                    <td className="right mono">{formatUsd(asset.value_usd)}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} style={{ color: '#64748b' }}>
                    该账户当前没有可展示的逐资产仓位明细
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <JustLendPositionReplayChart address={address} protocol={data.protocol} />
    </div>
  );
}
