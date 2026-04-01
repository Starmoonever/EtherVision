import { Fragment, useState, useEffect } from 'react';
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { fetchLiquidationPeriod, fetchLiquidationDetail } from '../api';
import { fetchUserPosition } from '../api';
import type { LiquidationDetailResponse as LiquidationData } from '../api';
import type { UserPosition } from '../api';

type SortField =
  | 'liq_price'
  | 'liq_price_rise'
  | 'eth_collateral_usd'
  | 'total_debt_usd'
  | 'weth_debt_usd'
  | 'total_collateral_usd';

type SortOrder = 'asc' | 'desc';

interface LiquidationChartProps {
  currentEthPrice: number;
  priceChange: number;
  version: 'v2' | 'v3' | 'all';
  side: 'collateral' | 'borrow';
  onPriceChange?: (value: number) => void;
}

interface ChartDataPoint {
  price: number;
  priceLabel: string;
  liquidationValue: number;
  liquidationAmount: number;
  isCurrent: boolean;
}

type ChartTooltipValue = string | number | ReadonlyArray<string | number>;

const PAGE_SIZE = 20;

function getDefaultSortField(side: 'collateral' | 'borrow'): SortField {
  return side === 'borrow' ? 'liq_price_rise' : 'liq_price';
}

function getDefaultSortOrder(side: 'collateral' | 'borrow'): SortOrder {
  return side === 'borrow' ? 'asc' : 'desc';
}

