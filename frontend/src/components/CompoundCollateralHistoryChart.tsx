import { useState, useEffect, useMemo } from 'react';
import {
  Area,
  AreaChart,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import {
  fetchCompoundMarketHistoryWithMeta,
  fetchCompoundMarketGovernanceV3WithMeta,
  fetchCompoundMarketConfigV2WithMeta,
} from '../api/compound';
import type { CompoundMarketPoint } from '../api/compound';
import { ChartDataStatus, ChartInfoButton, type ExplainItem } from './ChartAssist';
import { mergeRequestMetas, type AggregatedRequestMeta } from '../api/requestMeta';

interface CompoundCollateralHistoryChartProps {
  version: 'v2' | 'v3';
  market: string;
  marketSymbol: string;
}

interface CollateralChartPoint {
  timestamp: string;
  price_in_base: number;
  total_collateral_usd: number;
  effective_collateral_usd: number;
}

interface CompositionPoint {
  timestamp: string;
  total_collateral_usd: number;
  [symbol: string]: string | number;
}

interface V2StructurePoint {
  timestamp: string;
  cash_usd: number;
  borrow_usd: number;
  supply_usd: number;
  reserves_usd: number;
  utilization_pct: number;
  reserve_share_pct: number;
}

function parseUtcDateBoundary(date: string, endOfDay = false): number {
  return Date.parse(`${date}T${endOfDay ? '23' : '00'}:00:00Z`);
}

function formatUtcDateBoundary(date: string, endOfDay = false): string {
  return `${date} ${endOfDay ? '23' : '00'}:00:00`;
}

function formatUsd(value: number): string {
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatPercent(value: number): string {
  return `${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}%`;
}

const explainItems: ExplainItem[] = [
  {
    term: '资金结构 / 抵押结构',
    formula: '按 reserve 的 supply_usd 汇总',
    meaning: '展示一个 market 的抵押组成是否分散、是否过度依赖单一资产。',
    riskHint: '如果抵押结构过于集中，单个资产波动或脱锚会更容易伤到整个 market。',
  },
  {
    term: '有效抵押价值',
    formula: 'collateral usd × collateral factor',
    meaning: '不是所有抵押都能 1:1 支撑借款，乘上抵押参数后才更接近真实安全垫。',
    riskHint: '有效抵押价值下降，比名义抵押下滑更值得警惕。',
  },
  {
    term: '储备占比（v2）',
    formula: 'reserves / supply',
    meaning: '衡量协议从市场里留存了多少储备。',
    riskHint: '储备越高未必越差，但如果伴随利用率恶化，往往意味着市场效率下降。',
  },
];

export function CompoundCollateralHistoryChart({
  version,
  market,
  marketSymbol,
}: CompoundCollateralHistoryChartProps) {
  const [data, setData] = useState<CompoundMarketPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [v2Config, setV2Config] = useState<any | null>(null);
  const [timeRange, setTimeRange] = useState<'3M' | '6M' | '1Y' | null>('3M');
  const [selectedSymbol, setSelectedSymbol] = useState<string>('');
  const [customStart, setCustomStart] = useState(() => {
    const d = new Date();
    d.setMonth(d.getMonth() - 3);
    return d.toISOString().slice(0, 10);
  });
  const [customEnd, setCustomEnd] = useState(() => new Date().toISOString().slice(0, 10));
  const [meta, setMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });

  useEffect(() => {
    if (timeRange === null) return;
    const now = new Date();
    const startDate = new Date();
    if (timeRange === '3M') startDate.setMonth(now.getMonth() - 3);
    else if (timeRange === '6M') startDate.setMonth(now.getMonth() - 6);
    else startDate.setFullYear(now.getFullYear() - 1);
    setCustomStart(startDate.toISOString().slice(0, 10));
    setCustomEnd(now.toISOString().slice(0, 10));
  }, [timeRange]);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError('');
      try {
        const startTs = parseUtcDateBoundary(customStart);
        const endTs = parseUtcDateBoundary(customEnd, true);
        if (Number.isNaN(startTs) || Number.isNaN(endTs)) {
          setError('时间格式无效');
          setLoading(false);
          return;
        }
        if (startTs > endTs) {
          setError('自选时间区间无效：开始日期不能晚于结束日期');
          setLoading(false);
          return;
        }

        const start = formatUtcDateBoundary(customStart);
        const end = formatUtcDateBoundary(customEnd, true);

        const result = await fetchCompoundMarketHistoryWithMeta(version, market, start, end, {
          interval: version === 'v2' ? 1 : 24,
        });
        setMeta(mergeRequestMetas([result.meta]));

        // Sort data by time
        const sortedPoints = result.data.sort(
          (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
        );
        setData(sortedPoints);
      } catch (err) {
        console.error(err);
        setError('无法加载抵押资产历史数据');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [version, market, timeRange, customStart, customEnd]);

  useEffect(() => {
    if (version !== 'v2') {
      setV2Config(null);
      return;
    }

    let cancelled = false;

    const fetchV2Config = async () => {
      try {
        const today = new Date().toISOString().slice(0, 10) + ' 00:00:00';
        const response = await fetchCompoundMarketConfigV2WithMeta(marketSymbol, today);
        if (!cancelled) {
          setV2Config(response.data?.market_config ?? response.data ?? null);
        }
      } catch (err) {
        if (!cancelled) {
          setV2Config(null);
        }
        console.error('Error fetching Compound v2 market config:', err);
      }
    };

    fetchV2Config();
    return () => {
      cancelled = true;
    };
  }, [marketSymbol, version]);

  // Extract all available collateral symbols
  const availableSymbols = useMemo(() => {
    if (!data.length) return [];
    const symbolsSet = new Set<string>();
    data.forEach((pt) => {
      if (pt.reserves && Array.isArray(pt.reserves)) {
        pt.reserves.forEach((r) => {
          // 抵押代币不能为借贷市场借出代币，且该抵押代币的 supply_usd 必须 >= 1
          if (r.symbol !== pt.symbol && parseFloat(r.supply_usd || '0') >= 1) {
            symbolsSet.add(r.symbol);
          }
        });
      }
    });
    return Array.from(symbolsSet);
  }, [data]);

  const compositionData = useMemo<CompositionPoint[]>(() => {
    if (!data.length || !availableSymbols.length) return [];

    return data.map((pt) => {
      const bySymbol: Record<string, number> = {};
      let total = 0;

      for (const reserve of pt.reserves || []) {
        if (!reserve.symbol || reserve.symbol === pt.symbol) continue;
        const collateralUsd = parseFloat(reserve.supply_usd || '0');
        if (collateralUsd <= 0) continue;
        bySymbol[reserve.symbol] = (bySymbol[reserve.symbol] || 0) + collateralUsd;
        total += collateralUsd;
      }

      const row: CompositionPoint = {
        timestamp: pt.timestamp.split('T')[0].split(' ')[0],
        total_collateral_usd: total,
      };
      for (const sym of availableSymbols) {
        const val = bySymbol[sym] || 0;
        const percent = total > 0 ? (val / total) * 100 : 0;
        if (percent >= 0.005) {
          row[sym] = percent;
        }
      }
      return row;
    });
  }, [data, availableSymbols]);

  const compositionSymbols = useMemo(() => {
    if (!compositionData.length) return [];
    const validSymbols = new Set<string>();
    compositionData.forEach((row) => {
      availableSymbols.forEach((sym) => {
        if (row[sym] !== undefined) {
          validSymbols.add(sym);
        }
      });
    });
    return Array.from(validSymbols);
  }, [compositionData, availableSymbols]);

  const [collateralFactor, setCollateralFactor] = useState<number>(1);

  const v2StructureData = useMemo<V2StructurePoint[]>(() => {
    if (version !== 'v2' || !data.length) return [];

    return data.map((pt) => {
      const cashUsd = parseFloat(pt.collateral_usd || '0');
      const borrowUsd = parseFloat(pt.borrow_usd || '0');
      const supplyUsd = parseFloat(pt.supply_usd || '0');
      const reservesUsd = Math.max(0, cashUsd + borrowUsd - supplyUsd);
      const reserveSharePct = supplyUsd > 0 ? (reservesUsd / supplyUsd) * 100 : 0;

      return {
        timestamp: pt.timestamp.split('T')[0].split(' ')[0],
        cash_usd: cashUsd,
        borrow_usd: borrowUsd,
        supply_usd: supplyUsd,
        reserves_usd: reservesUsd,
        utilization_pct: parseFloat(pt.utilization || '0') * 100,
        reserve_share_pct: reserveSharePct,
      };
    });
  }, [data, version]);

  const latestV2Point = useMemo(() => {
    if (!v2StructureData.length) return null;
    return v2StructureData[v2StructureData.length - 1];
  }, [v2StructureData]);

  // Set default selected symbol if none is selected
  useEffect(() => {
    if (version !== 'v3') {
      setSelectedSymbol('');
      return;
    }

    if (availableSymbols.length > 0 && !availableSymbols.includes(selectedSymbol)) {
      setSelectedSymbol(availableSymbols[0]);
    }
  }, [availableSymbols, selectedSymbol, version]);

  // Fetch collateral factor
  useEffect(() => {
    if (version !== 'v3') {
      setCollateralFactor(1);
      return;
    }
    if (!selectedSymbol) return;

    const fetchFactor = async () => {
      try {
        const today = new Date().toISOString().slice(0, 10) + ' 00:00:00';
        const result = await fetchCompoundMarketGovernanceV3WithMeta(market, today);
        if (result.data && result.data.assets && Array.isArray(result.data.assets)) {
          const assetInfo = result.data.assets.find((a: any) => a.symbol === selectedSymbol);
          if (assetInfo && assetInfo.borrow_collateral_factor) {
            setCollateralFactor(parseFloat(assetInfo.borrow_collateral_factor));
            return;
          }
        }
      } catch (err) {
        console.error('Error fetching collateral factor:', err);
      }
      setCollateralFactor(1); // Default to 1 on error or missing data
    };
    fetchFactor();
  }, [version, market, selectedSymbol]);

  // Format data for the charts based on selected symbol
  const chartData = useMemo<CollateralChartPoint[]>(() => {
    if (!data.length || !selectedSymbol) return [];

    return data
      .map((pt): CollateralChartPoint | null => {
        const reserve = pt.reserves?.find((r) => r.symbol === selectedSymbol);
        if (!reserve) return null;

        const supplyUsd = parseFloat(reserve.supply_usd || '0');

        return {
          // Format timestamp as 20XX-XX-XX
          timestamp: pt.timestamp.split('T')[0].split(' ')[0],
          price_in_base: parseFloat(reserve.price_in_base || '0'),
          total_collateral_usd: supplyUsd,
          effective_collateral_usd: supplyUsd * collateralFactor,
        };
      })
      .filter((item): item is CollateralChartPoint => item !== null);
  }, [data, selectedSymbol, collateralFactor]);

  const collateralAxis = useMemo(() => {
    const maxValue = chartData.reduce(
      (max, item) => Math.max(max, item.effective_collateral_usd),
      0,
    );

    if (maxValue >= 1e9) return { divisor: 1e9, suffix: 'B' };
    if (maxValue >= 1e6) return { divisor: 1e6, suffix: 'M' };
    if (maxValue >= 1e3) return { divisor: 1e3, suffix: 'K' };
    return { divisor: 1, suffix: '' };
  }, [chartData]);

  const formatCollateralTick = (value: number) => {
    if (collateralAxis.divisor === 1) {
      return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
    }
    return `$${(value / collateralAxis.divisor).toFixed(2)}${collateralAxis.suffix}`;
  };

  const v2Axis = useMemo(() => {
    const maxValue = v2StructureData.reduce(
      (max, item) =>
        Math.max(max, item.cash_usd, item.borrow_usd, item.supply_usd, item.reserves_usd),
      0,
    );

    if (maxValue >= 1e9) return { divisor: 1e9, suffix: 'B' };
    if (maxValue >= 1e6) return { divisor: 1e6, suffix: 'M' };
    if (maxValue >= 1e3) return { divisor: 1e3, suffix: 'K' };
    return { divisor: 1, suffix: '' };
  }, [v2StructureData]);

  const formatV2UsdTick = (value: number) => {
    if (v2Axis.divisor === 1) {
      return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
    }
    return `$${(value / v2Axis.divisor).toFixed(2)}${v2Axis.suffix}`;
  };

  if (loading)
    return (
      <div
        className="card"
        style={{
          height: 400,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginTop: '1.5rem',
        }}
      >
        <div className="spinner"></div>
      </div>
    );

  if (error)
    return (
      <div
        className="card"
        style={{
          height: 100,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#f87171',
          marginTop: '1.5rem',
        }}
      >
        {error}
      </div>
    );

  if (version === 'v2') {
    if (!data.length || !v2StructureData.length)
      return (
        <div
          className="card"
          style={{
            height: 400,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#94a3b8',
            marginTop: '1.5rem',
          }}
        >
          暂无 Compound v2 市场结构数据
        </div>
      );

    const summaryCards = [
      {
        label: '可用流动性',
        value: formatUsd(latestV2Point?.cash_usd ?? 0),
        tone: '#22c55e',
      },
      {
        label: '未偿借款',
        value: formatUsd(latestV2Point?.borrow_usd ?? 0),
        tone: '#f59e0b',
      },
      {
        label: '利用率',
        value: formatPercent(latestV2Point?.utilization_pct ?? 0),
        tone: '#60a5fa',
      },
      {
        label: '协议储备',
        value: formatUsd(latestV2Point?.reserves_usd ?? 0),
        tone: '#c084fc',
      },
    ];

    if (v2Config?.collateral_factor) {
      summaryCards.push({
        label: '抵押系数',
        value: formatPercent(parseFloat(v2Config.collateral_factor) * 100),
        tone: '#f97316',
      });
    }
    if (v2Config?.reserve_factor) {
      summaryCards.push({
        label: '储备因子',
        value: formatPercent(parseFloat(v2Config.reserve_factor) * 100),
        tone: '#14b8a6',
      });
    }

    return (
      <div style={{ marginTop: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '0.5rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '1.2rem', fontWeight: 'bold', color: '#fff' }}>
              {marketSymbol} v2 市场结构回顾
            </span>
            <ChartInfoButton title="Compound 抵押与结构图说明" items={explainItems} />
            <span
              style={{
                fontSize: '0.75rem',
                color: '#93c5fd',
                background: 'rgba(37, 99, 235, 0.14)',
                border: '1px solid rgba(96, 165, 250, 0.28)',
                borderRadius: '999px',
                padding: '0.2rem 0.65rem',
              }}
            >
              单资产 cToken 市场
            </span>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <ChartDataStatus meta={meta} />
            {(['3M', '6M', '1Y'] as const).map((r) => (
              <button
                key={r}
                onClick={() => setTimeRange(r)}
                style={{
                  background: timeRange === r ? '#3b82f6' : 'transparent',
                  color: timeRange === r ? '#fff' : '#94a3b8',
                  border: '1px solid #334155',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '0.75rem',
                }}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        <div
          style={{
            color: '#94a3b8',
            fontSize: '0.9rem',
            lineHeight: 1.6,
            background: 'rgba(15, 23, 42, 0.68)',
            border: '1px solid #1e293b',
            borderRadius: '10px',
            padding: '0.85rem 1rem',
          }}
        >
          Compound v2 的每个市场只对应一个底层资产，没有 v3 那种多抵押篮子。 这里改为展示该 cToken
          市场的资金结构、流动性利用率和协议储备演化。
        </div>

        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: '0.5rem',
            marginTop: '-0.5rem',
          }}
        >
          <input
            type="date"
            value={customStart}
            onChange={(e) => {
              setTimeRange(null);
              setCustomStart(e.target.value);
            }}
            style={{
              background: '#0f172a',
              border: '1px solid #334155',
              color: '#cbd5e1',
              borderRadius: '4px',
              padding: '2px 6px',
              fontSize: '0.75rem',
            }}
          />
          <span style={{ color: '#64748b', alignSelf: 'center' }}>-</span>
          <input
            type="date"
            value={customEnd}
            onChange={(e) => {
              setTimeRange(null);
              setCustomEnd(e.target.value);
            }}
            style={{
              background: '#0f172a',
              border: '1px solid #334155',
              color: '#cbd5e1',
              borderRadius: '4px',
              padding: '2px 6px',
              fontSize: '0.75rem',
            }}
          />
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
            gap: '0.75rem',
          }}
        >
          {summaryCards.map((item) => (
            <div
              key={item.label}
              className="card"
              style={{
                padding: '1rem',
                background:
                  'linear-gradient(180deg, rgba(15, 23, 42, 0.92), rgba(15, 23, 42, 0.72))',
              }}
            >
              <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginBottom: '0.45rem' }}>
                {item.label}
              </div>
              <div style={{ fontSize: '1.15rem', fontWeight: 700, color: item.tone }}>
                {item.value}
              </div>
            </div>
          ))}
        </div>

        <div className="card">
          <div
            className="card-header"
            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
          >
            <span className="card-title">{marketSymbol} 资金结构</span>
          </div>
          <div style={{ height: 400 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={v2StructureData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis
                  dataKey="timestamp"
                  stroke="#64748b"
                  tick={{ fontSize: 12 }}
                  minTickGap={30}
                />
                <YAxis yAxisId="left" stroke="#64748b" tickFormatter={formatV2UsdTick} width={70} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                  formatter={(value: unknown, name: unknown) => [
                    formatUsd(Number(value)),
                    String(name),
                  ]}
                />
                <Legend />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="cash_usd"
                  name="可用流动性"
                  stroke="#22c55e"
                  dot={false}
                  strokeWidth={2}
                />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="borrow_usd"
                  name="未偿借款"
                  stroke="#f59e0b"
                  dot={false}
                  strokeWidth={2}
                />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="supply_usd"
                  name="供应规模"
                  stroke="#60a5fa"
                  dot={false}
                  strokeWidth={2}
                />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="reserves_usd"
                  name="协议储备"
                  stroke="#c084fc"
                  dot={false}
                  strokeWidth={2}
                  strokeDasharray="6 4"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
            gap: '1.5rem',
          }}
        >
          <div className="card">
            <div
              className="card-header"
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
            >
              <span className="card-title">{marketSymbol} 市场效率</span>
            </div>
            <div style={{ height: 360 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={v2StructureData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis
                    dataKey="timestamp"
                    stroke="#64748b"
                    tick={{ fontSize: 12 }}
                    minTickGap={30}
                  />
                  <YAxis
                    stroke="#64748b"
                    tickFormatter={(value) => `${Number(value).toFixed(0)}%`}
                    width={60}
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                    formatter={(value: unknown, name: unknown) => [
                      formatPercent(Number(value)),
                      String(name),
                    ]}
                  />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="utilization_pct"
                    name="利用率"
                    stroke="#38bdf8"
                    dot={false}
                    strokeWidth={2}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card">
            <div
              className="card-header"
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
            >
              <span className="card-title">{marketSymbol} 储备占比</span>
            </div>
            <div style={{ height: 360 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={v2StructureData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis
                    dataKey="timestamp"
                    stroke="#64748b"
                    tick={{ fontSize: 12 }}
                    minTickGap={30}
                  />
                  <YAxis
                    stroke="#64748b"
                    tickFormatter={(value) => `${Number(value).toFixed(0)}%`}
                    width={60}
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                    formatter={(value: unknown, name: unknown) => [
                      formatPercent(Number(value)),
                      String(name),
                    ]}
                  />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="reserve_share_pct"
                    name="储备占供应规模比例"
                    stroke="#f97316"
                    dot={false}
                    strokeWidth={2}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!data.length || !chartData.length)
    return (
      <div
        className="card"
        style={{
          height: 400,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#94a3b8',
          marginTop: '1.5rem',
        }}
      >
        暂无抵押资产数据
      </div>
    );

  return (
    <div style={{ marginTop: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header and Controls */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '0.5rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '1.2rem', fontWeight: 'bold', color: '#fff' }}>
            抵押资产市场历史数据回顾
          </span>
          <ChartInfoButton title="Compound 抵押与结构图说明" items={explainItems} />
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <ChartDataStatus meta={meta} />
          {(['3M', '6M', '1Y'] as const).map((r) => (
            <button
              key={r}
              onClick={() => setTimeRange(r)}
              style={{
                background: timeRange === r ? '#3b82f6' : 'transparent',
                color: timeRange === r ? '#fff' : '#94a3b8',
                border: '1px solid #334155',
                padding: '2px 8px',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '0.75rem',
              }}
            >
              {r}
            </button>
          ))}
        </div>
      </div>
      <div
        style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '-0.5rem' }}
      >
        <input
          type="date"
          value={customStart}
          onChange={(e) => {
            setTimeRange(null);
            setCustomStart(e.target.value);
          }}
          style={{
            background: '#0f172a',
            border: '1px solid #334155',
            color: '#cbd5e1',
            borderRadius: '4px',
            padding: '2px 6px',
            fontSize: '0.75rem',
          }}
        />
        <span style={{ color: '#64748b', alignSelf: 'center' }}>-</span>
        <input
          type="date"
          value={customEnd}
          onChange={(e) => {
            setTimeRange(null);
            setCustomEnd(e.target.value);
          }}
          style={{
            background: '#0f172a',
            border: '1px solid #334155',
            color: '#cbd5e1',
            borderRadius: '4px',
            padding: '2px 6px',
            fontSize: '0.75rem',
          }}
        />
      </div>

      {/* Composition Chart: collateral share over time */}
      <div className="card">
        <div
          className="card-header"
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
        >
          <span className="card-title">各抵押资产占 {marketSymbol} 市场总抵押值比例</span>
        </div>
        <div style={{ height: 420 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={compositionData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="timestamp" stroke="#64748b" tick={{ fontSize: 12 }} minTickGap={30} />
              <YAxis
                stroke="#64748b"
                domain={[0, 100]}
                tickFormatter={(val) => `${val.toFixed(0)}%`}
                width={55}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                itemSorter={(item) => -(item.value as number)}
                formatter={(value: unknown, name: unknown) => {
                  const num = Number(value);
                  const formatted = num.toFixed(2);
                  return [`${formatted}%`, `${String(name)} 占比`];
                }}
                labelFormatter={(
                  label: unknown,
                  payload?: ReadonlyArray<{ payload?: { total_collateral_usd?: unknown } }>,
                ) => {
                  const total = payload?.[0]?.payload?.total_collateral_usd;
                  if (typeof total === 'number') {
                    return `${String(label)} | 总抵押: $${total.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
                  }
                  return String(label);
                }}
              />
              <Legend />
              {compositionSymbols.map((sym, idx) => {
                const palette = [
                  '#3b82f6',
                  '#10b981',
                  '#f59e0b',
                  '#ef4444',
                  '#8b5cf6',
                  '#14b8a6',
                  '#f97316',
                  '#06b6d4',
                  '#84cc16',
                  '#ec4899',
                ];
                const color = palette[idx % palette.length];
                return (
                  <Area
                    key={sym}
                    type="monotone"
                    dataKey={sym}
                    name={sym}
                    stackId="collateral-share"
                    stroke={color}
                    fill={color}
                    fillOpacity={0.35}
                    dot={false}
                  />
                );
              })}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Symbol Tabs */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.5rem' }}>
        {availableSymbols.map((sym) => (
          <button
            key={sym}
            onClick={() => setSelectedSymbol(sym)}
            style={{
              background: selectedSymbol === sym ? '#7c3aed' : '#1e293b',
              color: selectedSymbol === sym ? '#fff' : '#cbd5e1',
              border: 'none',
              padding: '6px 16px',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '0.85rem',
              fontWeight: 600,
              transition: 'all 0.2s',
            }}
          >
            {sym}
          </button>
        ))}
      </div>

      {/* Combined Chart: price_in_base + total_collateral_usd */}
      <div className="card">
        <div
          className="card-header"
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
        >
          <span className="card-title">
            {selectedSymbol} 对 {marketSymbol} 汇率与抵押规模
          </span>
        </div>
        <div style={{ height: 400 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="timestamp" stroke="#64748b" tick={{ fontSize: 12 }} minTickGap={30} />
              <YAxis
                yAxisId="left"
                stroke="#3b82f6"
                tickFormatter={formatCollateralTick}
                width={60}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                stroke="#f59e0b"
                tickFormatter={(val) => `${Number(val).toFixed(2)}`}
                width={60}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                formatter={(value: unknown, name: unknown) => {
                  const numericValue = typeof value === 'number' ? value : Number(value);
                  const label = String(name);
                  if (label === `${selectedSymbol} 有效抵押总值 (USD)`)
                    return [
                      `$${numericValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                      label,
                    ];
                  return [
                    numericValue.toLocaleString(undefined, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    }),
                    label,
                  ];
                }}
              />
              <Legend />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="effective_collateral_usd"
                name={`${selectedSymbol} 有效抵押总值 (USD)`}
                stroke="#3b82f6"
                dot={false}
                strokeWidth={2}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="price_in_base"
                name={`1 ${selectedSymbol} 换取 ${marketSymbol} 数量`}
                stroke="#f59e0b"
                dot={false}
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
