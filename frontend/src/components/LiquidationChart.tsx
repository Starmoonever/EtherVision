import { useState, useEffect } from 'react';
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts';

interface Position {
  address: string;
  liq_price: string; // 用于抵押端
  liq_price_rise?: string; // 用于借贷端
  eth_collateral_amount?: string;
  eth_collateral_usd?: string;
  total_debt_usd?: string;
  weth_debt_amount?: string;
  weth_debt_usd?: string;
  total_collateral_usd?: string;
}

interface LiquidationData {
  simulated_eth_price: string;
  positions: Position[];
  positions_cnt: string;
  total_liquidation_usd: string;
  total_weth_debt_amount?: string;
  total_weth_debt_usd?: string;
}

type SortField = 'eth_collateral_amount' | 'eth_collateral_usd' | 'total_debt_usd' | 'weth_debt_amount' | 'weth_debt_usd' | 'total_collateral_usd';

interface LiquidationChartProps {
  currentEthPrice: number;
  priceChange: number;
  version: 'v2' | 'v3' | 'all';
  side: 'collateral' | 'borrow';
}

interface ChartDataPoint {
  price: number;
  priceLabel: string;
  liquidationValue: number;
  liquidationAmount: number;
  isCurrent: boolean;
}

export function LiquidationChart({ currentEthPrice, priceChange, version, side }: LiquidationChartProps) {
  const [chartData, setChartData] = useState<ChartDataPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [modalLoading, setModalLoading] = useState(false);
  const [modalData, setModalData] = useState<LiquidationData | null>(null);
  const [sortField, setSortField] = useState<SortField>('eth_collateral_usd');

  const selectedPrice = currentEthPrice * (1 + priceChange / 100);

  useEffect(() => {
    const fetchRangeData = async () => {
      if (currentEthPrice <= 0) return;

      setLoading(true);
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL;
        // 如果是 collateral，范围是 0.01 ~ currentEthPrice (下跌 -100% ~ 0%)
        // 如果是 borrow，范围可能是 currentEthPrice ~ currentEthPrice * 2 (上涨 0% ~ +100%)
        // 既然横轴要从 -100% 到 +100%，我们需要获取更宽范围的数据

        const start = side === 'borrow' ? currentEthPrice : 0.01;
        const end = side === 'borrow' ? currentEthPrice * 2 : currentEthPrice;

        let dataList: {
          simulated_eth_price: string;
          positions_cnt: string;
          total_liquidation_usd: string;
          total_weth_debt_amount?: string;
          total_weth_debt_usd?: string;
        }[] = [];

        // 获取数据函数
        const fetchData = async (v: string) => {
          let url = '';
          if (side === 'borrow') {
            url = `${baseUrl}/borrow/liquidate/period?start=${start}&end=${end}&interval=1&eth_ratio=0.4&version=${v}`;
          } else {
            url = `${baseUrl}/liquidate/period?start=${start}&end=${end}&interval=1&eth_ratio=0.4&version=${v}`;
          }

          const response = await fetch(url);
          if (!response.ok) throw new Error(`Fetch ${v} failed`);
          return await response.json();
        };

        if (version === 'all') {
          const [v2Data, v3Data] = await Promise.all([fetchData('v2'), fetchData('v3')]);

          // 合并数据
          // 假设数据按价格排序，或者我们需要按价格聚合并累加 total_liquidation_usd
          const mergedMap = new Map<string, {
            simulated_eth_price: string;
            positions_cnt: number;
            total_liquidation_usd: number;
          }>();

          [...v2Data, ...v3Data].forEach(item => {
            const priceKey = parseFloat(item.simulated_eth_price).toFixed(2); // 统一精度作为 key
            if (!mergedMap.has(priceKey)) {
              mergedMap.set(priceKey, {
                simulated_eth_price: item.simulated_eth_price,
                positions_cnt: 0,
                total_liquidation_usd: 0
              });
            }
            const entry = mergedMap.get(priceKey)!;
            entry.positions_cnt += parseInt(item.positions_cnt);
            entry.total_liquidation_usd += parseFloat(item.total_liquidation_usd);
          });

          dataList = Array.from(mergedMap.values()).map(item => ({
            simulated_eth_price: item.simulated_eth_price,
            positions_cnt: item.positions_cnt.toString(),
            total_liquidation_usd: item.total_liquidation_usd.toString()
          }));
        } else {
          dataList = await fetchData(version);
        }

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
        if (side === 'borrow') {
          // 借贷端：0% 到 +100%
          for (let i = 0; i <= 100; i += 1) {
            rangeSteps.push(i);
          }
        } else {
          // 抵押端：-100% 到 0%
          for (let i = -100; i <= 0; i += 0.5) {
            rangeSteps.push(i);
          }
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
  }, [currentEthPrice, version, side]);

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

      let positions: Position[] = [];
      let totalLiqUsd = 0;
      let posCnt = 0;

      const fetchDetail = async (v: string) => {
        let url = '';
        if (side === 'borrow') {
          url = `${baseUrl}/borrow/liquidate?eth_price=${selectedPrice - cap}&limit=1000&cap=${selectedPrice + cap}&version=${v}`;
        } else {
          url = `${baseUrl}/liquidate?eth_price=${selectedPrice - cap}&limit=1000&cap=${selectedPrice + cap}&version=${v}`;
        }

        const response = await fetch(url);
        if (response.status === 422) return null;
        if (!response.ok) throw new Error(`Fetch ${v} detail failed`);
        return await response.json();
      };

      if (version === 'all') {
        const [v2Res, v3Res] = await Promise.all([fetchDetail('v2'), fetchDetail('v3')]);

        const v2Positions = v2Res?.positions || [];
        const v3Positions = v3Res?.positions || [];

        positions = [...v2Positions, ...v3Positions];

        // 重新计算总和
        if (v2Res) {
          totalLiqUsd += parseFloat(v2Res.total_liquidation_usd);
          posCnt += parseInt(v2Res.positions_cnt);
        }
        if (v3Res) {
          totalLiqUsd += parseFloat(v3Res.total_liquidation_usd);
          posCnt += parseInt(v3Res.positions_cnt);
        }

      } else {
        const res = await fetchDetail(version);
        if (res) {
          positions = res.positions || [];
          totalLiqUsd = parseFloat(res.total_liquidation_usd);
          posCnt = parseInt(res.positions_cnt);
        }
      }

      const result: LiquidationData = {
        simulated_eth_price: selectedPrice.toString(),
        positions: positions,
        positions_cnt: posCnt.toString(),
        total_liquidation_usd: totalLiqUsd.toString()
      };

      // 初始排序，默认按 sortField (如果是 borrow 模式，可能默认排序字段不同)
      // 如果是借贷端，默认按 total_collateral_usd 排序，或者是 weth_debt_usd
      const initialSortField: SortField = side === 'borrow' ? 'weth_debt_usd' : 'eth_collateral_usd';
      setSortField(initialSortField);

      if (result.positions) {
        result.positions.sort((a: Position, b: Position) =>
          parseFloat(b[initialSortField] || '0') - parseFloat(a[initialSortField] || '0')
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

  // 当 sortField 改变时，重新排序 modalData
  useEffect(() => {
    setModalData(prev => {
      if (!prev?.positions) return prev;
      const sortedPositions = [...prev.positions].sort((a, b) => {
        const valA = parseFloat(a[sortField] || '0');
        const valB = parseFloat(b[sortField] || '0');
        return valB - valA;
      });
      return { ...prev, positions: sortedPositions };
    });
  }, [sortField]);

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
        <span className="chart-title" style={{ color: '#cbd5e1', fontWeight: 700 }}> ETH 清算量 </span>
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

      <div style={{ minWidth: 0 }}>
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={highlightedData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis
              dataKey="priceLabel"
              stroke="#64748b"
              label={{ value: side === 'borrow' ? '价格上涨幅度' : '价格下降幅度', position: 'insideBottom', offset: -5, fill: '#64748b', fontSize: 12 }}
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
              tickFormatter={(value) => `${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
            />
            <Tooltip
              cursor={{ fill: '#1e293b', opacity: 0.4 }}
              contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#e2e8f0' }}
              itemStyle={{ color: '#f87171' }}
              formatter={(value: number | string | (number | string)[] | undefined, name: string | undefined) => {
                if (name === 'liquidationAmount') return [`${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })} ETH`, '清算数量'];
                return [`$${Number(value).toLocaleString()}`, '清算价值'];
              }}
              labelFormatter={(label, payload) => {
                if (payload && payload.length > 0) {
                  const data = payload[0].payload;
                  return `ETH 价格: $${data.price.toLocaleString(undefined, { maximumFractionDigits: 0 })} (${data.priceLabel})`;
                }
                return label;
              }}
            />
            <Bar
              yAxisId="left"
              dataKey="liquidationValue"
              radius={[4, 4, 0, 0]}
              fill="#334155"
              activeBar={{ fill: '#4a6080' }}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              shape={(props: any) => {
                const { x, y, width, height, index } = props;
                const entry = highlightedData[index as number];
                const color = entry?.isCurrent ? '#ef4444' : '#334155';
                return <rect x={x} y={y} width={width} height={height} fill={color} rx={4} ry={4} />;
              }}
            />
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
        模拟ETH价格: <span style={{ color: '#e2e8f0', fontWeight: 'bold' }}>${selectedPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
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
                  ETH 清算价格在  <span style={{ fontSize: '1.0rem', color: '#94a3b8', fontWeight: 'normal' }}> ${selectedPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>浮动的账户
                </h3>
                <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                  在 ${selectedPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })} 清算价格增减1%区间内，
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

            <div style={{ padding: '0 1.2rem 1.2rem 1.2rem', overflowY: 'auto' }}>
              <div style={{ display: 'flex', gap: '1rem', margin: '1rem 0', alignItems: 'center' }}>
                <span style={{ color: '#94a3b8', fontSize: '0.9rem' }}>排序方式:</span>
                <select
                  value={sortField}
                  onChange={(e) => setSortField(e.target.value as SortField)}
                  style={{
                    background: '#1e293b',
                    color: '#e2e8f0',
                    border: '1px solid #334155',
                    padding: '0.4rem',
                    borderRadius: '6px',
                    fontSize: '0.9rem',
                    outline: 'none'
                  }}
                >
                  {side === 'borrow' ? (
                    <>
                      <option value="weth_debt_usd">借出 ETH 价值 (USD)</option>
                      <option value="weth_debt_amount">借出 ETH 数量</option>
                      <option value="total_collateral_usd">仓位总抵押 (USD)</option>
                    </>
                  ) : (
                    <>
                      <option value="eth_collateral_usd">抵押 ETH 价值 (USD)</option>
                      <option value="eth_collateral_amount">抵押 ETH 数量</option>
                      <option value="total_debt_usd">仓位总债务 (USD)</option>
                    </>
                  )}
                </select>
              </div>

              {modalLoading ? (
                <div style={{ textAlign: 'center', padding: '2rem', color: '#94a3b8' }}>加载中...</div>
              ) : modalData?.positions && modalData.positions.length > 0 ? (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid #334155' }}>
                      <th style={{ textAlign: 'left', padding: '0.8rem', color: '#64748b' }}>地址</th>
                      <th style={{ textAlign: 'right', padding: '0.8rem', color: '#64748b' }}>清算价格</th>
                      {side === 'borrow' ? (
                        <>
                          <th style={{ textAlign: 'right', padding: '0.8rem', color: '#64748b' }}>借出 ETH 数量</th>
                          <th style={{ textAlign: 'right', padding: '0.8rem', color: '#64748b' }}>借出 ETH 价值</th>
                          <th style={{ textAlign: 'right', padding: '0.8rem', color: '#64748b' }}>仓位总抵押</th>
                        </>
                      ) : (
                        <>
                          <th style={{ textAlign: 'right', padding: '0.8rem', color: '#64748b' }}>抵押 ETH 数量</th>
                          <th style={{ textAlign: 'right', padding: '0.8rem', color: '#64748b' }}>抵押 ETH 价值</th>
                          <th style={{ textAlign: 'right', padding: '0.8rem', color: '#64748b' }}>仓位总债务</th>
                        </>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {modalData.positions.map((pos, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid #1e293b' }}>
                        <td style={{ padding: '0.8rem', color: '#cbd5e1', fontFamily: 'monospace' }}>
                          {pos.address.slice(0, 6)}...{pos.address.slice(-4)}
                        </td>
                        <td style={{ textAlign: 'right', padding: '0.8rem', color: '#f87171' }}>
                          ${parseFloat(side === 'borrow' ? (pos.liq_price_rise || '0') : pos.liq_price).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                        </td>
                        {side === 'borrow' ? (
                          <>
                            <td style={{ textAlign: 'right', padding: '0.8rem', color: '#e2e8f0' }}>
                              {parseFloat(pos.weth_debt_amount || '0').toLocaleString(undefined, { maximumFractionDigits: 4 })}
                            </td>
                            <td style={{ textAlign: 'right', padding: '0.8rem', color: '#e2e8f0' }}>
                              ${parseFloat(pos.weth_debt_usd || '0').toLocaleString(undefined, { maximumFractionDigits: 2 })}
                            </td>
                            <td style={{ textAlign: 'right', padding: '0.8rem', color: '#94a3b8' }}>
                              ${parseFloat(pos.total_collateral_usd || '0').toLocaleString(undefined, { maximumFractionDigits: 2 })}
                            </td>
                          </>
                        ) : (
                          <>
                            <td style={{ textAlign: 'right', padding: '0.8rem', color: '#e2e8f0' }}>
                              {parseFloat(pos.eth_collateral_amount || '0').toLocaleString(undefined, { maximumFractionDigits: 4 })}
                            </td>
                            <td style={{ textAlign: 'right', padding: '0.8rem', color: '#e2e8f0' }}>
                              ${parseFloat(pos.eth_collateral_usd || '0').toLocaleString(undefined, { maximumFractionDigits: 2 })}
                            </td>
                            <td style={{ textAlign: 'right', padding: '0.8rem', color: '#94a3b8' }}>
                              ${parseFloat(pos.total_debt_usd || '0').toLocaleString(undefined, { maximumFractionDigits: 2 })}
                            </td>
                          </>
                        )}
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
