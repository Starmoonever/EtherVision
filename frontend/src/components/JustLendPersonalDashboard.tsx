import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
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

const collateralColors = ['#22c55e', '#38bdf8', '#f59e0b', '#8b5cf6', '#14b8a6', '#eab308'];
const borrowColors = ['#f87171', '#fb7185', '#f97316', '#fbbf24', '#ef4444', '#f43f5e'];

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

function toNum(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatUsd(value: string | number): string {
  return `$${toNum(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatUsdCompact(value: number): string {
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatPercentRatio(value: string | number): string {
  const num = toNum(value);
  const percent = num <= 1 ? num * 100 : num;
  return `${percent.toFixed(2)}%`;
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

  const ltvPercent = data ? (toNum(data.ltv) <= 1 ? toNum(data.ltv) * 100 : toNum(data.ltv)) : 0;
  const thresholdPercent = data
    ? toNum(data.liquidation_threshold) <= 1
      ? toNum(data.liquidation_threshold) * 100
      : toNum(data.liquidation_threshold)
    : 0;
  const riskGap = Math.max(0, thresholdPercent - ltvPercent);

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

  const summaryItems = [
    { label: '总抵押价值', value: formatUsd(data.total_collateral_usd), tone: 'green' as const },
    { label: '总债务价值', value: formatUsd(data.total_debt_usd), tone: 'red' as const },
    { label: '剩余可借额度', value: formatUsd(data.available_borrow_usd), tone: 'blue' as const },
    { label: '健康因子', value: formatHealthFactor(data.health_factor), tone: 'blue' as const },
    { label: 'LTV', value: formatPercentRatio(data.ltv), tone: 'blue' as const },
    {
      label: '清算阈值',
      value: formatPercentRatio(data.liquidation_threshold),
      tone: 'blue' as const,
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div className="card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <span className="card-title">JustLend 个人账户分析</span>
            <ChartInfoButton title="JustLend 指标说明" items={explainItems} />
            <span className="badge green-badge">{String(data.chain).toUpperCase()}</span>
            <span className="badge" style={{ background: '#0f172a', color: '#cbd5e1' }}>
              {data.protocol}
            </span>
          </div>
          <ChartDataStatus meta={meta} />
        </div>

        <div
          style={{
            display: 'flex',
            gap: '0.5rem',
            alignItems: 'center',
            flexWrap: 'wrap',
            justifyContent: 'flex-start',
          }}
        >
          {[
            { label: '地址', value: data.address, mono: true },
            { label: '快照时间', value: formatDateTime(data.snapshot_at) },
            { label: '底层数据时间', value: formatDateTime(data.block_timestamp) },
            { label: '数据来源', value: data.data_source },
          ].map((item) => (
            <div
              key={item.label}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                background: '#0f172a',
                border: '1px solid #1e293b',
                borderRadius: '999px',
                padding: '0.22rem 0.6rem',
                fontSize: '0.72rem',
                lineHeight: 1.2,
              }}
            >
              <span style={{ color: '#64748b' }}>{item.label}</span>
              <span
                style={{
                  color: '#cbd5e1',
                  fontWeight: 600,
                  fontFamily: item.mono ? "'Courier New', monospace" : undefined,
                }}
              >
                {item.value}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="summary-grid">
        {summaryItems.map((item) => (
          <div key={item.label} className="metric-box">
            <span className="metric-label">{item.label}</span>
            <span className={`metric-value ${item.tone}`}>{item.value}</span>
          </div>
        ))}
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: '1rem',
        }}
      >
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">抵押资产构成</span>
            <span className="badge" style={{ background: '#052e16', color: '#86efac' }}>
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
                        paddingAngle={2}
                      >
                        {collateralData.map((entry, index) => (
                          <Cell
                            key={entry.name}
                            fill={collateralColors[index % collateralColors.length]}
                          />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
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
                        <span className="mono">
                          数量:{' '}
                          {item.amount.toLocaleString(undefined, { maximumFractionDigits: 6 })}
                        </span>
                        <span className="mono">{formatUsd(item.valueUsd)}</span>
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
            <span className="badge" style={{ background: '#3f0d0d', color: '#fca5a5' }}>
              Borrow
            </span>
          </div>
          <div style={{ height: 280 }}>
            {borrowData.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={borrowData} layout="vertical" margin={{ left: 12, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis type="number" stroke="#64748b" tickFormatter={(value) => `${value}%`} />
                  <YAxis type="category" dataKey="name" stroke="#94a3b8" width={64} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                    formatter={(value: unknown, name: unknown) => [
                      `${Number(value ?? 0).toFixed(2)}%`,
                      String(name ?? '债务占比'),
                    ]}
                  />
                  <Bar dataKey="value" name="债务占比" radius={[0, 6, 6, 0]}>
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

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.25fr) minmax(300px, 0.85fr)',
          gap: '1rem',
        }}
      >
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">抵押 / 借款净结构</span>
            <span className="badge" style={{ background: '#0f172a', color: '#cbd5e1' }}>
              Exposure
            </span>
          </div>
          <div style={{ height: 320 }}>
            {exposureData.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={exposureData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="asset" stroke="#94a3b8" />
                  <YAxis
                    stroke="#64748b"
                    tickFormatter={(value) => `$${(Number(value) / 1000).toFixed(0)}k`}
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                    formatter={(value: unknown, name: unknown) => [
                      formatUsdCompact(Number(value ?? 0)),
                      String(name),
                    ]}
                  />
                  <Legend />
                  <Bar dataKey="collateral" name="抵押价值" fill="#22c55e" radius={[6, 6, 0, 0]} />
                  <Bar dataKey="borrow" name="借款价值" fill="#f87171" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="justlend-empty-state">暂无可展示的资产结构</div>
            )}
          </div>
        </div>

        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">风险缓冲</span>
          </div>
          <div className="justlend-risk-stack">
            <div className="justlend-progress-header">
              <span>当前 LTV</span>
              <span>{formatPercentRatio(data.ltv)}</span>
            </div>
            <div className="justlend-progress-track">
              <div
                className="justlend-progress-fill"
                style={{ width: `${Math.min(100, ltvPercent)}%` }}
              />
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
            <div className="justlend-banner justlend-banner-soft">
              <div className="justlend-banner-copy">
                当前账户健康因子为 <strong>{formatHealthFactor(data.health_factor)}</strong>。如果
                LTV 继续向清算阈值靠近，仓位的价格波动容忍度会快速下降。
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <span className="card-title">逐资产仓位明细</span>
          <span className="badge" style={{ background: '#0f172a', color: '#cbd5e1' }}>
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
    </div>
  );
}
