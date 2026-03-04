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

interface PositionReplayProps {
  address: string;
  version: 'v2' | 'v3';
}

interface ReplayPoint {
  timestamp: string;
  eth_price_usd: number;
  eth_collateral_usd: number;
  weth_debt_usd: number;
  liq_price: number;
  brief: string;
  total_collateral_usd: number;
  total_debt_usd: number;
  available_borrows_usd: number;
  health_factor: number;
}

const CustomTooltip = ({ active, payload, label, onDetailsClick }: any) => {
  if (active && payload && payload.length) {
    const point = payload[0].payload;
    return (
      <div className="custom-tooltip" style={{ backgroundColor: '#0f172a', borderColor: '#1e293b', border: '1px solid', padding: '10px', borderRadius: '4px' }}>
        <p className="label" style={{ color: '#94a3b8', marginBottom: '5px' }}>
           {point.brief ? `${label} - ${point.brief}` : label}
        </p>
        {payload.map((entry: any, index: number) => (
          <p key={index} style={{ color: entry.color, margin: 0, fontSize: '0.9rem' }}>
            {entry.name}: {entry.value}
          </p>
        ))}
        <button
            onClick={() => onDetailsClick(point)}
            style={{ marginTop: '8px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '4px', padding: '4px 8px', cursor: 'pointer', fontSize: '0.8rem' }}
        >
            账户头寸明细
        </button>
      </div>
    );
  }
  return null;
};

const DetailsModal = ({ point, onClose }: { point: ReplayPoint, onClose: () => void }) => {
    if (!point) return null;
    return (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
            <div style={{ background: '#1e293b', padding: '20px', borderRadius: '8px', width: '400px', maxWidth: '90%', border: '1px solid #334155' }}>
                <h3 style={{ color: '#fff', marginTop: 0, marginBottom: '1rem' }}>账户详情</h3>
                <div style={{ display: 'grid', gap: '10px', color: '#e2e8f0', fontSize: '0.9rem' }}>
                    <div style={{display:'flex', justifyContent:'space-between'}}><span style={{color:'#94a3b8'}}>时间:</span> <span>{point.timestamp}</span></div>
                    <div style={{display:'flex', justifyContent:'space-between'}}><span style={{color:'#94a3b8'}}>总抵押资产价值:</span> <span>${point.total_collateral_usd.toLocaleString(undefined, {maximumFractionDigits: 2})}</span></div>
                    <div style={{display:'flex', justifyContent:'space-between'}}><span style={{color:'#94a3b8'}}>总贷出债务价值:</span> <span>${point.total_debt_usd.toLocaleString(undefined, {maximumFractionDigits: 2})}</span></div>
                    <div style={{display:'flex', justifyContent:'space-between'}}><span style={{color:'#94a3b8'}}>可借出总额:</span> <span>${point.available_borrows_usd.toLocaleString(undefined, {maximumFractionDigits: 2})}</span></div>
                    <div style={{display:'flex', justifyContent:'space-between'}}><span style={{color:'#94a3b8'}}>健康因子:</span> <span>{point.health_factor.toFixed(2)}</span></div>
                    <div style={{display:'flex', justifyContent:'space-between'}}><span style={{color:'#94a3b8'}}>抵押ETH价值:</span> <span>${point.eth_collateral_usd.toLocaleString(undefined, {maximumFractionDigits: 2})}</span></div>
                    <div style={{display:'flex', justifyContent:'space-between'}}><span style={{color:'#94a3b8'}}>贷出ETH价值:</span> <span>${point.weth_debt_usd.toLocaleString(undefined, {maximumFractionDigits: 2})}</span></div>
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '20px' }}>
                    <button onClick={onClose} style={{ padding: '6px 16px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>关闭</button>
                </div>
            </div>
        </div>
    )
}

export function PositionReplayChart({ address, version }: PositionReplayProps) {
  const [data, setData] = useState<ReplayPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [primaryMetric, setPrimaryMetric] = useState<'eth_collateral_usd' | 'weth_debt_usd'>('eth_collateral_usd');
  const [selectedPoint, setSelectedPoint] = useState<ReplayPoint | null>(null);
  const [activeTooltip, setActiveTooltip] = useState<{
    index: number;
    coordinate: { x: number; y: number };
  } | null>(null);

  useEffect(() => {
    // Reset tooltip state when address or version changes
    setActiveTooltip(null);
    setSelectedPoint(null);
    
    const fetchData = async () => {
      setLoading(true);
      setError('');
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL;
        const start = '2020-12-01';
        const now = new Date();
        const year = now.getUTCFullYear();
        const month = String(now.getUTCMonth() + 1).padStart(2, '0');
        const day = String(now.getUTCDate()).padStart(2, '0');
        const hours = String(now.getUTCHours()).padStart(2, '0');
        const minutes = String(now.getUTCMinutes()).padStart(2, '0');
        const seconds = String(now.getUTCSeconds()).padStart(2, '0');
        const end = `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
        
        const response = await fetch(
          `${baseUrl}/position/replay?address=${address}&start=${start}&end=${encodeURIComponent(end)}&version=${version}`
        );
        
        if (!response.ok) {
          throw new Error('Failed to fetch replay data');
        }

        const result = await response.json();
        
        if (!result.points || !Array.isArray(result.points)) {
          throw new Error('Invalid data format');
        }

        const formattedData = result.points.map((pt: any) => ({
          timestamp: new Date(pt.timestamp).toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'numeric',
            day: 'numeric'
          }),
          eth_price_usd: parseFloat(pt.eth_price_usd || '0'),
          eth_collateral_usd: parseFloat(pt.eth_collateral_usd || '0'),
          weth_debt_usd: parseFloat(pt.weth_debt_usd || '0'),
          liq_price: parseFloat(pt.liq_price || '0'),
          brief: pt.brief || '',
          total_collateral_usd: parseFloat(pt.total_collateral_usd || '0'),
          total_debt_usd: parseFloat(pt.total_debt_usd || '0'),
          available_borrows_usd: parseFloat(pt.available_borrows_usd || '0'),
          health_factor: parseFloat(pt.health_factor || '0'),
        })).sort((a: any, b: any) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

        setData(formattedData);
      } catch (err) {
        console.error(err);
        setError('无法加载历史回放数据');
      } finally {
        setLoading(false);
      }
    };

    if (address) {
      fetchData();
    }
  }, [address, version]);

  const handleChartClick = (e: any) => {
    if (e && e.activeTooltipIndex !== undefined && e.activeCoordinate) {
      if (activeTooltip && activeTooltip.index === e.activeTooltipIndex) {
        setActiveTooltip(null); // Toggle off if clicking the same point
      } else {
        setActiveTooltip({
            index: e.activeTooltipIndex,
            coordinate: e.activeCoordinate
        });
      }
    } else {
      // Don't close if clicking inside the tooltip (handled by wrapperStyle pointerEvents)
      // But Recharts click handler is on the chart area.
      setActiveTooltip(null); 
    }
  };

  if (loading) return <div className="card" style={{height: 350, display: 'flex', alignItems: 'center', justifyContent: 'center'}}><div className="spinner"></div></div>;
  if (error) return <div className="card" style={{height: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#f87171'}}>{error}</div>;
  if (!data.length) return null;

  return (
    <div className="card" style={{ marginTop: '1.5rem' }}>
      <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="card-title">历史交易与头寸变化记录</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.85rem', color: '#94a3b8' }}>指标:</span>
          <select
            value={primaryMetric}
            onChange={(e) => setPrimaryMetric(e.target.value as any)}
            style={{
              background: '#1e293b',
              color: '#e2e8f0',
              border: '1px solid #334155',
              padding: '0.2rem 0.5rem',
              borderRadius: '4px',
              fontSize: '0.85rem'
            }}
          >
            <option value="eth_collateral_usd">抵押ETH价值 (USD)</option>
            <option value="weth_debt_usd">贷出ETH价值 (USD)</option>
          </select>
        </div>
      </div>

      <div style={{ height: 350 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart 
            data={data} 
            margin={{ top: 10, right: 30, left: 10, bottom: 5 }}
            onClick={handleChartClick}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis 
              dataKey="timestamp" 
              stroke="#64748b" 
              tick={{ fontSize: 12 }} 
              minTickGap={50}
            />
            
            {/* 左轴：资产/债务价值 */}
            <YAxis 
              yAxisId="left" 
              stroke="#10b981" 
              tickFormatter={(val) => `$${(val/1000).toFixed(0)}k`}
            />
            
            {/* 右轴：ETH价格 & 清算价格 */}
            <YAxis 
              yAxisId="right" 
              orientation="right" 
              stroke="#3b82f6"
              tickFormatter={(val) => `$${val}`}
            />

            <Tooltip
              content={<CustomTooltip onDetailsClick={setSelectedPoint} />}
              wrapperStyle={{ pointerEvents: 'auto', zIndex: 1000 }}
              trigger="hover" 
              active={activeTooltip !== null ? true : undefined}
              position={activeTooltip ? activeTooltip.coordinate : undefined}
            />
            {/* 
              Workaround: Recharts onClick gives us the activeIndex. 
              We can conditionally render a custom overlay OR try to force the Tooltip props.
              Actually, Recharts `Tooltip` has a `shared` and `defaultIndex` prop but not "force show at index".
              
              Better UX plan:
              1. Keep standard hover tooltip.
              2. When clicked, setting activeTooltipIndex.
              3. Pass `active={true}` and `payload={...}` corresponding to that index to Tooltip.
              
              However, cursor follows mouse. To "freeze" it, we might need to stop the mouse events or provide a fixed coordinate.
              Recharts doesn't make "freezing" easy. 
              
              Alternative: When clicked, we open the "DetailsModal" directly? 
              User asked to "fix the tooltip".
              
              Let's try controlling `active` and `payload`.
              Positioning will still follow mouse if we don't provide `coordinate`. 
              But `coordinate` is hard to calculate without internal chart state.
              
              Actually, `onClick` on Chart gives `activeCoordinate`. We can save that!
            */}
            <Legend />

            <Line
              yAxisId="left"
              type="monotone"
              dataKey={primaryMetric}
              stroke="#10b981"
              strokeWidth={2}
              dot={false}
              name={primaryMetric === 'eth_collateral_usd' ? '抵押ETH价值' : '贷出ETH价值'}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="eth_price_usd"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
              name="ETH 价格"
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="liq_price"
              stroke="#ef4444"
              strokeWidth={2}
              strokeDasharray="5 5"
              dot={false}
              name="ETH清算价格"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      
      {selectedPoint && (
        <DetailsModal point={selectedPoint} onClose={() => setSelectedPoint(null)} />
      )}
    </div>
  );
}