export function LiquidationChart({
  currentEthPrice,
  priceChange,
  version,
  side,
  onPriceChange,
}: LiquidationChartProps) {
  const [chartData, setChartData] = useState<ChartDataPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [modalLoading, setModalLoading] = useState(false);
  const [modalData, setModalData] = useState<LiquidationData | null>(null);
  const [sortField, setSortField] = useState<SortField>(getDefaultSortField(side));
  const [sortOrder, setSortOrder] = useState<SortOrder>(getDefaultSortOrder(side));
  const [currentPage, setCurrentPage] = useState(1);
  const [copiedAddress, setCopiedAddress] = useState('');
  const [expandedAddress, setExpandedAddress] = useState<string | null>(null);
  const [positionDetails, setPositionDetails] = useState<
    Record<
      string,
      {
        loading: boolean;
        error: string;
        data: UserPosition | null;
      }
    >
  >({});

  const selectedPrice = currentEthPrice * (1 + priceChange / 100);
  const totalPositions = parseInt(modalData?.positions_cnt || '0', 10);
  const totalPages = Math.max(1, Math.ceil(totalPositions / PAGE_SIZE));

  useEffect(() => {
    const fetchRangeData = async () => {
      if (currentEthPrice <= 0) return;

      setLoading(true);
      try {
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
        const fetchData = (v: string) => fetchLiquidationPeriod(side, v, start, end, 5);

        if (version === 'all') {
          const [v2Data, v3Data] = await Promise.all([fetchData('v2'), fetchData('v3')]);

          // 以 $1 整数价格为 key 对 v2/v3 数据对齐求和
          // interval=1 代表后端每 $1 出一个数据点，用 Math.round 消除浮点偏差
          const mergedMap = new Map<
            number,
            {
              simulated_eth_price: string;
              positions_cnt: number;
              total_liquidation_usd: number;
            }
          >();

          [...v2Data, ...v3Data].forEach((item) => {
            const priceKey = Math.round(parseFloat(item.simulated_eth_price));
            if (!mergedMap.has(priceKey)) {
              mergedMap.set(priceKey, {
                simulated_eth_price: priceKey.toString(),
                positions_cnt: 0,
                total_liquidation_usd: 0,
              });
            }
            const entry = mergedMap.get(priceKey)!;
            entry.positions_cnt += parseInt(item.positions_cnt);
            entry.total_liquidation_usd += parseFloat(item.total_liquidation_usd);
          });

          dataList = Array.from(mergedMap.values()).map((item) => ({
            simulated_eth_price: item.simulated_eth_price,
            positions_cnt: item.positions_cnt.toString(),
            total_liquidation_usd: item.total_liquidation_usd.toString(),
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

        const chartPoints: ChartDataPoint[] = rangeSteps.map((step) => {
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
          if (!closest || minDiff > 100) {
            // 阈值可调整
            // 如果找不到匹配点，value 设为 0
            return {
              price: simPrice,
              priceLabel: `${step > 0 ? '+' : ''}${step}%`,
              liquidationValue: 0,
              liquidationAmount: 0,
              isCurrent: false,
            };
          }

          return {
            price: simPrice,
            priceLabel: `${step > 0 ? '+' : ''}${step}%`,
            liquidationValue: parseFloat(closest.total_liquidation_usd) / 1.05,
            liquidationAmount: parseFloat(closest.total_liquidation_usd) / 1.05 / simPrice,
            isCurrent: false,
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

  const highlightedData = chartData.map((d) => ({
    ...d,
    isCurrent: Math.abs(d.price - selectedPrice) < currentEthPrice * 0.0025,
  }));

  useEffect(() => {
    setSortField(getDefaultSortField(side));
    setSortOrder(getDefaultSortOrder(side));
    setCurrentPage(1);
  }, [side]);

  useEffect(() => {
    if (!showModal || version === 'all') return;

    let cancelled = false;

    const loadModalData = async () => {
      setModalLoading(true);
      try {
        const result = await fetchLiquidationDetail(side, version, selectedPrice, {
          limit: PAGE_SIZE,
          offset: (currentPage - 1) * PAGE_SIZE,
          orderby: sortField,
          order: sortOrder,
        });

        if (!cancelled) {
          setModalData(result);
        }
      } catch (err) {
        console.error('Fetch detail error:', err);
        if (!cancelled) {
          setModalData(null);
        }
      } finally {
        if (!cancelled) {
          setModalLoading(false);
        }
      }
    };

    loadModalData();

    return () => {
      cancelled = true;
    };
  }, [currentPage, selectedPrice, showModal, side, sortField, sortOrder, version]);

  const handleShowDetails = () => {
    setCopiedAddress('');
    setCurrentPage(1);
    setSortField(getDefaultSortField(side));
    setSortOrder(getDefaultSortOrder(side));
    setModalData(null);
    setShowModal(true);
  };

  const handleCopyAddress = async (address: string) => {
    try {
      await navigator.clipboard.writeText(address);
      setCopiedAddress(address);
      window.setTimeout(() => {
        setCopiedAddress((prev) => (prev === address ? '' : prev));
      }, 1500);
    } catch (err) {
      console.error('Copy address failed:', err);
    }
  };

  const formatUsd = (value: string | undefined, maximumFractionDigits: number = 2) =>
    `$${parseFloat(value || '0').toLocaleString(undefined, { maximumFractionDigits })}`;

  const formatAmount = (value: string | undefined, maximumFractionDigits: number = 4) =>
    parseFloat(value || '0').toLocaleString(undefined, { maximumFractionDigits });

  const formatHealthFactor = (value: number) => {
    if (!Number.isFinite(value)) return 'inf';
    if (value > 100) return '>100';
    return value.toFixed(2);
  };

  const detailColumnCount = 5;

  const handleTogglePositionDetails = async (address: string) => {
    if (expandedAddress === address) {
      setExpandedAddress(null);
      return;
    }

    setExpandedAddress(address);

    if (positionDetails[address]?.data || positionDetails[address]?.loading) {
      return;
    }

    setPositionDetails((prev) => ({
      ...prev,
      [address]: {
        loading: true,
        error: '',
        data: null,
      },
    }));

    try {
      const data = await fetchUserPosition(address, version);
      setPositionDetails((prev) => ({
        ...prev,
        [address]: {
          loading: false,
          error: '',
          data,
        },
      }));
    } catch (err) {
      console.error('Fetch user position detail error:', err);
      setPositionDetails((prev) => ({
        ...prev,
        [address]: {
          loading: false,
          error: err instanceof Error ? err.message : '加载仓位详情失败',
          data: null,
        },
      }));
    }
  };

  if (loading && chartData.length === 0) {
    return (
      <div
        className="chart-container"
        style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      >
        <div className="spinner"></div>
      </div>
    );
  }

  // 修复图表宽度问题，确保ResponsiveContainer有确定的父容器大小
  return (
    <div className="chart-container" style={{ width: '100%', minHeight: '350px' }}>
      <div
        className="chart-header"
        style={{
          marginBottom: '1rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <span className="chart-title" style={{ color: '#cbd5e1', fontWeight: 700 }}>
          {' '}
          ETH 清算量{' '}
        </span>
        <button
          onClick={version === 'all' ? undefined : handleShowDetails}
          disabled={version === 'all'}
          title={version === 'all' ? '合并模式下不支持查询明细' : undefined}
          style={{
            background: '#1e293b',
            color: version === 'all' ? '#475569' : '#94a3b8',
            border: '1px solid #334155',
            padding: '0.3rem 0.8rem',
            borderRadius: '6px',
            fontSize: '0.8rem',
            cursor: version === 'all' ? 'not-allowed' : 'pointer',
            transition: 'all 0.2s',
            opacity: version === 'all' ? 0.5 : 1,
          }}
        >
          查询明细
        </button>
      </div>

      <div style={{ minWidth: 0 }}>
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart
            data={highlightedData}
            margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis
              dataKey="priceLabel"
              stroke="#64748b"
              label={{
                value: side === 'borrow' ? '价格上涨幅度' : '价格下降幅度',
                position: 'insideBottom',
                offset: -5,
                fill: '#64748b',
                fontSize: 12,
              }}
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
              tickFormatter={(value) =>
                `${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
              }
              domain={[0, side === 'borrow' ? 6000 : 3000]}
            />
            <Tooltip
              cursor={{ fill: '#1e293b', opacity: 0.4 }}
              contentStyle={{
                backgroundColor: '#0f172a',
                borderColor: '#1e293b',
                color: '#e2e8f0',
              }}
              itemStyle={{ color: '#f87171' }}
              formatter={(
                value: ChartTooltipValue | undefined,
                name: string | number | undefined,
              ) => {
                const normalizedValue = Array.isArray(value) ? value[0] : value;
                const label = String(name ?? '');
                if (label === 'liquidationAmount')
                  return [
                    `${Number(normalizedValue).toLocaleString(undefined, { maximumFractionDigits: 2 })} ETH`,
                    '清算数量',
                  ];
                return [`$${Number(normalizedValue ?? 0).toLocaleString()}`, '清算价值'];
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
              style={{ cursor: onPriceChange ? 'pointer' : undefined }}
              onClick={(barData) => {
                if (!onPriceChange) return;
                const clickedPrice: number = (barData as unknown as { price: number }).price;
                const rawPct = Math.round((clickedPrice / currentEthPrice - 1) * 100);
                const min = side === 'collateral' ? -100 : 0;
                const max = side === 'collateral' ? 0 : 100;
                onPriceChange(Math.max(min, Math.min(max, rawPct)));
              }}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              shape={(props: any) => {
                const { x, y, width, height, index } = props;
                const entry = highlightedData[index as number];
                const color = entry?.isCurrent ? '#ef4444' : '#334155';
                return (
                  <rect x={x} y={y} width={width} height={height} fill={color} rx={4} ry={4} />
                );
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

      {/* Modal Overlay */}
      {showModal && (
        <div
          style={{
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
            backdropFilter: 'blur(4px)',
          }}
        >
          <div
            style={{
              background: '#0f172a',
              border: '1px solid #334155',
              borderRadius: '12px',
              width: '92%',
              maxWidth: '1120px',
              maxHeight: '80vh',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)',
            }}
          >
            <div
              style={{
                padding: '1.2rem',
                borderBottom: '1px solid #1e293b',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <h3 style={{ margin: 0, color: '#e2e8f0' }}>
                  ETH 清算价格在{' '}
                  <span style={{ fontSize: '1.0rem', color: '#94a3b8', fontWeight: 'normal' }}>
                    {' '}
                    ${selectedPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </span>
                  浮动的账户
                </h3>
                <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                  在 ${selectedPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}{' '}
                  清算价格增减1%区间内，
                  <span style={{ color: '#f87171', fontWeight: 'bold' }}> {totalPositions} </span>
                  个仓位面临清算
                </span>
                <span style={{ fontSize: '0.78rem', color: '#64748b' }}>
                  规则：仅统计快照时健康因子 {'>'} 1 的仓位；抵押端仅保留 0 {'<'} 清算价格
                  {' < '}当前 ETH 价格的仓位，借贷端仅保留清算价格 {'>'} 当前 ETH 价格的仓位。
                </span>
              </div>
              <button
                onClick={() => setShowModal(false)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: '#64748b',
                  fontSize: '1.5rem',
                  cursor: 'pointer',
                }}
              >
                ×
              </button>
            </div>

            <div style={{ padding: '0 1.2rem 1.2rem 1.2rem', overflowY: 'auto' }}>
              <div
                style={{
                  display: 'flex',
                  gap: '1rem',
                  margin: '1rem 0',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                }}
              >
                <span style={{ color: '#94a3b8', fontSize: '0.9rem' }}>排序方式:</span>
                <select
                  value={sortField}
                  onChange={(e) => {
                    setSortField(e.target.value as SortField);
                    setCurrentPage(1);
                  }}
                  style={{
                    background: '#1e293b',
                    color: '#e2e8f0',
                    border: '1px solid #334155',
                    padding: '0.4rem',
                    borderRadius: '6px',
                    fontSize: '0.9rem',
                    outline: 'none',
                  }}
                >
                  {side === 'borrow' ? (
                    <>
                      <option value="liq_price_rise">清算价格</option>
                      <option value="weth_debt_usd">借出 ETH 价值 (USD)</option>
                      <option value="total_collateral_usd">仓位总抵押 (USD)</option>
                    </>
                  ) : (
                    <>
                      <option value="liq_price">清算价格</option>
                      <option value="eth_collateral_usd">抵押 ETH 价值 (USD)</option>
                      <option value="total_collateral_usd">仓位总抵押 (USD)</option>
                      <option value="total_debt_usd">仓位总债务 (USD)</option>
                    </>
                  )}
                </select>
                <button
                  onClick={() => {
                    setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'));
                    setCurrentPage(1);
                  }}
                  type="button"
                  style={{
                    background: '#1e293b',
                    color: '#e2e8f0',
                    border: '1px solid #334155',
                    padding: '0.4rem 0.75rem',
                    borderRadius: '6px',
                    fontSize: '0.9rem',
                    cursor: 'pointer',
                  }}
                >
                  {sortOrder === 'asc' ? '升序' : '降序'}
                </button>
                <span style={{ color: '#64748b', fontSize: '0.85rem' }}>
                  每页 {PAGE_SIZE} 条，共 {totalPositions} 条
                </span>
              </div>

              {modalLoading ? (
                <div style={{ textAlign: 'center', padding: '2rem', color: '#94a3b8' }}>
                  加载中...
                </div>
              ) : modalData?.positions && modalData.positions.length > 0 ? (
                <div>
                  <table
                    style={{
                      width: '100%',
                      tableLayout: 'fixed',
                      borderCollapse: 'collapse',
                      fontSize: '0.85rem',
                    }}
                  >
                    <thead>
                      <tr style={{ borderBottom: '1px solid #334155' }}>
                        <th
                          style={{
                            width: '29%',
                            textAlign: 'left',
                            padding: '0.75rem 0.6rem',
                            color: '#64748b',
                          }}
                        >
                          地址
                        </th>
                        <th
                          style={{
                            width: '17%',
                            textAlign: 'right',
                            padding: '0.75rem 0.6rem',
                            color: '#64748b',
                          }}
                        >
                          清算价格
                        </th>
                        {side === 'borrow' ? (
                          <>
                            <th
                              style={{
                                width: '18%',
                                textAlign: 'right',
                                padding: '0.75rem 0.6rem',
                                color: '#64748b',
                              }}
                            >
                              借出 ETH 数量
                            </th>
                            <th
                              style={{
                                width: '18%',
                                textAlign: 'right',
                                padding: '0.75rem 0.6rem',
                                color: '#64748b',
                              }}
                            >
                              借出 ETH 价值
                            </th>
                            <th
                              style={{
                                width: '18%',
                                textAlign: 'right',
                                padding: '0.75rem 0.6rem',
                                color: '#64748b',
                              }}
                            >
                              仓位总抵押
                            </th>
                          </>
                        ) : (
                          <>
                            <th
                              style={{
                                width: '18%',
                                textAlign: 'right',
                                padding: '0.75rem 0.6rem',
                                color: '#64748b',
                              }}
                            >
                              抵押 ETH 价值
                            </th>
                            <th
                              style={{
                                width: '18%',
                                textAlign: 'right',
                                padding: '0.75rem 0.6rem',
                                color: '#64748b',
                              }}
                            >
                              仓位总抵押
                            </th>
                            <th
                              style={{
                                width: '18%',
                                textAlign: 'right',
                                padding: '0.75rem 0.6rem',
                                color: '#64748b',
                              }}
                            >
                              仓位总债务
                            </th>
                          </>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {modalData.positions.map((pos, idx) => {
                        const detailState = positionDetails[pos.address];
                        const isExpanded = expandedAddress === pos.address;

                        return (
                          <Fragment key={`${idx}-${pos.address}`}>
                            <tr style={{ borderBottom: '1px solid #1e293b' }}>
                              <td style={{ padding: '0.75rem 0.6rem' }}>
                                <div
                                  style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem',
                                    color: '#cbd5e1',
                                    fontFamily: 'monospace',
                                    flexWrap: 'wrap',
                                  }}
                                >
                                  <span title={pos.address} style={{ whiteSpace: 'nowrap' }}>
                                    {pos.address.slice(0, 6)}...{pos.address.slice(-4)}
                                  </span>
                                  <button
                                    onClick={() => handleCopyAddress(pos.address)}
                                    type="button"
                                    style={{
                                      background:
                                        copiedAddress === pos.address ? '#14532d' : '#1e293b',
                                      color: copiedAddress === pos.address ? '#86efac' : '#94a3b8',
                                      border: '1px solid #334155',
                                      borderRadius: '6px',
                                      padding: '0.2rem 0.45rem',
                                      fontSize: '0.75rem',
                                      cursor: 'pointer',
                                    }}
                                  >
                                    {copiedAddress === pos.address ? '已复制' : '复制'}
                                  </button>
                                  <button
                                    onClick={() => handleTogglePositionDetails(pos.address)}
                                    type="button"
                                    style={{
                                      background: isExpanded ? '#334155' : '#1e293b',
                                      color: '#e2e8f0',
                                      border: '1px solid #334155',
                                      borderRadius: '6px',
                                      padding: '0.2rem 0.5rem',
                                      fontSize: '0.75rem',
                                      cursor: 'pointer',
                                    }}
                                  >
                                    {isExpanded ? '收起仓位' : '查看仓位'}
                                  </button>
                                </div>
                              </td>
                              <td
                                style={{
                                  textAlign: 'right',
                                  padding: '0.75rem 0.6rem',
                                  color: '#f87171',
                                }}
                              >
                                {formatUsd(side === 'borrow' ? pos.liq_price_rise : pos.liq_price)}
                              </td>
                              {side === 'borrow' ? (
                                <>
                                  <td
                                    style={{
                                      textAlign: 'right',
                                      padding: '0.75rem 0.6rem',
                                      color: '#e2e8f0',
                                    }}
                                  >
                                    {formatAmount(pos.weth_debt_amount)}
                                  </td>
                                  <td
                                    style={{
                                      textAlign: 'right',
                                      padding: '0.75rem 0.6rem',
                                      color: '#e2e8f0',
                                    }}
                                  >
                                    {formatUsd(pos.weth_debt_usd)}
                                  </td>
                                  <td
                                    style={{
                                      textAlign: 'right',
                                      padding: '0.75rem 0.6rem',
                                      color: '#94a3b8',
                                    }}
                                  >
                                    {formatUsd(pos.total_collateral_usd)}
                                  </td>
                                </>
                              ) : (
                                <>
                                  <td
                                    style={{
                                      textAlign: 'right',
                                      padding: '0.75rem 0.6rem',
                                      color: '#e2e8f0',
                                    }}
                                  >
                                    {formatUsd(pos.eth_collateral_usd)}
                                  </td>
                                  <td
                                    style={{
                                      textAlign: 'right',
                                      padding: '0.75rem 0.6rem',
                                      color: '#94a3b8',
                                    }}
                                  >
                                    {formatUsd(pos.total_collateral_usd)}
                                  </td>
                                  <td
                                    style={{
                                      textAlign: 'right',
                                      padding: '0.75rem 0.6rem',
                                      color: '#94a3b8',
                                    }}
                                  >
                                    {formatUsd(pos.total_debt_usd)}
                                  </td>
                                </>
                              )}
                            </tr>

                            {isExpanded && (
                              <tr key={`detail-${idx}-${pos.address}`}>
                                <td
                                  colSpan={detailColumnCount}
                                  style={{
                                    padding: '0.9rem 0.8rem 1rem',
                                    background: '#111827',
                                    borderBottom: '1px solid #1e293b',
                                  }}
                                >
                                  {detailState?.loading ? (
                                    <div style={{ color: '#94a3b8', padding: '0.5rem 0' }}>
                                      正在加载仓位明细...
                                    </div>
                                  ) : detailState?.error ? (
                                    <div style={{ color: '#fca5a5', padding: '0.5rem 0' }}>
                                      {detailState.error}
                                    </div>
                                  ) : detailState?.data ? (
                                    <div
                                      style={{
                                        display: 'flex',
                                        flexDirection: 'column',
                                        gap: '0.75rem',
                                      }}
                                    >
                                      <div
                                        style={{
                                          display: 'grid',
                                          gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                                          gap: '0.75rem',
                                        }}
                                      >
                                        <div
                                          style={{
                                            background: '#0f172a',
                                            border: '1px solid #1f2937',
                                            borderRadius: '10px',
                                            padding: '0.8rem',
                                            textAlign: 'center',
                                          }}
                                        >
                                          <div
                                            style={{
                                              color: '#64748b',
                                              fontSize: '0.78rem',
                                              marginBottom: '0.35rem',
                                            }}
                                          >
                                            总抵押
                                          </div>
                                          <div style={{ color: '#e2e8f0', fontWeight: 700 }}>
                                            {formatUsd(detailState.data.total_collateral_usd)}
                                          </div>
                                        </div>
                                        <div
                                          style={{
                                            background: '#0f172a',
                                            border: '1px solid #1f2937',
                                            borderRadius: '10px',
                                            padding: '0.8rem',
                                            textAlign: 'center',
                                          }}
                                        >
                                          <div
                                            style={{
                                              color: '#64748b',
                                              fontSize: '0.78rem',
                                              marginBottom: '0.35rem',
                                            }}
                                          >
                                            总债务
                                          </div>
                                          <div style={{ color: '#e2e8f0', fontWeight: 700 }}>
                                            {formatUsd(detailState.data.total_debt_usd)}
                                          </div>
                                        </div>
                                        <div
                                          style={{
                                            background: '#0f172a',
                                            border: '1px solid #1f2937',
                                            borderRadius: '10px',
                                            padding: '0.8rem',
                                            textAlign: 'center',
                                          }}
                                        >
                                          <div
                                            style={{
                                              color: '#64748b',
                                              fontSize: '0.78rem',
                                              marginBottom: '0.35rem',
                                            }}
                                          >
                                            波动前健康因子
                                          </div>
                                          <div style={{ color: '#e2e8f0', fontWeight: 700 }}>
                                            {formatHealthFactor(
                                              detailState.data.health_factor === 'inf'
                                                ? Number.POSITIVE_INFINITY
                                                : parseFloat(detailState.data.health_factor),
                                            )}
                                          </div>
                                        </div>
                                      </div>
                                      <div
                                        style={{
                                          display: 'grid',
                                          gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                                          gap: '1rem',
                                          alignItems: 'start',
                                        }}
                                      >
                                        <div
                                          style={{
                                            border: '1px solid #1f2937',
                                            borderRadius: '10px',
                                            background: '#0f172a',
                                            overflow: 'hidden',
                                          }}
                                        >
                                          <div
                                            style={{
                                              padding: '0.8rem 1rem',
                                              borderBottom: '1px solid #1f2937',
                                              color: '#86efac',
                                              fontWeight: 700,
                                            }}
                                          >
                                            抵押端
                                          </div>
                                          {detailState.data.reserves.filter(
                                            (reserve) =>
                                              parseFloat(reserve.supply_amount || '0') > 0,
                                          ).length > 0 ? (
                                            <div>
                                              <table
                                                style={{
                                                  width: '100%',
                                                  tableLayout: 'fixed',
                                                  borderCollapse: 'collapse',
                                                  fontSize: '0.82rem',
                                                }}
                                              >
                                                <thead>
                                                  <tr style={{ borderBottom: '1px solid #334155' }}>
                                                    <th
                                                      style={{
                                                        textAlign: 'left',
                                                        padding: '0.65rem 0.5rem',
                                                        color: '#64748b',
                                                      }}
                                                    >
                                                      资产
                                                    </th>
                                                    <th
                                                      style={{
                                                        textAlign: 'right',
                                                        padding: '0.65rem 0.5rem',
                                                        color: '#64748b',
                                                      }}
                                                    >
                                                      单价
                                                    </th>
                                                    <th
                                                      style={{
                                                        textAlign: 'right',
                                                        padding: '0.65rem 0.5rem',
                                                        color: '#64748b',
                                                      }}
                                                    >
                                                      抵押数量
                                                    </th>
                                                    <th
                                                      style={{
                                                        textAlign: 'right',
                                                        padding: '0.65rem 0.5rem',
                                                        color: '#64748b',
                                                      }}
                                                    >
                                                      抵押价值
                                                    </th>
                                                  </tr>
                                                </thead>
                                                <tbody>
                                                  {detailState.data.reserves
                                                    .filter(
                                                      (reserve) =>
                                                        parseFloat(reserve.supply_amount || '0') >
                                                        0,
                                                    )
                                                    .map((reserve) => (
                                                      <tr
                                                        key={`${pos.address}-supply-${reserve.token_address}`}
                                                        style={{
                                                          borderBottom: '1px solid #1f2937',
                                                        }}
                                                      >
                                                        <td
                                                          style={{
                                                            padding: '0.65rem 0.5rem',
                                                            color: '#e2e8f0',
                                                          }}
                                                        >
                                                          {reserve.symbol}
                                                        </td>
                                                        <td
                                                          style={{
                                                            textAlign: 'right',
                                                            padding: '0.65rem 0.5rem',
                                                            color: '#cbd5e1',
                                                          }}
                                                        >
                                                          {formatUsd(reserve.price_usd)}
                                                        </td>
                                                        <td
                                                          style={{
                                                            textAlign: 'right',
                                                            padding: '0.65rem 0.5rem',
                                                            color: '#cbd5e1',
                                                          }}
                                                        >
                                                          {formatAmount(reserve.supply_amount, 6)}
                                                        </td>
                                                        <td
                                                          style={{
                                                            textAlign: 'right',
                                                            padding: '0.65rem 0.5rem',
                                                            color: '#cbd5e1',
                                                          }}
                                                        >
                                                          {formatUsd(reserve.supply_usd)}
                                                        </td>
                                                      </tr>
                                                    ))}
                                                </tbody>
                                              </table>
                                            </div>
                                          ) : (
                                            <div
                                              style={{
                                                padding: '1rem',
                                                color: '#64748b',
                                                fontSize: '0.82rem',
                                              }}
                                            >
                                              无非零抵押仓位
                                            </div>
                                          )}
                                        </div>

                                        <div
                                          style={{
                                            border: '1px solid #1f2937',
                                            borderRadius: '10px',
                                            background: '#0f172a',
                                            overflow: 'hidden',
                                          }}
                                        >
                                          <div
                                            style={{
                                              padding: '0.8rem 1rem',
                                              borderBottom: '1px solid #1f2937',
                                              color: '#fca5a5',
                                              fontWeight: 700,
                                            }}
                                          >
                                            借贷端
                                          </div>
                                          {detailState.data.reserves.filter(
                                            (reserve) =>
                                              parseFloat(reserve.total_debt_amount || '0') > 0,
                                          ).length > 0 ? (
                                            <div>
                                              <table
                                                style={{
                                                  width: '100%',
                                                  tableLayout: 'fixed',
                                                  borderCollapse: 'collapse',
                                                  fontSize: '0.82rem',
                                                }}
                                              >
                                                <thead>
                                                  <tr style={{ borderBottom: '1px solid #334155' }}>
                                                    <th
                                                      style={{
                                                        textAlign: 'left',
                                                        padding: '0.65rem 0.5rem',
                                                        color: '#64748b',
                                                      }}
                                                    >
                                                      资产
                                                    </th>
                                                    <th
                                                      style={{
                                                        textAlign: 'right',
                                                        padding: '0.65rem 0.5rem',
                                                        color: '#64748b',
                                                      }}
                                                    >
                                                      单价
                                                    </th>
                                                    <th
                                                      style={{
                                                        textAlign: 'right',
                                                        padding: '0.65rem 0.5rem',
                                                        color: '#64748b',
                                                      }}
                                                    >
                                                      稳定债务
                                                    </th>
                                                    <th
                                                      style={{
                                                        textAlign: 'right',
                                                        padding: '0.65rem 0.5rem',
                                                        color: '#64748b',
                                                      }}
                                                    >
                                                      浮动债务
                                                    </th>
                                                    <th
                                                      style={{
                                                        textAlign: 'right',
                                                        padding: '0.65rem 0.5rem',
                                                        color: '#64748b',
                                                      }}
                                                    >
                                                      债务价值
                                                    </th>
                                                  </tr>
                                                </thead>
                                                <tbody>
                                                  {detailState.data.reserves
                                                    .filter(
                                                      (reserve) =>
                                                        parseFloat(
                                                          reserve.total_debt_amount || '0',
                                                        ) > 0,
                                                    )
                                                    .map((reserve) => (
                                                      <tr
                                                        key={`${pos.address}-debt-${reserve.token_address}`}
                                                        style={{
                                                          borderBottom: '1px solid #1f2937',
                                                        }}
                                                      >
                                                        <td
                                                          style={{
                                                            padding: '0.65rem 0.5rem',
                                                            color: '#e2e8f0',
                                                          }}
                                                        >
                                                          {reserve.symbol}
                                                        </td>
                                                        <td
                                                          style={{
                                                            textAlign: 'right',
                                                            padding: '0.65rem 0.5rem',
                                                            color: '#cbd5e1',
                                                          }}
                                                        >
                                                          {formatUsd(reserve.price_usd)}
                                                        </td>
                                                        <td
                                                          style={{
                                                            textAlign: 'right',
                                                            padding: '0.65rem 0.5rem',
                                                            color: '#cbd5e1',
                                                          }}
                                                        >
                                                          {formatAmount(
                                                            reserve.stable_debt_amount,
                                                            6,
                                                          )}
                                                        </td>
                                                        <td
                                                          style={{
                                                            textAlign: 'right',
                                                            padding: '0.65rem 0.5rem',
                                                            color: '#cbd5e1',
                                                          }}
                                                        >
                                                          {formatAmount(
                                                            reserve.variable_debt_amount,
                                                            6,
                                                          )}
                                                        </td>
                                                        <td
                                                          style={{
                                                            textAlign: 'right',
                                                            padding: '0.65rem 0.5rem',
                                                            color: '#cbd5e1',
                                                          }}
                                                        >
                                                          {formatUsd(reserve.total_debt_usd)}
                                                        </td>
                                                      </tr>
                                                    ))}
                                                </tbody>
                                              </table>
                                            </div>
                                          ) : (
                                            <div
                                              style={{
                                                padding: '1rem',
                                                color: '#64748b',
                                                fontSize: '0.82rem',
                                              }}
                                            >
                                              无非零借贷仓位
                                            </div>
                                          )}
                                        </div>
                                      </div>
                                    </div>
                                  ) : (
                                    <div style={{ color: '#94a3b8', padding: '0.5rem 0' }}>
                                      暂无仓位明细
                                    </div>
                                  )}
                                </td>
                              </tr>
                            )}
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : totalPositions > 0 ? (
                <div style={{ textAlign: 'center', padding: '2rem', color: '#94a3b8' }}>
                  当前页无数据
                </div>
              ) : (
                <div style={{ textAlign: 'center', padding: '2rem', color: '#64748b' }}>
                  该价格点无清算数据
                </div>
              )}

              {totalPositions > 0 && (
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginTop: '1rem',
                    paddingTop: '1rem',
                    borderTop: '1px solid #1e293b',
                    gap: '1rem',
                    flexWrap: 'wrap',
                  }}
                >
                  <span style={{ color: '#94a3b8', fontSize: '0.85rem' }}>
                    第 {currentPage} / {totalPages} 页
                  </span>
                  <div style={{ display: 'flex', gap: '0.75rem' }}>
                    <button
                      onClick={() => setCurrentPage((prev) => Math.max(1, prev - 1))}
                      disabled={currentPage === 1 || modalLoading}
                      type="button"
                      style={{
                        background: currentPage === 1 || modalLoading ? '#0f172a' : '#1e293b',
                        color: currentPage === 1 || modalLoading ? '#475569' : '#e2e8f0',
                        border: '1px solid #334155',
                        padding: '0.45rem 0.85rem',
                        borderRadius: '6px',
                        cursor: currentPage === 1 || modalLoading ? 'not-allowed' : 'pointer',
                      }}
                    >
                      上一页
                    </button>
                    <button
                      onClick={() => setCurrentPage((prev) => Math.min(totalPages, prev + 1))}
                      disabled={currentPage >= totalPages || modalLoading}
                      type="button"
                      style={{
                        background:
                          currentPage >= totalPages || modalLoading ? '#0f172a' : '#1e293b',
                        color: currentPage >= totalPages || modalLoading ? '#475569' : '#e2e8f0',
                        border: '1px solid #334155',
                        padding: '0.45rem 0.85rem',
                        borderRadius: '6px',
                        cursor:
                          currentPage >= totalPages || modalLoading ? 'not-allowed' : 'pointer',
                      }}
                    >
                      下一页
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
