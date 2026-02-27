import { useState, useEffect } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell
} from 'recharts';

interface LiquidationData {
  simulated_eth_price: string;
  positions_cnt: string;
  total_liquidation_usd: string;
}

interface LiquidationChartProps {
  currentEthPrice: number;
  priceChange: number;
}

export function LiquidationChart({ currentEthPrice, priceChange }: LiquidationChartProps) {
  const [data, setData] = useState<LiquidationData | null>(null);
  const [loading, setLoading] = useState(false);
  
  // 计算模拟的 ETH 价格
  const simulatedPrice = currentEthPrice * (1 + priceChange / 100);

  useEffect(() => {
    const fetchData = async () => {
      if (currentEthPrice <= 0) return;
      
      setLoading(true);
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL;
<<<<<<< HEAD
        const response = await fetch(`${baseUrl}/liquidate?eth_price=${simulatedPrice}&eth_ratio=0.1`);
=======
        const response = await fetch(`${baseUrl}/liquidate?eth_price=${simulatedPrice}&eth_ratio=0.4`);
>>>>>>> feat/charts
        if (!response.ok) throw new Error('无法获取清算数据');
        
        const result = await response.json();
        setData(result);
      } catch (err) {
        console.error('Fetch liquidation data error:', err);
        setData(null);
      } finally {
        setLoading(false);
      }
    };

    // 使用 debounce 避免频繁请求
    const timeoutId = setTimeout(fetchData, 500);
    return () => clearTimeout(timeoutId);
  }, [simulatedPrice]);

  if (loading) {
    return (
      <div className="chart-container" style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="spinner"></div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="chart-container" style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#64748b' }}>
        暂无清算数据
      </div>
    );
  }

  // 构造图表数据
  const chartData = [
    {
      name: '清算ETH价值',
      value: parseFloat(data.total_liquidation_usd) / 1.05,
      price: simulatedPrice
    }
  ];

  return (
    <div className="chart-container">
      <div className="chart-header" style={{ marginBottom: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="chart-title" style={{ color: '#cbd5e1', fontWeight: 700 }}>ETH 价格 ${simulatedPrice.toLocaleString(undefined, {maximumFractionDigits: 2})}</span>
        <span className="badge red-badge">
          涉及仓位: {data.positions_cnt}
        </span>
      </div>
      
      <div style={{ height: 300 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="name" stroke="#64748b" />
            <YAxis stroke="#64748b" tickFormatter={(value) => `$${(value / 1000000).toFixed(1)}M`} />
            <Tooltip 
              cursor={{fill: '#1e293b', opacity: 0.4}}
              contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#e2e8f0' }}
              itemStyle={{ color: '#f87171' }}
              formatter={(value: any) => [`$${Number(value).toLocaleString()}`, '清算ETH总价值']}
              labelFormatter={() => `ETH 价格: $${simulatedPrice.toLocaleString(undefined, {maximumFractionDigits: 2})}`}
            />
            <Bar dataKey="value" fill="#f87171" radius={[4, 4, 0, 0]}>
              <Cell fill="#f87171" />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      
      <div className="chart-footer" style={{ marginTop: '1rem', textAlign: 'center', fontSize: '0.9rem', color: '#94a3b8' }}>
        当 ETH 价格{simulatedPrice >= currentEthPrice ? '涨' : '跌'}至 <span style={{ color: '#e2e8f0', fontWeight: 'bold' }}>${simulatedPrice.toLocaleString(undefined, {maximumFractionDigits: 2})}</span> 时，
        预计清算ETH <span style={{ color: '#f87171', fontWeight: 'bold' }}>${parseFloat(data.total_liquidation_usd).toLocaleString()}</span> 
      </div>
    </div>
  );
}
