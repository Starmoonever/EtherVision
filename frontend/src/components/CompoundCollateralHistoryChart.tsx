import { useState, useEffect, useMemo } from 'react';
import {
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
  version: 'v2' | 'v3' | 'all';
  market: string;
  marketSymbol: string;
}

export function CompoundCollateralHistoryChart({
  version,
  market,
  marketSymbol,
}: CompoundCollateralHistoryChartProps) {
  const [data, setData] = useState<CompoundMarketPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [timeRange, setTimeRange] = useState<'3M' | '6M' | '1Y'>('3M');
  const [selectedSymbol, setSelectedSymbol] = useState<string>('');

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

        const now = new Date();
        const end = now.toISOString().slice(0, 13).replace('T', ' ') + ':00:00';

        const startDate = new Date();
        if (timeRange === '3M') startDate.setMonth(now.getMonth() - 3);
        else if (timeRange === '6M') startDate.setMonth(now.getMonth() - 6);
        else if (timeRange === '1Y') startDate.setFullYear(now.getFullYear() - 1);

        const start = startDate.toISOString().slice(0, 13).replace('T', ' ') + ':00:00';

        const fetchVersion = version === 'all' ? 'v3' : version;

        const points = await fetchCompoundMarketHistory(fetchVersion, market, start, end);

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
  }, [version, market, timeRange]);

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

  // Set default selected symbol if none is selected
  useEffect(() => {
    if (availableSymbols.length > 0 && !availableSymbols.includes(selectedSymbol)) {
      setSelectedSymbol(availableSymbols[0]);
    }
  }, [availableSymbols, selectedSymbol]);

  // Format data for the charts based on selected symbol
  const chartData = useMemo(() => {
    if (!data.length || !selectedSymbol) return [];

    return data
      .map((pt) => {
        const reserve = pt.reserves?.find((r) => r.symbol === selectedSymbol);
        if (!reserve) return null;

        return {
          // Format timestamp as 20XX-XX-XX
          timestamp: pt.timestamp.split('T')[0].split(' ')[0],
          price_usd: parseFloat(reserve.price_usd || '0'),
          price_in_base: parseFloat(reserve.price_in_base || '0'),
          supply_usd: parseFloat(reserve.supply_usd || '0'),
          borrow_usd: parseFloat(reserve.borrow_usd || '0'),
          borrow_apr: parseFloat(reserve.borrow_apr || '0') * 100,
          supply_apr: parseFloat(reserve.supply_apr || '0') * 100,
          utilization: parseFloat(reserve.utilization || '0') * 100,
        };
      })
      .filter(Boolean) as any[];
  }, [data, selectedSymbol]);

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

      {/* Chart 1: Collateral Prices */}
      <div className="card">
        <div
          className="card-header"
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
        >
          <span className="card-title">{selectedSymbol} 价格图</span>
        </div>
        <div style={{ height: 400 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="timestamp" stroke="#64748b" tick={{ fontSize: 12 }} minTickGap={30} />
              <YAxis
                yAxisId="left"
                stroke="#10b981"
                tickFormatter={(val) => `$${val}`}
                width={60}
              />
              <YAxis yAxisId="right" orientation="right" stroke="#f59e0b" width={60} />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                formatter={(value: any, name: any) => {
                  if (name === `${selectedSymbol} 价格 (USD)`)
                    return [`$${Number(value).toLocaleString()}`, name];
                  return [Number(value).toLocaleString(), name];
                }}
              />
              <Legend />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="price_usd"
                name={`${selectedSymbol} 价格 (USD)`}
                stroke="#10b981"
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

      {/* Chart 2: Market Size */}
      <div className="card">
        <div
          className="card-header"
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
        >
          <span className="card-title">{selectedSymbol} 市场规模 (USD)</span>
        </div>
        <div style={{ height: 400 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="timestamp" stroke="#64748b" tick={{ fontSize: 12 }} minTickGap={30} />
              <YAxis
                stroke="#64748b"
                tickFormatter={(val) =>
                  selectedSymbol === 'rsETH' ? `$${val}` : `$${(val / 1e6).toFixed(0)}M`
                }
                width={60}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                formatter={(value: any, name: any) => [`$${Number(value).toLocaleString()}`, name]}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="supply_usd"
                name={`抵押 ${selectedSymbol} 总值`}
                stroke="#3b82f6"
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
