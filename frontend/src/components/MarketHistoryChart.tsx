import { useState, useEffect } from 'react';
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

interface MarketHistoryChartProps {
  version: 'v2' | 'v3' | 'all';
}

interface MarketPoint {
  timestamp: string;
  total_debt_usd: number;
  available_liquidity_usd: number;
  variable_borrow_apy: number;
  supply_apy: number;
  utilization_rate: number;
}

export function MarketHistoryChart({ version }: MarketHistoryChartProps) {
  const [data, setData] = useState<MarketPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [timeRange, setTimeRange] = useState<'3M' | '6M' | '1Y'>('3M');

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError('');
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL;
        const now = new Date();
        const end = now.toISOString().split('T')[0];

        const startDate = new Date();
        if (timeRange === '3M') startDate.setMonth(now.getMonth() - 3);
        else if (timeRange === '6M') startDate.setMonth(now.getMonth() - 6);
        else if (timeRange === '1Y') startDate.setFullYear(now.getFullYear() - 1);

        const start = startDate.toISOString().split('T')[0];

        // Helper to fetch and process data for a specific version
        const fetchAndProcess = async (v: string) => {
          const res = await fetch(
            `${baseUrl}/positions/replay?start=${start}&end=${end}&version=${v}&detail=true`,
          );
          if (!res.ok) throw new Error(`Failed to fetch ${v} market history`);
          const json = await res.json();
          if (!json.points || !Array.isArray(json.points)) throw new Error('Invalid data format');

          return json.points
            .map((pt: any) => {
              const ethReserve = pt.reserves.find(
                (r: any) => r.symbol.toUpperCase() === 'ETH' || r.symbol.toUpperCase() === 'WETH',
              );
              if (!ethReserve) return null;
              return {
                timestamp: pt.block_timestamp.split('T')[0],
                total_debt_usd: parseFloat(ethReserve.total_debt_usd || '0'),
                available_liquidity_usd: parseFloat(ethReserve.available_liquidity_usd || '0'),
                total_supply_usd: parseFloat(ethReserve.total_supply_usd || '0'),
                variable_borrow_apy: parseFloat(ethReserve.variable_borrow_apy || '0'),
                supply_apy: parseFloat(ethReserve.supply_apy || '0'),
                utilization_rate: parseFloat(ethReserve.utilization_rate || '0'),
              };
            })
            .filter(Boolean);
        };

        let finalData: MarketPoint[] = [];

        if (version === 'all') {
          const [v2Data, v3Data] = await Promise.all([
            fetchAndProcess('v2'),
            fetchAndProcess('v3'),
          ]);

          // Aggregate data by timestamp
          const dateMap = new Map<string, any>();

          // Process V2
          v2Data.forEach((pt: any) => {
            if (!dateMap.has(pt.timestamp)) {
              dateMap.set(pt.timestamp, { ...pt, count: 1 });
            } else {
              // Should not happen for same version, but safe to ignore or overwrite
              dateMap.set(pt.timestamp, pt);
            }
          });

          // Merge V3
          v3Data.forEach((pt: any) => {
            if (dateMap.has(pt.timestamp)) {
              const existing = dateMap.get(pt.timestamp);

              // Sum amounts
              const totalDebt = existing.total_debt_usd + pt.total_debt_usd;
              const totalSupply = existing.total_supply_usd + pt.total_supply_usd;
              const totalLiquidity = existing.available_liquidity_usd + pt.available_liquidity_usd;

              // Weighted averages for rates
              // Avoid division by zero
              const weightedBorrowAPY =
                totalDebt > 0
                  ? (existing.variable_borrow_apy * existing.total_debt_usd +
                      pt.variable_borrow_apy * pt.total_debt_usd) /
                    totalDebt
                  : 0;

              const weightedSupplyAPY =
                totalSupply > 0
                  ? (existing.supply_apy * existing.total_supply_usd +
                      pt.supply_apy * pt.total_supply_usd) /
                    totalSupply
                  : 0;

              // Utilization rate = Total Debt / Total Supply
              const utilizationRate = totalSupply > 0 ? totalDebt / totalSupply : 0;

              dateMap.set(pt.timestamp, {
                timestamp: pt.timestamp,
                total_debt_usd: totalDebt,
                available_liquidity_usd: totalLiquidity,
                variable_borrow_apy: weightedBorrowAPY,
                supply_apy: weightedSupplyAPY,
                utilization_rate: utilizationRate,
              });
            } else {
              dateMap.set(pt.timestamp, pt);
            }
          });

          finalData = Array.from(dateMap.values()).map((pt) => ({
            ...pt,
            variable_borrow_apy: pt.variable_borrow_apy * 100,
            supply_apy: pt.supply_apy * 100,
            utilization_rate: pt.utilization_rate * 100,
          }));
        } else {
          // Single version
          const data = await fetchAndProcess(version);
          finalData = data.map((pt: any) => ({
            timestamp: pt.timestamp,
            total_debt_usd: pt.total_debt_usd,
            available_liquidity_usd: pt.available_liquidity_usd,
            variable_borrow_apy: pt.variable_borrow_apy * 100,
            supply_apy: pt.supply_apy * 100,
            utilization_rate: pt.utilization_rate * 100,
          }));
        }

        setData(
          finalData.sort(
            (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
          ),
        );
      } catch (err) {
        console.error(err);
        setError('无法加载市场历史数据');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [version, timeRange]);

  if (loading)
    return (
      <div
        className="card"
        style={{ height: 400, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
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
        }}
      >
        {error}
      </div>
    );

  // Ensure charts have data or show a message
  if (!data.length)
    return (
      <div
        className="card"
        style={{
          height: 400,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#94a3b8',
        }}
      >
        暂无数据
      </div>
    );

  return (
    <div style={{ marginTop: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <span style={{ fontSize: '1.2rem', fontWeight: 'bold', color: '#fff' }}>历史数据回顾</span>
      </div>

      {/* Chart 1: Market Size */}
      <div className="card">
        <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span className="card-title">市场规模 （USD）</span>
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
        <div style={{ height: 400 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="timestamp" stroke="#64748b" tick={{ fontSize: 12 }} minTickGap={30} />
              <YAxis
                stroke="#64748b"
                tickFormatter={(val) => `$${(val / 1e6).toFixed(0)}M`}
                width={60}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                formatter={(value: any, name: any) => {
                  let label = name;
                  if (name === '借出 ETH 总值') label = '借出 ETH 总值';
                  else if (name === '剩余可借 ETH 总值') label = '剩余可借 ETH 总值';
                  return [`$${Number(value).toLocaleString()}`, label];
                }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="total_debt_usd"
                name="借出 ETH 总值"
                stroke="#ef4444"
                dot={false}
                strokeWidth={2}
              />
              <Line
                type="monotone"
                dataKey="available_liquidity_usd"
                name="剩余可借 ETH 总值"
                stroke="#10b981"
                dot={false}
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Chart 2: Rates */}
      <div className="card">
        <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span className="card-title">抵押借贷利率</span>
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
        <div style={{ height: 400 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="timestamp" stroke="#64748b" tick={{ fontSize: 12 }} minTickGap={30} />
              <YAxis
                yAxisId="left"
                stroke="#64748b"
                tickFormatter={(val) => `${val}%`}
                width={40}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                stroke="#3b82f6"
                tickFormatter={(val) => `${val}%`}
                width={40}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                formatter={(value: any, name: any) => [`${Number(value).toFixed(2)}%`, name]}
              />
              <Legend />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="variable_borrow_apy"
                name="借款实际年化利息率"
                stroke="#ef4444"
                dot={false}
                strokeWidth={2}
              />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="supply_apy"
                name="存款年化收益率"
                stroke="#10b981"
                dot={false}
                strokeWidth={2}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="utilization_rate"
                name="资金利用率"
                stroke="#3b82f6"
                dot={false}
                strokeWidth={2}
                strokeDasharray="5 5"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
