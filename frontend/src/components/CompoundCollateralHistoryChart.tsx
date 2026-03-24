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
import { fetchCompoundMarketHistory } from '../api/compound';
import type { CompoundMarketPoint } from '../api/compound';

interface CompoundCollateralHistoryChartProps {
  version: 'v2' | 'v3';
  market: string;
  marketSymbol: string;
}

interface CollateralChartPoint {
  timestamp: string;
  price_in_base: number;
  total_collateral_usd: number;
}

interface CompositionPoint {
  timestamp: string;
  total_collateral_usd: number;
  [symbol: string]: string | number;
}

export function CompoundCollateralHistoryChart({
  version,
  market,
  marketSymbol,
}: CompoundCollateralHistoryChartProps) {
  const [data, setData] = useState<CompoundMarketPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [timeRange, setTimeRange] = useState<'3M' | '6M' | '1Y' | null>('3M');
  const [selectedSymbol, setSelectedSymbol] = useState<string>('');
  const [customStart, setCustomStart] = useState(() => {
    const d = new Date();
    d.setMonth(d.getMonth() - 3);
    return d.toISOString().slice(0, 10);
  });
  const [customEnd, setCustomEnd] = useState(() => new Date().toISOString().slice(0, 10));

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
        if (version === 'v2') {
          setError('暂无Compound v2 借贷市场数据');
          setLoading(false);
          return;
        }

        const startDate = new Date(`${customStart}T00:00:00`);
        const endDate = new Date(`${customEnd}T23:00:00`);
        if (startDate.getTime() > endDate.getTime()) {
          setError('自选时间区间无效：开始日期不能晚于结束日期');
          setLoading(false);
          return;
        }

        const start = startDate.toISOString().slice(0, 13).replace('T', ' ') + ':00:00';
        const end = endDate.toISOString().slice(0, 13).replace('T', ' ') + ':00:00';

        const points = await fetchCompoundMarketHistory(version, market, start, end);

        // Sort data by time
        const sortedPoints = points.sort(
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
        row[sym] = total > 0 ? (val / total) * 100 : 0;
      }
      return row;
    });
  }, [data, availableSymbols]);

  // Set default selected symbol if none is selected
  useEffect(() => {
    if (availableSymbols.length > 0 && !availableSymbols.includes(selectedSymbol)) {
      setSelectedSymbol(availableSymbols[0]);
    }
  }, [availableSymbols, selectedSymbol]);

  // Format data for the charts based on selected symbol
  const chartData = useMemo<CollateralChartPoint[]>(() => {
    if (!data.length || !selectedSymbol) return [];

    return data
      .map((pt): CollateralChartPoint | null => {
        const reserve = pt.reserves?.find((r) => r.symbol === selectedSymbol);
        if (!reserve) return null;

        return {
          // Format timestamp as 20XX-XX-XX
          timestamp: pt.timestamp.split('T')[0].split(' ')[0],
          price_in_base: parseFloat(reserve.price_in_base || '0'),
          total_collateral_usd: parseFloat(reserve.supply_usd || '0'),
        };
      })
      .filter((item): item is CollateralChartPoint => item !== null);
  }, [data, selectedSymbol]);

  const collateralAxis = useMemo(() => {
    const maxValue = chartData.reduce((max, item) => Math.max(max, item.total_collateral_usd), 0);

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
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
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
          <span className="card-title">{selectedSymbol} 价格与抵押规模</span>
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
                tickFormatter={(val) => `${val}`}
                width={60}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                formatter={(value: unknown, name: unknown) => {
                  const numericValue = typeof value === 'number' ? value : Number(value);
                  const label = String(name);
                  if (label === `${selectedSymbol} 抵押总值 (USD)`)
                    return [`$${numericValue.toLocaleString()}`, label];
                  return [numericValue.toLocaleString(), label];
                }}
              />
              <Legend />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="total_collateral_usd"
                name={`${selectedSymbol} 抵押总值 (USD)`}
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

      {/* Composition Chart: collateral share over time */}
      <div className="card">
        <div
          className="card-header"
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
        >
          <span className="card-title">各抵押资产占总抵押价值占比</span>
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
                formatter={(value: unknown, name: unknown) => [
                  `${Number(value).toFixed(2)}%`,
                  `${String(name)} 占比`,
                ]}
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
              {availableSymbols.map((sym, idx) => {
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
    </div>
  );
}
