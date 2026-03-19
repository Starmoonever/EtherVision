import { useState, useEffect } from 'react';
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { fetchWaterfallLiquidation } from '../api/liquidation';
import type { WaterfallResponse } from '../api/liquidation';

interface WaterfallLiquidationChartProps {
  version: 'v2' | 'v3' | 'all';
}

export function WaterfallLiquidationChart({ version }: WaterfallLiquidationChartProps) {
  const [data, setData] = useState<WaterfallResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sliders state
  const [initialShock, setInitialShock] = useState<number>(5); // 0% - 100%
  const [impactK, setImpactK] = useState<number>(2.5); // 1.0 - 6.0
  const [sellPartition, setSellPartition] = useState<number>(0.5); // 0.3 - 1.0
  const [date, setDate] = useState<string>('2026-02-10'); // 2026-01-01 to 2026-03-20

  useEffect(() => {
    const loadData = async () => {
      if (version === 'v2') {
        setError('无v2数据');
        setData(null);
        return;
      }

      setLoading(true);
      setError(null);
      try {
        const fetchVersion = version === 'all' ? 'v3' : version;
        const res = await fetchWaterfallLiquidation(
          fetchVersion,
          initialShock / 100, // convert percentage to decimal [0, 1)
          date,
          impactK,
          sellPartition
        );
        setData(res);
      } catch (err: any) {
        console.error('Failed to fetch waterfall liquidation data', err);
        setError(err.message || '获取数据失败');
        setData(null);
      } finally {
        setLoading(false);
      }
    };

    // Add a small debounce to prevent too many requests while dragging sliders
    const timeoutId = setTimeout(loadData, 300);
    return () => clearTimeout(timeoutId);
  }, [version, initialShock, impactK, sellPartition, date]);

  // Determine colors for sliders based on their values
  const getImpactKColor = (val: number) => {
    if (val <= 2.0) return '#4ade80'; // Green
    if (val <= 4.0) return '#facc15'; // Yellow
    return '#f87171'; // Red
  };

  const getSellPartitionColor = (val: number) => {
    if (val <= 0.5) return '#4ade80'; // Green
    if (val <= 0.8) return '#facc15'; // Yellow
    return '#f87171'; // Red
  };

  // Prepare chart data
  const chartData = data?.liquidation_turns.map((turn, index) => {
    const ethSoldValueNum = parseFloat(turn.eth_sold_value);
    const ethPriceNum = parseFloat(turn.eth_price);
    
    // Y left axis: eth_sold_value / sell_partition_eth
    const yLeftValue = ethSoldValueNum / sellPartition;

    return {
      turnName: index === 0 ? '初始冲击' : `轮次${index}`,
      yLeftValue,
      ethPriceNum,
      ...turn
    };
  }) || [];

  return (
    <div className="card" style={{ marginTop: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div className="card-header" style={{ marginBottom: '0.5rem' }}>
        <span className="card-title">模拟清算瀑布图 (多轮迭代)</span>
      </div>

      <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'flex-start' }}>
        {/* Left side: Controls (Date + 3 Sliders) */}
        <div style={{ flex: '0 0 300px', display: 'flex', flexDirection: 'column', gap: '1.5rem', background: '#0a0f1a', padding: '1rem', borderRadius: '8px', border: '1px solid #1e293b' }}>
          
          {/* Date Picker */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
              <span style={{ fontSize: '0.85rem', color: '#94a3b8' }}>模拟清算日期</span>
            </div>
            <input 
              type="date" 
              value={date} 
              min="2026-01-01"
              max="2026-03-20"
              onChange={e => setDate(e.target.value)}
              style={{ width: '100%', background: '#0f172a', border: '1px solid #334155', color: '#cbd5e1', borderRadius: '4px', padding: '0.4rem', fontSize: '0.9rem' }}
            />
          </div>

          {/* Slider 1: Initial Shock */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
              <span style={{ fontSize: '0.85rem', color: '#94a3b8' }}> ETH 价格初始跌幅</span>
              <span style={{ fontSize: '0.85rem', color: '#e2e8f0', fontWeight: 'bold' }}>{initialShock}%</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              step={1}
              value={initialShock}
              onChange={(e) => setInitialShock(Number(e.target.value))}
              style={{ width: '100%', accentColor: '#3b82f6' }}
            />
          </div>

          {/* Slider 2: Impact K */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
              <span 
                style={{ fontSize: '0.85rem', color: '#94a3b8', cursor: 'help', borderBottom: '1px dashed #64748b' }}
                title="衡量ETH清算抛售对价格冲击程度，数值越高，清算抛售导致价格下跌越剧烈"
              >
                市场流动性指数
              </span>
              <span style={{ fontSize: '0.85rem', color: getImpactKColor(impactK), fontWeight: 'bold' }}>{impactK.toFixed(1)}</span>
            </div>
            <div style={{ position: 'relative', paddingBottom: '1.2rem' }}>
              <input
                type="range"
                min={1.0}
                max={6.0}
                step={0.1}
                value={impactK}
                onChange={(e) => setImpactK(Number(e.target.value))}
                style={{ width: '100%', accentColor: getImpactKColor(impactK), position: 'relative', zIndex: 2 }}
              />
              {/* Markers for Impact K */}
              <div style={{ position: 'absolute', top: '15px', left: '20%', width: '1px', height: '6px', background: '#64748b', zIndex: 1 }} /> {/* 2.0 ( (2-1)/(6-1) = 20% ) */}
              <div style={{ position: 'absolute', top: '15px', left: '60%', width: '1px', height: '6px', background: '#64748b', zIndex: 1 }} /> {/* 4.0 ( (4-1)/(6-1) = 60% ) */}
              
              <div style={{ display: 'flex', position: 'absolute', top: '22px', width: '100%', fontSize: '0.7rem', color: '#64748b' }}>
                <span title="ETH 市场抗风险能力强，大额卖单对价格冲击微弱，模拟牛市" style={{ flex: 1, textAlign: 'left', cursor: 'help' }}>高流动</span>
                <span title="ETH 市场抗风险能力常规，模拟标准交易期" style={{ flex: 1, textAlign: 'center', cursor: 'help' }}>标准水平</span>
                <span title="ETH市场抗风险能力差，易触发连环爆仓导致价格进入死亡螺旋，模拟市场恐慌期" style={{ flex: 1, textAlign: 'right', cursor: 'help' }}>流动性枯竭</span>
              </div>
            </div>
          </div>

          {/* Slider 3: Sell Partition */}
          <div style={{ marginTop: '0.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
              <span 
                style={{ fontSize: '0.85rem', color: '#94a3b8', cursor: 'help', borderBottom: '1px dashed #64748b' }}
                title="衡量清算人获取抵押品后，立即在二级市场卖出套现的比例。该变现比例越高，对市场直接产生的清算冲击越大"
              >
                清算人变现比例
              </span>
              <span style={{ fontSize: '0.85rem', color: getSellPartitionColor(sellPartition), fontWeight: 'bold' }}>{sellPartition.toFixed(2)}</span>
            </div>
            <div style={{ position: 'relative', paddingBottom: '1.2rem' }}>
              <input
                type="range"
                min={0.3}
                max={1.0}
                step={0.05}
                value={sellPartition}
                onChange={(e) => setSellPartition(Number(e.target.value))}
                style={{ width: '100%', accentColor: getSellPartitionColor(sellPartition), position: 'relative', zIndex: 2 }}
              />
              {/* Markers for Sell Partition */}
              <div style={{ position: 'absolute', top: '15px', left: '0%', width: '1px', height: '6px', background: '#64748b', zIndex: 1 }} /> {/* 0.3 (0%) */}
              <div style={{ position: 'absolute', top: '15px', left: '42.8%', width: '1px', height: '6px', background: '#64748b', zIndex: 1 }} /> {/* 0.6 ( (0.6-0.3)/(1.0-0.3) ≈ 42.8% ) */}
              
              <div style={{ display: 'flex', position: 'absolute', top: '22px', width: '100%', fontSize: '0.7rem', color: '#64748b' }}>
                <span title="模拟清算人看涨ETH，倾向长期持有清算获得资产。此时清算仅发生资产转移，几乎不影响价格" style={{ width: '42.8%', textAlign: 'left', cursor: 'help' }}>长期持有</span>
                <span title="模拟 ETH 存在价格波动风险，部分清算人为规避风险卖出部分清算所得 ETH" style={{ flex: 1, textAlign: 'center', cursor: 'help' }}>规避风险</span>
                <span title="模拟极端行情下，清算人看空 ETH，为规避 ETH价格进一步下降，卖出大部分清算所得 ETH" style={{ width: '42.8%', textAlign: 'right', cursor: 'help' }}>极度恐慌</span>
              </div>
            </div>
          </div>

        </div>

        {/* Right side: Chart & Stats */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          
          {/* Top Stats Bar */}
          {data && !error && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', marginBottom: '1rem' }}>
              <div style={{ background: '#0a0f1a', padding: '0.8rem', borderRadius: '6px', border: '1px solid #1e293b' }}>
                <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>总清算价值 (USD)</div>
                <div style={{ fontSize: '1.2rem', color: '#10b981', fontWeight: 'bold' }}>${(parseFloat(data.total_liquidation_usd) / 1000000).toFixed(2)}M</div>
              </div>
              <div style={{ background: '#0a0f1a', padding: '0.8rem', borderRadius: '6px', border: '1px solid #1e293b' }}>
                <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>清算总轮数</div>
                <div style={{ fontSize: '1.2rem', color: '#e2e8f0', fontWeight: 'bold' }}>{data.liquidation_turns_cnt}</div>
              </div>
              <div style={{ background: '#0a0f1a', padding: '0.8rem', borderRadius: '6px', border: '1px solid #1e293b' }}>
                <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>总价格跌幅</div>
                <div style={{ fontSize: '1.2rem', color: '#f87171', fontWeight: 'bold' }}>{(parseFloat(data.total_decline) * 100).toFixed(2)}%</div>
              </div>
              <div style={{ background: '#0a0f1a', padding: '0.8rem', borderRadius: '6px', border: '1px solid #1e293b' }}>
                <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>被清算账户总数</div>
                <div style={{ fontSize: '1.2rem', color: '#e2e8f0', fontWeight: 'bold' }}>{data.total_liquidation_accounts}</div>
              </div>
            </div>
          )}

          {/* Chart Area */}
          <div style={{ height: 350, background: '#0a0f1a', borderRadius: '8px', border: '1px solid #1e293b', position: 'relative' }}>
            {error ? (
               <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#f87171' }}>
                 {error}
               </div>
            ) : loading ? (
              <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                 <div className="spinner"></div>
               </div>
            ) : !data || chartData.length === 0 ? (
               <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#64748b' }}>
                 暂无数据
               </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData} margin={{ top: 20, right: 50, left: 20, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis 
                    dataKey="turnName" 
                    stroke="#64748b" 
                    fontSize={12}
                    angle={-20}
                    textAnchor="end"
                    label={{ value: '清算轮次', position: 'right', offset: 10, fill: '#94a3b8', fontSize: 12 }}
                  />
                  {/* Left Axis: Sold Value / Partition (Bar) */}
                  <YAxis 
                    yAxisId="left"
                    stroke="#ef4444"
                    tickFormatter={(val) => `$${(val / 1000000).toFixed(1)}M`}
                  />
                  {/* Right Axis: ETH Price (Line) */}
                  <YAxis 
                    yAxisId="right"
                    orientation="right"
                    stroke="#3b82f6"
                    tickFormatter={(val) => `$${val}`}
                    domain={['auto', 'auto']}
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#e2e8f0' }}
                    itemStyle={{ fontSize: '0.9rem' }}
                    formatter={(value: any, name: any) => {
                        if (name === 'ethPriceNum') return [`$${value.toLocaleString(undefined, {maximumFractionDigits: 2})}`, '该轮 ETH 价格'];
                        if (name === 'yLeftValue') return [`$${value.toLocaleString(undefined, {maximumFractionDigits: 0})}`, '抛压估值 (Sold Value / Partition)'];
                        return [value, name];
                    }}
                    labelFormatter={(label) => `${label}`}
                  />
                  <Legend verticalAlign="top" height={36} />
                  <Bar 
                    yAxisId="left" 
                    dataKey="yLeftValue" 
                    name="该轮清算ETH价值 (USD)" 
                    fill="#ef4444" 
                    opacity={0.8}
                    radius={[4, 4, 0, 0]}
                  />
                  <Line 
                    yAxisId="right" 
                    type="monotone" 
                    dataKey="ethPriceNum" 
                    name="该轮 ETH 价格" 
                    stroke="#3b82f6" 
                    strokeWidth={2}
                    dot={{ r: 4, fill: '#0f172a', stroke: '#3b82f6', strokeWidth: 2 }}
                    activeDot={{ r: 6 }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
