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
import { fetchCompoundMarketHistory } from '../api/compound';

interface CompoundMarketHistoryChartProps {
  version: 'v2' | 'v3' | 'all';
  market: string;
  marketSymbol: string;
}

interface ChartPoint {
  timestamp: string;
  borrow_usd: number;
  available_liquidity_usd: number;
  borrow_apr: number;
  supply_apr: number;
  utilization: number;
}

export function CompoundMarketHistoryChart({
  version,
  market,
  marketSymbol,
}: CompoundMarketHistoryChartProps) {
  const [data, setData] = useState<ChartPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [timeRange, setTimeRange] = useState<'3M' | '6M' | '1Y'>('3M');

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
        const end = now.toISOString().slice(0, 13).replace('T', ' ') + ':00:00'; // YYYY-MM-DD HH:00:00

        const startDate = new Date();
        if (timeRange === '3M') startDate.setMonth(now.getMonth() - 3);
        else if (timeRange === '6M') startDate.setMonth(now.getMonth() - 6);
        else if (timeRange === '1Y') startDate.setFullYear(now.getFullYear() - 1);

        const start = startDate.toISOString().slice(0, 13).replace('T', ' ') + ':00:00'; // YYYY-MM-DD HH:00:00

        // 对接后端要求：Compound 仅支持 v3 数据，如果是 all，强制转换为 v3 发起请求
        const fetchVersion = version === 'all' ? 'v3' : version;

        const points = await fetchCompoundMarketHistory(fetchVersion, market, start, end);

        const finalData: ChartPoint[] = points.map((pt) => {
          const supplyUsd = parseFloat(pt.supply_usd || '0');
          const borrowUsd = parseFloat(pt.borrow_usd || '0');
          return {
            timestamp: pt.timestamp.replace('T', ' '),
            borrow_usd: borrowUsd,
            available_liquidity_usd: Math.max(0, supplyUsd - borrowUsd),
            borrow_apr: parseFloat(pt.borrow_apr || '0') * 100,
            supply_apr: parseFloat(pt.supply_apr || '0') * 100,
            utilization: parseFloat(pt.utilization || '0') * 100,
          };
        });

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
  }, [version, market, timeRange]);

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
            {marketSymbol} 借贷市场历史数据回顾
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

      {/* Chart 1: Market Size */}
      <div className="card">
        <div
          className="card-header"
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
        >
          <span className="card-title">市场规模 （USD）</span>
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
                  if (name === `借出 ${marketSymbol} 总值`) label = `借出 ${marketSymbol} 总值`;
                  else if (name === `剩余可借 ${marketSymbol} 总值`)
                    label = `剩余可借 ${marketSymbol} 总值`;
                  return [`$${Number(value).toLocaleString()}`, label];
                }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="borrow_usd"
                name={`借出 ${marketSymbol} 总值`}
                stroke="#ef4444"
                dot={false}
                strokeWidth={2}
              />
              <Line
                type="monotone"
                dataKey="available_liquidity_usd"
                name={`剩余可借 ${marketSymbol} 总值`}
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
        <div
          className="card-header"
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
        >
          <span className="card-title">抵押借贷利率与资金利用率</span>
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
                dataKey="borrow_apr"
                name="借款年利息率"
                stroke="#ef4444"
                dot={false}
                strokeWidth={2}
              />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="supply_apr"
                name="存款年收益率"
                stroke="#10b981"
                dot={false}
                strokeWidth={2}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="utilization"
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
