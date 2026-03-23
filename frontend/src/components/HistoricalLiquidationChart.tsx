import { Fragment, useEffect, useState } from 'react';
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
import { fetchHistoricalLiquidation, fetchHistoricalLiquidationDetail } from '../api/liquidation';
import { fetchHistoricalUserPosition } from '../api';
import type {
  HistoricalLiquidationPoint,
  HistoricalLiquidationDetailResponse,
} from '../api/liquidation';
import type { UserPosition } from '../api';

interface HistoricalLiquidationChartProps {
  version: 'v2' | 'v3' | 'all';
  side: 'collateral' | 'borrow';
  startDate: string;
  endDate: string;
  priceChange: number;
}

type SortField =
  | 'liq_price'
  | 'liq_price_rise'
  | 'eth_collateral_usd'
  | 'total_debt_usd'
  | 'weth_debt_usd'
  | 'total_collateral_usd';

type SortOrder = 'asc' | 'desc';

const PAGE_SIZE = 20;

function getDefaultSortField(side: 'collateral' | 'borrow'): SortField {
  return side === 'borrow' ? 'liq_price_rise' : 'liq_price';
}

function getDefaultSortOrder(side: 'collateral' | 'borrow'): SortOrder {
  return side === 'borrow' ? 'asc' : 'desc';
}

function getPreferredSnapshotDate(points: HistoricalLiquidationPoint[]): string | null {
  if (points.length === 0) return null;
  const latestWithLiquidation = [...points]
    .reverse()
    .find((point) => parseInt(point.liquidation_cnt, 10) > 0);
  return latestWithLiquidation?.snapshot_date ?? points[points.length - 1].snapshot_date;
}

