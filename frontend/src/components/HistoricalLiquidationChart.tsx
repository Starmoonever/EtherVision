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
import { fetchHistoricalLiquidation } from '../api/liquidation';
import type { HistoricalLiquidationPoint } from '../api/liquidation';

interface HistoricalLiquidationChartProps {
  version: 'v2' | 'v3' | 'all';
  side: 'collateral' | 'borrow';
  startDate: string;
  endDate: string;
  priceChange: number;
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

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      try {
        if (version === 'all') {
          // Fetch v2 and v3 then aggregate
          const [v2Data, v3Data] = await Promise.all([
            fetchHistoricalLiquidation(startDate, endDate, 'v2', priceChange),
            fetchHistoricalLiquidation(startDate, endDate, 'v3', priceChange),
          ]);

          // Aggregate by snapshot_date
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
                eth_price: item.eth_price, // Assuming eth_price is same for same date
                sim_eth_price: item.sim_eth_price,
              });
            }
            const current = map.get(item.snapshot_date)!;
            current.liquidation_cnt = (
              parseInt(current.liquidation_cnt) + parseInt(item.liquidation_cnt)
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

          const sorted = Array.from(map.values()).sort(
            (a, b) => new Date(a.snapshot_date).getTime() - new Date(b.snapshot_date).getTime(),
          );
          setData(sorted);
        } else {
          const res = await fetchHistoricalLiquidation(startDate, endDate, version, priceChange);
          setData(
            res.sort(
              (a, b) => new Date(a.snapshot_date).getTime() - new Date(b.snapshot_date).getTime(),
            ),
          );
        }
      } catch (err) {
        console.error('Failed to fetch historical liquidation data', err);
        setData([]);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [version, startDate, endDate, priceChange]);

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

  // Format data for chart
  const chartData = data.map((d) => ({
    ...d,
    total_eth_collateral_usd_num: parseFloat(d.total_eth_collateral_usd),
    total_weth_debt_usd_num: parseFloat(d.total_weth_debt_usd),
    sim_eth_price_num: parseFloat(d.sim_eth_price),
    total_eth_collateral_amount_num: parseFloat(d.total_eth_collateral_amount),
    total_weth_debt_amount_num: parseFloat(d.total_weth_debt_amount),
    liquidation_cnt_num: parseInt(d.liquidation_cnt),
  }));

  return (
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
          {/* Left Axis: Total USD (Bar) */}
          <YAxis
            yAxisId="left"
            stroke={side === 'collateral' ? '#10b981' : '#f59e0b'}
            tickFormatter={(val) =>
              version === 'v2' ? `$${val}` : `$${(val / 1000000).toFixed(1)}M`
            }
            domain={[0, 'auto']}
          />
          {/* Right Axis: Simulated ETH Price (Line) — only sim_eth_price_num, no other dataKeys */}
          <YAxis
            yAxisId="right"
            orientation="right"
            stroke="#3b82f6"
            tickFormatter={(val) => `$${val}`}
            domain={[0, side === 'borrow' ? 6000 : 3000]}
            allowDataOverflow={true}
          />
          {/* Hidden Axis: hosts amount/count lines for tooltip only, never affects visible scales */}
          <YAxis yAxisId="hidden" hide={true} width={0} />
          <Tooltip
            contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#e2e8f0' }}
            itemStyle={{ fontSize: '0.9rem' }}
            formatter={(value: number | undefined, name: string | undefined): [string, string] => {
              const v = value ?? 0;
              const n = name ?? '';
              if (n === '模拟ETH价格' || n === 'sim_eth_price_num') return [`$${v}`, '模拟ETH价格'];
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
            labelFormatter={(label) => `日期: ${label}`}
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
            />
          ) : (
            <Bar
              yAxisId="left"
              dataKey="total_weth_debt_usd_num"
              name="该模拟价格下清算的 ETH 债务总值"
              fill="#f59e0b"
              opacity={0.8}
              radius={[4, 4, 0, 0]}
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
  );
}
