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
import { fetchCompoundMarketHistory, fetchCompoundMarketGovernanceV3 } from '../api/compound';
import { fetchAssetPrice } from '../api/price';

interface CompoundMarketHistoryChartProps {
  version: 'v2' | 'v3';
  market: string;
  marketSymbol: string;
}

interface ChartPoint {
  timestamp: string;
  borrow_usd: number;
  total_market_usd: number;
  asset_price_usd: number;
  borrow_apr: number;
  supply_apr: number;
  utilization: number;
  total_supply_apr: number;
  total_borrow_apr: number;
}

export function CompoundMarketHistoryChart({
  version,
  market,
  marketSymbol,
}: CompoundMarketHistoryChartProps) {
  const [data, setData] = useState<ChartPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [timeRange, setTimeRange] = useState<'3M' | '6M' | '1Y' | null>('3M');
  const [customStart, setCustomStart] = useState(() => {
    const d = new Date();
    d.setMonth(d.getMonth() - 3);
    return d.toISOString().slice(0, 10);
  });
  const [customEnd, setCustomEnd] = useState(() => new Date().toISOString().slice(0, 10));

  const [showRatesHelp, setShowRatesHelp] = useState(false);

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

        let compPrice = 0;
        let trackingIndexScale = 1e15;
        let baseTrackingSupplySpeed = 0;
        let baseTrackingBorrowSpeed = 0;

        if (version === 'v3') {
          try {
            compPrice = await fetchAssetPrice('comp');
            const govData = await fetchCompoundMarketGovernanceV3(market, customEnd + ' 00:00:00');
            if (govData) {
              trackingIndexScale = parseFloat(govData.tracking_index_scale || '1e15');
              baseTrackingSupplySpeed = parseFloat(govData.base_tracking_supply_speed || '0');
              baseTrackingBorrowSpeed = parseFloat(govData.base_tracking_borrow_speed || '0');
            }
          } catch (e) {
            console.error('Failed to fetch governance data or COMP price', e);
          }
        }

        const SECONDS_PER_YEAR = 60 * 60 * 24 * 365;

        const finalData: ChartPoint[] = points.map((pt) => {
          const supplyUsd = parseFloat(pt.supply_usd || '0');
          const borrowUsd = parseFloat(pt.borrow_usd || '0');
          
          const baseSupplyApr = parseFloat(pt.supply_apr || '0') * 100;
          const baseBorrowApr = parseFloat(pt.borrow_apr || '0') * 100;

          let rewardSupplyApr = 0;
          let rewardBorrowApr = 0;

          if (version === 'v3' && trackingIndexScale > 0) {
            if (supplyUsd > 0) {
              rewardSupplyApr = (baseTrackingSupplySpeed * SECONDS_PER_YEAR / trackingIndexScale * compPrice / supplyUsd) * 100;
            }
            if (borrowUsd > 0) {
              rewardBorrowApr = (baseTrackingBorrowSpeed * SECONDS_PER_YEAR / trackingIndexScale * compPrice / borrowUsd) * 100;
            }
          }

          return {
            timestamp: pt.timestamp.replace('T', ' '),
            borrow_usd: borrowUsd,
            total_market_usd: Math.max(0, supplyUsd),
            asset_price_usd: parseFloat(pt.price_usd || '0'),
            borrow_apr: baseBorrowApr,
            supply_apr: baseSupplyApr,
            utilization: parseFloat(pt.utilization || '0') * 100,
            total_supply_apr: baseSupplyApr + rewardSupplyApr,
            total_borrow_apr: baseBorrowApr - rewardBorrowApr,
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
  }, [version, market, timeRange, customStart, customEnd]);

  const marketSizeAxis = useMemo(() => {
    const maxValue = data.reduce((max, item) => Math.max(max, item.total_market_usd, item.borrow_usd), 0);
    if (maxValue >= 1e9) return { divisor: 1e9, suffix: 'B' };
    if (maxValue >= 1e6) return { divisor: 1e6, suffix: 'M' };
    if (maxValue >= 1e3) return { divisor: 1e3, suffix: 'K' };
    return { divisor: 1, suffix: '' };
  }, [data]);

  const formatMarketSizeTick = (value: number) => {
    if (marketSizeAxis.divisor === 1) {
      return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
    }
    return `$${(value / marketSizeAxis.divisor).toFixed(2)}${marketSizeAxis.suffix}`;
  };

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
                yAxisId="left"
                stroke="#64748b"
                tickFormatter={formatMarketSizeTick}
                width={60}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                stroke="#f59e0b"
                tickFormatter={(val) => `$${val}`}
                width={60}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                formatter={(value: any, name: any) => {
                  let label = name;
                  if (name === `实际借出 ${marketSymbol} 总值`) label = `实际借出 ${marketSymbol} 总值`;
                  else if (name === `${marketSymbol} 市场可借出总值`) label = `${marketSymbol} 市场可借出总值`;
                  else if (name === `${marketSymbol} 资产价格`) label = `${marketSymbol} 资产价格`;
                  return [
                    `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                    label,
                  ];
                }}
              />
              <Legend />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="borrow_usd"
                name={`实际借出 ${marketSymbol} 总值`}
                stroke="#ef4444"
                dot={false}
                strokeWidth={2}
              />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="total_market_usd"
                name={`${marketSymbol} 市场可借出总值`}
                stroke="#10b981"
                dot={false}
                strokeWidth={2}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="asset_price_usd"
                name={`${marketSymbol} 资产价格`}
                stroke="#f59e0b"
                dot={false}
                strokeWidth={2}
                strokeDasharray="5 4"
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
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span className="card-title">存款年化总收益率与借款年化总利率</span>
            <div style={{ position: 'relative' }}>
              <button
                type="button"
                onClick={() => setShowRatesHelp((v) => !v)}
                onMouseEnter={() => setShowRatesHelp(true)}
                onMouseLeave={() => setShowRatesHelp(false)}
                style={{
                  width: '20px',
                  height: '20px',
                  borderRadius: '999px',
                  border: '1px solid #334155',
                  background: showRatesHelp ? '#334155' : '#0f172a',
                  color: '#cbd5e1',
                  fontWeight: 700,
                  cursor: 'pointer',
                  padding: 0,
                  fontSize: '0.75rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
                title="收益率说明"
              >
                ?
              </button>
              {showRatesHelp && (
                <div
                  onMouseEnter={() => setShowRatesHelp(true)}
                  onMouseLeave={() => setShowRatesHelp(false)}
                  style={{
                    position: 'absolute',
                    top: '28px',
                    left: 0,
                    width: '320px',
                    zIndex: 20,
                    background: '#0b1220',
                    border: '1px solid #334155',
                    borderRadius: '8px',
                    padding: '0.75rem',
                    boxShadow: '0 12px 24px rgba(2,6,23,0.55)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.5rem',
                    fontSize: '0.8rem',
                  }}
                >
                  <div style={{ color: '#94a3b8' }}>
                    <span style={{ color: '#e2e8f0', fontWeight: 600 }}>存款年化总收益率 = </span>
                    Compound v3 原生存款年利率 + 协议奖励代币收益率
                  </div>
                  <div style={{ color: '#94a3b8' }}>
                    <span style={{ color: '#e2e8f0', fontWeight: 600 }}>借款年化总利率 = </span>
                    Compound v3 原生借款年利率 - 协议奖励代币收益率
                  </div>
                </div>
              )}
            </div>
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
              <YAxis yAxisId="priceHidden" hide={true} />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                formatter={(value: any, name: any) => {
                  if (name === `${marketSymbol} 价格趋势`) {
                    return [
                      `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                      name,
                    ];
                  }
                  return [`${Number(value).toFixed(2)}%`, name];
                }}
              />
              <Legend />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="total_borrow_apr"
                name="借款年总利息率"
                stroke="#ef4444"
                dot={false}
                strokeWidth={2}
              />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="total_supply_apr"
                name="存款年总收益率"
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
              <Line
                yAxisId="priceHidden"
                type="monotone"
                dataKey="asset_price_usd"
                name={`${marketSymbol} 价格趋势`}
                stroke="#fbbf24"
                dot={false}
                strokeWidth={2}
                strokeDasharray="2 4"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