export function HistoricalLiquidationChart({
  version,
  side,
  startDate,
  endDate,
  priceChange,
}: HistoricalLiquidationChartProps) {
  const [data, setData] = useState<HistoricalLiquidationPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedSnapshotDate, setSelectedSnapshotDate] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [modalLoading, setModalLoading] = useState(false);
  const [modalData, setModalData] = useState<HistoricalLiquidationDetailResponse | null>(null);
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

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      try {
        let nextData: HistoricalLiquidationPoint[] = [];

        if (version === 'all') {
          const [v2Data, v3Data] = await Promise.all([
            fetchHistoricalLiquidation(startDate, endDate, 'v2', priceChange),
            fetchHistoricalLiquidation(startDate, endDate, 'v3', priceChange),
          ]);

          const map = new Map<string, HistoricalLiquidationPoint>();

          [...v2Data, ...v3Data].forEach((item) => {
            if (!map.has(item.snapshot_date)) {
              map.set(item.snapshot_date, {
                snapshot_date: item.snapshot_date,
                liquidation_cnt: '0',
                total_eth_collateral_amount: '0',
                total_eth_collateral_usd: '0',
                total_weth_debt_amount: '0',
                total_weth_debt_usd: '0',
                eth_price: item.eth_price,
                sim_eth_price: item.sim_eth_price,
              });
            }
            const current = map.get(item.snapshot_date)!;
            current.liquidation_cnt = (
              parseInt(current.liquidation_cnt, 10) + parseInt(item.liquidation_cnt, 10)
            ).toString();
            current.total_eth_collateral_amount = (
              parseFloat(current.total_eth_collateral_amount) +
              parseFloat(item.total_eth_collateral_amount)
            ).toString();
            current.total_eth_collateral_usd = (
              parseFloat(current.total_eth_collateral_usd) +
              parseFloat(item.total_eth_collateral_usd)
            ).toString();
            current.total_weth_debt_amount = (
              parseFloat(current.total_weth_debt_amount) + parseFloat(item.total_weth_debt_amount)
            ).toString();
            current.total_weth_debt_usd = (
              parseFloat(current.total_weth_debt_usd) + parseFloat(item.total_weth_debt_usd)
            ).toString();
          });

          nextData = Array.from(map.values());
        } else {
          nextData = await fetchHistoricalLiquidation(startDate, endDate, version, priceChange);
        }

        const sorted = nextData.sort(
          (a, b) => new Date(a.snapshot_date).getTime() - new Date(b.snapshot_date).getTime(),
        );
        setData(sorted);
        setSelectedSnapshotDate((prev) => {
          if (prev && sorted.some((item) => item.snapshot_date === prev)) return prev;
          return getPreferredSnapshotDate(sorted);
        });
      } catch (err) {
        console.error('Failed to fetch historical liquidation data', err);
        setData([]);
        setSelectedSnapshotDate(null);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [endDate, priceChange, startDate, version]);

  useEffect(() => {
    setSortField(getDefaultSortField(side));
    setSortOrder(getDefaultSortOrder(side));
    setCurrentPage(1);
    setExpandedAddress(null);
    setPositionDetails({});
  }, [side]);

  useEffect(() => {
    setCurrentPage(1);
    setExpandedAddress(null);
    setPositionDetails({});
    setCopiedAddress('');
  }, [priceChange, selectedSnapshotDate, version]);

  const selectedPoint =
    data.find((item) => item.snapshot_date === selectedSnapshotDate) ??
    (data.length > 0 ? data[data.length - 1] : null);
  const activeSnapshotDate = selectedPoint?.snapshot_date ?? null;

  useEffect(() => {
    if (!showModal || version === 'all' || !activeSnapshotDate) return;

    let cancelled = false;

    const loadModalData = async () => {
      setModalLoading(true);
      try {
        const result = await fetchHistoricalLiquidationDetail(
          activeSnapshotDate,
          version,
          side,
          priceChange,
          {
            limit: PAGE_SIZE,
            offset: (currentPage - 1) * PAGE_SIZE,
            orderby: sortField,
            order: sortOrder,
          },
        );

        if (!cancelled) {
          setModalData(result);
        }
      } catch (err) {
        console.error('Failed to fetch historical liquidation detail', err);
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
  }, [
    activeSnapshotDate,
    currentPage,
    priceChange,
    showModal,
    side,
    sortField,
    sortOrder,
    version,
  ]);

  const selectedSimulatedPrice = parseFloat(
    modalData?.simulated_eth_price ?? selectedPoint?.sim_eth_price ?? '0',
  );
  const totalPositions = parseInt(modalData?.positions_cnt || '0', 10);
  const totalPages = Math.max(1, Math.ceil(totalPositions / PAGE_SIZE));
  const detailColumnCount = 5;

  const formatUsd = (value: string | undefined, maximumFractionDigits: number = 2) =>
    `$${parseFloat(value || '0').toLocaleString(undefined, { maximumFractionDigits })}`;

  const formatAmount = (value: string | undefined, maximumFractionDigits: number = 4) =>
    parseFloat(value || '0').toLocaleString(undefined, { maximumFractionDigits });

  const formatHealthFactor = (value: number) => {
    if (!Number.isFinite(value)) return 'inf';
    if (value > 100) return '>100';
    return value.toFixed(2);
  };

  const handleShowDetails = () => {
    if (!activeSnapshotDate) return;
    setCopiedAddress('');
    setExpandedAddress(null);
    setPositionDetails({});
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

  const handleTogglePositionDetails = async (address: string) => {
    if (!activeSnapshotDate || version === 'all') return;

    const cacheKey = `${activeSnapshotDate}:${address}`;
    if (expandedAddress === cacheKey) {
      setExpandedAddress(null);
      return;
    }

    setExpandedAddress(cacheKey);

    if (positionDetails[cacheKey]?.data || positionDetails[cacheKey]?.loading) {
      return;
    }

    setPositionDetails((prev) => ({
      ...prev,
      [cacheKey]: {
        loading: true,
        error: '',
        data: null,
      },
    }));

    try {
      const detail = await fetchHistoricalUserPosition(address, activeSnapshotDate, version);
      setPositionDetails((prev) => ({
        ...prev,
        [cacheKey]: {
          loading: false,
          error: '',
          data: detail,
        },
      }));
    } catch (err) {
      console.error('Fetch historical user position detail error:', err);
      setPositionDetails((prev) => ({
        ...prev,
        [cacheKey]: {
          loading: false,
          error: err instanceof Error ? err.message : '加载历史仓位详情失败',
          data: null,
        },
      }));
    }
  };

  if (loading && data.length === 0) {
    return (
      <div style={{ height: 350, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="spinner"></div>
      </div>
    );
  }

  if (!data.length) {
    return (
      <div
        style={{
          height: 350,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#64748b',
        }}
      >
        暂无数据
      </div>
    );
  }

  const chartData = data.map((d) => ({
    ...d,
    total_eth_collateral_usd_num: parseFloat(d.total_eth_collateral_usd),
    total_weth_debt_usd_num: parseFloat(d.total_weth_debt_usd),
    sim_eth_price_num: parseFloat(d.sim_eth_price),
    total_eth_collateral_amount_num: parseFloat(d.total_eth_collateral_amount),
    total_weth_debt_amount_num: parseFloat(d.total_weth_debt_amount),
    liquidation_cnt_num: parseInt(d.liquidation_cnt, 10),
    isSelected: d.snapshot_date === selectedPoint?.snapshot_date,
  }));

  return (
    <div style={{ width: '100%', minHeight: '350px' }}>
      <div
        className="chart-header"
        style={{
          marginBottom: '0.75rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '1rem',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
          <span className="chart-title" style={{ color: '#cbd5e1', fontWeight: 700 }}>
            历史清算趋势
          </span>
          <span style={{ color: '#94a3b8', fontSize: '0.82rem' }}>
            已选日期：
            <span style={{ color: '#e2e8f0', fontWeight: 700 }}>
              {' '}
              {selectedPoint?.snapshot_date ?? '--'}
            </span>
            ，仓位与 reserve 明细均截止该日 00:00 UTC
          </span>
        </div>
        <button
          onClick={version === 'all' ? undefined : handleShowDetails}
          disabled={version === 'all' || !activeSnapshotDate}
          title={version === 'all' ? '合并模式下不支持查询明细' : undefined}
          style={{
            background: '#1e293b',
            color: version === 'all' || !activeSnapshotDate ? '#475569' : '#94a3b8',
            border: '1px solid #334155',
            padding: '0.3rem 0.8rem',
            borderRadius: '6px',
            fontSize: '0.8rem',
            cursor: version === 'all' || !activeSnapshotDate ? 'not-allowed' : 'pointer',
            transition: 'all 0.2s',
            opacity: version === 'all' || !activeSnapshotDate ? 0.5 : 1,
          }}
        >
          查询明细
        </button>
      </div>

      <div style={{ width: '100%', height: 350 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis
              dataKey="snapshot_date"
              stroke="#64748b"
              tickFormatter={(val) => {
                const d = new Date(val);
                return `${d.getMonth() + 1}-${d.getDate()}`;
              }}
              fontSize={12}
            />
            <YAxis
              yAxisId="left"
              stroke={side === 'collateral' ? '#10b981' : '#f59e0b'}
              tickFormatter={(val) =>
                version === 'v2' ? `$${val}` : `$${(val / 1000000).toFixed(1)}M`
              }
              domain={[0, 'auto']}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              stroke="#3b82f6"
              tickFormatter={(val) => `$${val}`}
              domain={[0, side === 'borrow' ? 6000 : 3000]}
              allowDataOverflow={true}
            />
            <YAxis yAxisId="hidden" hide={true} width={0} />
            <Tooltip
              cursor={{ fill: '#1e293b', opacity: 0.35 }}
              contentStyle={{
                backgroundColor: '#0f172a',
                borderColor: '#1e293b',
                color: '#e2e8f0',
              }}
              itemStyle={{ fontSize: '0.9rem' }}
              formatter={(
                value: number | undefined,
                name: string | undefined,
              ): [string, string] => {
                const v = value ?? 0;
                const n = name ?? '';
                if (n === '模拟ETH价格' || n === 'sim_eth_price_num')
                  return [`$${v}`, '模拟ETH价格'];
                if (n === '该模拟价格下清算的抵押 ETH 总值' || n === 'total_eth_collateral_usd_num')
                  return [
                    `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
                    '该模拟价格下清算的抵押 ETH 总值',
                  ];
                if (n === '该模拟价格下清算的 ETH 债务总值' || n === 'total_weth_debt_usd_num')
                  return [
                    `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
                    '该模拟价格下清算的 ETH 债务总值',
                  ];
                if (n === '模拟价格下清算账户数' || n === 'liquidation_cnt_num')
                  return [String(v), '模拟价格下清算账户数'];
                if (n === '清算抵押ETH数量' || n === 'total_eth_collateral_amount_num')
                  return [
                    v.toLocaleString(undefined, { maximumFractionDigits: 2 }),
                    '清算抵押ETH数量',
                  ];
                if (n === '清算ETH债务总数量' || n === 'total_weth_debt_amount_num')
                  return [
                    v.toLocaleString(undefined, { maximumFractionDigits: 2 }),
                    '清算ETH债务总数量',
                  ];
                return [String(v), n];
              }}
              labelFormatter={(label) => `日期: ${label}（点击柱子可切换明细日期）`}
            />
            <Legend />
            {side === 'collateral' ? (
              <Bar
                yAxisId="left"
                dataKey="total_eth_collateral_usd_num"
                name="该模拟价格下清算的抵押 ETH 总值"
                fill="#10b981"
                opacity={0.8}
                radius={[4, 4, 0, 0]}
                onClick={(barData) => {
                  const nextDate = (barData as { snapshot_date?: string }).snapshot_date;
                  if (nextDate) setSelectedSnapshotDate(nextDate);
                }}
                cursor="pointer"
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                shape={(props: any) => {
                  const { x, y, width, height, index } = props;
                  const entry = chartData[index as number];
                  const color = entry?.isSelected ? '#34d399' : '#10b981';
                  return (
                    <rect
                      onClick={() => {
                        if (entry?.snapshot_date) setSelectedSnapshotDate(entry.snapshot_date);
                      }}
                      style={{ cursor: 'pointer' }}
                      x={x}
                      y={y}
                      width={width}
                      height={height}
                      fill={color}
                      rx={4}
                      ry={4}
                      opacity={entry?.isSelected ? 1 : 0.8}
                    />
                  );
                }}
              />
            ) : (
              <Bar
                yAxisId="left"
                dataKey="total_weth_debt_usd_num"
                name="该模拟价格下清算的 ETH 债务总值"
                fill="#f59e0b"
                opacity={0.8}
                radius={[4, 4, 0, 0]}
                onClick={(barData) => {
                  const nextDate = (barData as { snapshot_date?: string }).snapshot_date;
                  if (nextDate) setSelectedSnapshotDate(nextDate);
                }}
                cursor="pointer"
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                shape={(props: any) => {
                  const { x, y, width, height, index } = props;
                  const entry = chartData[index as number];
                  const color = entry?.isSelected ? '#fbbf24' : '#f59e0b';
                  return (
                    <rect
                      onClick={() => {
                        if (entry?.snapshot_date) setSelectedSnapshotDate(entry.snapshot_date);
                      }}
                      style={{ cursor: 'pointer' }}
                      x={x}
                      y={y}
                      width={width}
                      height={height}
                      fill={color}
                      rx={4}
                      ry={4}
                      opacity={entry?.isSelected ? 1 : 0.8}
                    />
                  );
                }}
              />
            )}
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="sim_eth_price_num"
              name="模拟ETH价格"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
            />
            <Line
              yAxisId="hidden"
              type="monotone"
              dataKey="liquidation_cnt_num"
              name="模拟价格下清算账户数"
              stroke="none"
              legendType="none"
              dot={false}
              activeDot={false}
            />
            <Line
              yAxisId="hidden"
              type="monotone"
              dataKey="total_eth_collateral_amount_num"
              name="清算抵押ETH数量"
              stroke="none"
              legendType="none"
              dot={false}
              activeDot={false}
            />
            <Line
              yAxisId="hidden"
              type="monotone"
              dataKey="total_weth_debt_amount_num"
              name="清算ETH债务总数量"
              stroke="none"
              legendType="none"
              dot={false}
              activeDot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div style={{ marginTop: '0.75rem', color: '#64748b', fontSize: '0.8rem' }}>
        点击柱状图选择历史日期，查询与展开的仓位明细均按该日 00:00 UTC 快照展示。
      </div>

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
                gap: '1rem',
              }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <h3 style={{ margin: 0, color: '#e2e8f0' }}>
                  {selectedPoint?.snapshot_date ?? '--'} 历史清算明细
                </h3>
                <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                  历史仓位数据截止该日 00:00 UTC；在模拟 ETH 价格
                  <span style={{ color: '#e2e8f0', fontWeight: 700 }}>
                    {' '}
                    $
                    {selectedSimulatedPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </span>
                  下，
                  <span style={{ color: '#f87171', fontWeight: 'bold' }}> {totalPositions} </span>
                  个仓位面临清算
                </span>
                <span style={{ fontSize: '0.78rem', color: '#64748b' }}>
                  规则：仅统计该日零点快照时健康因子 {'>'} 1 的仓位；抵押端仅保留 0 {'<'}
                  清算价格 {'<'} 当日 ETH 价格的仓位，借贷端仅保留清算价格 {'>'} 当日 ETH
                  价格的仓位。
                </span>
                {modalData?.note && (
                  <span style={{ fontSize: '0.78rem', color: '#64748b' }}>{modalData.note}</span>
                )}
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
                        const detailKey = `${activeSnapshotDate}:${pos.address}`;
                        const detailState = positionDetails[detailKey];
                        const isExpanded = expandedAddress === detailKey;

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
                  该日期在当前模拟价格下无清算数据
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
