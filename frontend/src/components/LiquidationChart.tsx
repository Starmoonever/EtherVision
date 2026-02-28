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
  Cell
} from 'recharts';

interface Position {
  address: string;
  liq_price: string;
  eth_collateral_amount: string;
  eth_collateral_usd: string;
  total_debt_usd: string;
}

interface LiquidationData {
  simulated_eth_price: string;
  positions: Position[];
  positions_cnt: string;
  total_liquidation_usd: string;
}

interface LiquidationChartProps {
  currentEthPrice: number;
  priceChange: number;
  version: 'v2' | 'v3';
}

interface ChartDataPoint {
  price: number;
  priceLabel: string;
  liquidationValue: number;
  liquidationAmount: number;
  isCurrent: boolean;
}

export function LiquidationChart({ currentEthPrice, priceChange, version }: LiquidationChartProps) {
  const [chartData, setChartData] = useState<ChartDataPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [modalLoading, setModalLoading] = useState(false);
  const [modalData, setModalData] = useState<LiquidationData | null>(null);
  
  const selectedPrice = currentEthPrice * (1 + priceChange / 100);

  useEffect(() => {
    const fetchRangeData = async () => {
      if (currentEthPrice <= 0) return;

      setLoading(true);
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL;
        const start = 0.01;
        const end = currentEthPrice;
        // 使用新接口一次性获取所有数据点
        // 注意：API 路径应为 /liquidate/period 且参数名为 interval 而非 intereval (通常拼写)
        // 根据用户输入: "intereval=1"，这里按照用户要求拼写
        const response = await fetch(`${baseUrl}/liquidate/period?start=${start}&end=${end}&interval=1&eth_ratio=0.4&version=${version}`);
        
        if (!response.ok) {
          console.error('Fetch liquidation period data failed');
          return;
        }

        const dataList: {
          simulated_eth_price: string;
          positions_cnt: string;
          total_liquidation_usd: string;
        }[] = await response.json();

        // 将返回的数组转换为 chartData
        // 需要映射到我们预设的 -100% 到 0% 的坐标系上
        // 这里的逻辑稍微复杂一点：
        // 1. 我们图表的 X 轴是 "价格下降幅度" (0% -> -100%)
        // 2. API 返回的是具体的 eth_price 点
        // 3. 我们需要把 API 数据映射到最近的 rangeSteps 上，或者直接使用 API 数据点？
        // 原有逻辑是固定 rangeSteps (-100, -99.5, ..., 0)，然后去 fetch 对应价格。
        // 现在 API 返回了一系列数据点。
        
        // 为了保持图表 X 轴的一致性（显示百分比），我们将 API 返回的数据映射回百分比
        // 假设 API 返回的数据覆盖了从 0.01 到 currentEthPrice 的区间
        
        // 构建一个 Map 方便查找
        // key: eth_price (number), value: data
        // 由于浮点数问题，可能需要模糊匹配
        
        // 简化方案：直接使用 rangeSteps，对于每个 step 计算出的 simPrice，在 dataList 中找最接近的
        
        const rangeSteps = [];
        for (let i = -100; i <= 0; i += 0.5) {
          rangeSteps.push(i);
        }

        const chartPoints: ChartDataPoint[] = rangeSteps.map(step => {
          const simPrice = currentEthPrice * (1 + step / 100);
          
          // 在 dataList 中寻找最接近 simPrice 的点
          // 假设 dataList 是按价格排序的，可以用二分查找，或者简单的 find
          // 这里数据量不大，简单遍历即可找到最接近的
          
          let closest = null;
          let minDiff = Infinity;
          
          for (const item of dataList) {
            const itemPrice = parseFloat(item.simulated_eth_price);
            const diff = Math.abs(itemPrice - simPrice);
            if (diff < minDiff) {
              minDiff = diff;
              closest = item;
            }
          }

          // 如果找不到接近的（比如差异太大），则认为无数据
          // 这里设定一个阈值，比如 5 USD
          if (!closest || minDiff > 100) { // 阈值可调整
             // 如果找不到匹配点，value 设为 0
             return {
              price: simPrice,
              priceLabel: `${step > 0 ? '+' : ''}${step}%`,
              liquidationValue: 0,
              liquidationAmount: 0,
              isCurrent: false
            };
          }

          return {
            price: simPrice,
            priceLabel: `${step > 0 ? '+' : ''}${step}%`,
            liquidationValue: parseFloat(closest.total_liquidation_usd) / 1.05,
            liquidationAmount: (parseFloat(closest.total_liquidation_usd) / 1.05) / simPrice,
            isCurrent: false
          };
        });
        
        setChartData(chartPoints);
      } catch (err) {
        console.error('Fetch liquidation range data error:', err);
      } finally {
        setLoading(false);
      }
    };
    
    fetchRangeData();
  }, [currentEthPrice, version]);

  const highlightedData = chartData.map(d => ({
    ...d,
    isCurrent: Math.abs(d.price - selectedPrice) < (currentEthPrice * 0.0025)
  }));

  const handleShowDetails = async () => {
    setModalLoading(true);
    setShowModal(true);
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL;
      const cap = selectedPrice * 0.01;
      const response = await fetch(`${baseUrl}/liquidate?eth_price=${selectedPrice - cap}&limit=1000&cap=${selectedPrice + cap}&version=${version}`);
      
      // 如果后端返回 422，可能是因为 eth_price 为 0 或无效，尝试容错处理
      if (response.status === 422) {
        console.warn('API returned 422, possibly invalid eth_price:', selectedPrice);
        setModalData({
          simulated_eth_price: selectedPrice.toString(),
          positions: [],
          positions_cnt: "0",
          total_liquidation_usd: "0"
        });
        return;
      }

      if (!response.ok) throw new Error('Failed to fetch details');
      const result: LiquidationData = await response.json();
      
      // 按 eth_collateral_usd 从大到小排序
      if (result.positions) {
        result.positions.sort((a, b) => 
          parseFloat(b.eth_collateral_usd) - parseFloat(a.eth_collateral_usd)
        );
      }
      
      setModalData(result);
    } catch (err) {
      console.error('Fetch detail error:', err);
      // 发生错误时清空数据，避免显示旧数据
      setModalData(null);
    } finally {
      setModalLoading(false);
    }
  };

  if (loading && chartData.length === 0) {
    return (
      <div className="chart-container" style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="spinner"></div>
      </div>
    );
  }

  // 修复图表宽度问题，确保ResponsiveContainer有确定的父容器大小
  return (
    <div className="chart-container" style={{ width: '100%', minHeight: '400px' }}>
      <div className="chart-header" style={{ marginBottom: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="chart-title" style={{ color: '#cbd5e1', fontWeight: 700 }}> ETH 清算量</span>
        <button 
          onClick={handleShowDetails}
          style={{
            background: '#1e293b',
            color: '#94a3b8',
            border: '1px solid #334155',
            padding: '0.3rem 0.8rem',
            borderRadius: '6px',
            fontSize: '0.8rem',
            cursor: 'pointer',
            transition: 'all 0.2s'
          }}
        >
          查询明细
        </button>
      </div>

      <div style={{ height: 300 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={highlightedData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis 
              dataKey="priceLabel" 
              stroke="#64748b" 
              label={{ value: '价格下降幅度', position: 'insideBottom', offset: -5, fill: '#64748b', fontSize: 12 }}
            />
            {/* 左轴：清算价值 (USD) */}
            <YAxis 
              yAxisId="left"
              stroke="#64748b" 
              tickFormatter={(value) => `$${(value / 1000000).toFixed(1)}M`} 
            />
            {/* 右轴：清算数量 (ETH) */}
            <YAxis 
              yAxisId="right"
              orientation="right"
              stroke="#a78bfa" 
              tickFormatter={(value) => `${value.toLocaleString(undefined, {maximumFractionDigits: 0})}`} 
            />
            <Tooltip 
              cursor={{fill: '#1e293b', opacity: 0.4}}
              contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#e2e8f0' }}
              itemStyle={{ color: '#f87171' }}
              formatter={(value: any, name: any) => {
                if (name === 'liquidationAmount') return [`${Number(value).toLocaleString(undefined, {maximumFractionDigits: 2})} ETH`, '清算数量'];
                return [`$${Number(value).toLocaleString()}`, '清算价值'];
              }}
              labelFormatter={(label, payload) => {
                if (payload && payload.length > 0) {
                  const data = payload[0].payload;
                  return `ETH 价格: $${data.price.toLocaleString(undefined, {maximumFractionDigits: 0})} (${data.priceLabel})`;
                }
                return label;
              }}
            />
            <Bar yAxisId="left" dataKey="liquidationValue" radius={[4, 4, 0, 0]}>
              {highlightedData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.isCurrent ? '#ef4444' : '#334155'} />
              ))}
            </Bar>
            <Line 
              yAxisId="right"
              type="monotone" 
              dataKey="liquidationAmount" 
              stroke="#a78bfa" 
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 6 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="chart-footer" style={{ marginTop: '1rem', textAlign: 'center', fontSize: '0.9rem', color: '#94a3b8' }}>
        模拟ETH价格: <span style={{ color: '#e2e8f0', fontWeight: 'bold' }}>${selectedPrice.toLocaleString(undefined, {maximumFractionDigits: 2})}</span> 
        ({priceChange > 0 ? '+' : ''}{priceChange}%)
      </div>
      <div className="chart-footer" style={{ textAlign: 'center', fontSize: '0.9rem', color: '#94a3b8' }}>
        该清算价格增减1%区间内，
        <span style={{ color: '#f87171', fontWeight: 'bold' }}>{modalData?.positions?.length || 0}</span> 个仓位面临清算
      </div>

      {/* Modal Overlay */}
      {showModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.7)',
          zIndex: 100,
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          backdropFilter: 'blur(4px)'
        }}>
          <div style={{
            background: '#0f172a',
            border: '1px solid #334155',
            borderRadius: '12px',
            width: '90%',
            maxWidth: '800px',
            maxHeight: '80vh',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)'
          }}>
            <div style={{ padding: '1.2rem', borderBottom: '1px solid #1e293b', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <h3 style={{ margin: 0, color: '#e2e8f0' }}>
                  ETH 清算价格为 <span style={{ fontSize: '0.9rem', color: '#94a3b8', fontWeight: 'normal' }}> ${selectedPrice.toLocaleString(undefined, {maximumFractionDigits: 2})}</span>的账户
                </h3>
                <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                  在 ${selectedPrice.toLocaleString(undefined, {maximumFractionDigits: 2})} 清算价格增减1%区间内，
                  <span style={{ color: '#f87171', fontWeight: 'bold' }}> {modalData?.positions?.length || 0} </span> 
                  个仓位面临清算
                </span>
              </div>
              <button 
                onClick={() => setShowModal(false)}
                style={{ background: 'none', border: 'none', color: '#64748b', fontSize: '1.5rem', cursor: 'pointer' }}
              >
                ×
              </button>
            </div>
            
            <div style={{ padding: '1.2rem', overflowY: 'auto' }}>
              {modalLoading ? (
                <div style={{ textAlign: 'center', padding: '2rem', color: '#94a3b8' }}>加载中...</div>
              ) : modalData?.positions && modalData.positions.length > 0 ? (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid #334155' }}>
                      <th style={{ textAlign: 'left', padding: '0.8rem', color: '#64748b' }}>地址</th>
                      <th style={{ textAlign: 'right', padding: '0.8rem', color: '#64748b' }}>清算价格</th>
                      <th style={{ textAlign: 'right', padding: '0.8rem', color: '#64748b' }}>抵押ETH</th>
                      <th style={{ textAlign: 'right', padding: '0.8rem', color: '#64748b' }}>抵押价值 (USD)</th>
                      <th style={{ textAlign: 'right', padding: '0.8rem', color: '#64748b' }}>总债务 (USD)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modalData.positions.map((pos, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid #1e293b' }}>
                        <td style={{ padding: '0.8rem', color: '#cbd5e1', fontFamily: 'monospace' }}>
                          {pos.address.slice(0, 6)}...{pos.address.slice(-4)}
                        </td>
                        <td style={{ textAlign: 'right', padding: '0.8rem', color: '#f87171' }}>
                          ${parseFloat(pos.liq_price).toLocaleString(undefined, {maximumFractionDigits: 2})}
                        </td>
                        <td style={{ textAlign: 'right', padding: '0.8rem', color: '#e2e8f0' }}>
                          {parseFloat(pos.eth_collateral_amount).toLocaleString(undefined, {maximumFractionDigits: 4})}
                        </td>
                        <td style={{ textAlign: 'right', padding: '0.8rem', color: '#e2e8f0' }}>
                          ${parseFloat(pos.eth_collateral_usd).toLocaleString(undefined, {maximumFractionDigits: 2})}
                        </td>
                        <td style={{ textAlign: 'right', padding: '0.8rem', color: '#94a3b8' }}>
                          ${parseFloat(pos.total_debt_usd).toLocaleString(undefined, {maximumFractionDigits: 2})}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div style={{ textAlign: 'center', padding: '2rem', color: '#64748b' }}>该价格点无清算数据</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
