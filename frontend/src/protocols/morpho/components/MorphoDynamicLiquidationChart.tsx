import { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import type { EChartsOption } from 'echarts';
import { ChartInfoButton, type ExplainItem } from '../../../components/ChartAssist';
import {
  buildDynamicLiquidationSeries,
  syncAxis,
  type DynamicLiquidationPoint,
  type MorphoPricePoint,
} from './morphoDynamicLiquidationUtils';

type LiquidationChartMode = 'collateral' | 'debt';

interface MorphoDynamicLiquidationChartProps {
  collateralSeries: MorphoPricePoint[];
  debtSeries: MorphoPricePoint[];
  debtAmount: number;
  collateralAmount: number;
  lltv: number;
  collateralSymbol?: string;
  debtSymbol?: string;
  height?: number;
}

const dynamicLiquidationExplainItems: ExplainItem[] = [
  {
    term: '抵押物视角',
    formula: 'debtPrice[i] × debtAmount[i] / (collateralAmount[i] × LLTV)',
    meaning: '展示抵押品价格与“抵押品跌到多少会清算”的价格，两条线越接近，价格下跌风险越高。',
    riskHint: '清算线抬升通常表示借入增加或抵押减少；抵押价格下探接近清算线时需要重点关注。',
  },
  {
    term: '借款物视角',
    formula: 'collateralPrice[i] × collateralAmount[i] × LLTV / debtAmount[i]',
    meaning: '展示债务资产价格与“债务资产涨到多少会清算”的价格，适合观察借款物上涨导致的风险。',
    riskHint: '如果借款物是稳定币，这条价格线通常很平；清算线变化主要来自借入、还款和抵押变化。',
  },
  {
    term: '距离清算空间',
    formula: '(当前价格 - 清算价格) / 当前价格',
    meaning: '表示当前价格距离清算触发价格还剩多少百分比缓冲。',
    riskHint: '低于 10% 时通常需要重点关注价格波动、补抵押或还款操作。',
  },
];

function formatChartNumber(value: number, digits = 4): string {
  if (!Number.isFinite(value)) return '--';
  return value.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

export function MorphoDynamicLiquidationChart({
  collateralSeries,
  debtSeries,
  debtAmount,
  collateralAmount,
  lltv,
  collateralSymbol = 'Collateral',
  debtSymbol = 'Debt',
  height = 340,
}: MorphoDynamicLiquidationChartProps) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const [mode, setMode] = useState<LiquidationChartMode>('collateral');

  const chartData = useMemo(
    () =>
      buildDynamicLiquidationSeries({
        collateralSeries,
        debtSeries,
        debtAmount,
        collateralAmount,
        lltv,
      }),
    [collateralAmount, collateralSeries, debtAmount, debtSeries, lltv],
  );

  useEffect(() => {
    if (!chartRef.current || chartData.length === 0) return undefined;

    const chart = echarts.init(chartRef.current);
    const splitNumber = 5;
    const isDebtMode = mode === 'debt';
    const currentKey = isDebtMode ? 'debtPrice' : 'collateralPrice';
    const liquidationKey = isDebtMode ? 'debtLiquidationPrice' : 'liquidationPrice';
    const currentLabel = isDebtMode ? `${debtSymbol} 借款物价格` : `${collateralSymbol} 抵押物价格`;
    const liquidationLabel = isDebtMode
      ? `${debtSymbol} 借款物清算价`
      : `${collateralSymbol} 抵押物清算价`;
    const currentColor = isDebtMode ? '#cbd5e1' : '#60a5fa';
    const areaStartColor = isDebtMode ? 'rgba(203, 213, 225, 0.22)' : 'rgba(96, 165, 250, 0.3)';
    const yAxisExtent = syncAxis(
      chartData.flatMap((point) =>
        isDebtMode
          ? [point.debtPrice, point.debtLiquidationPrice]
          : [point.collateralPrice, point.liquidationPrice],
      ),
      [],
      splitNumber,
    ).left;

    const yAxis = echarts.util.map(
      [
        {
          type: 'value' as const,
          name: isDebtMode ? `${debtSymbol} 价格` : `${collateralSymbol} 价格`,
          position: 'left' as const,
          min: yAxisExtent.min,
          max: yAxisExtent.max,
          interval: yAxisExtent.interval,
          axisLabel: {
            color: '#94a3b8',
            formatter: (value: number) => formatChartNumber(value, 3),
          },
          axisLine: {
            lineStyle: {
              color: '#334155',
            },
          },
          splitLine: {
            lineStyle: {
              color: 'rgba(148, 163, 184, 0.14)',
              type: 'dashed',
            },
          },
        },
      ],
      (axisConfig) => ({
        ...axisConfig,
        splitNumber,
      }),
    ) as EChartsOption['yAxis'];

    const option: EChartsOption = {
      backgroundColor: 'transparent',
      animationDuration: 520,
      grid: {
        top: 58,
        right: 72,
        bottom: 58,
        left: 64,
        containLabel: true,
      },
      legend: {
        top: 8,
        textStyle: {
          color: '#cbd5e1',
        },
        itemGap: 18,
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(15, 23, 42, 0.96)',
        borderColor: 'rgba(148, 163, 184, 0.22)',
        borderWidth: 1,
        textStyle: {
          color: '#e5e7eb',
        },
        axisPointer: {
          type: 'cross',
          crossStyle: {
            color: '#64748b',
          },
        },
        formatter: (params: unknown) => {
          const items = Array.isArray(params) ? params : [params];
          const first = items[0] as { data?: DynamicLiquidationPoint } | undefined;
          const data = first?.data;
          if (!data) return '';

          const rows = items
            .map((item) => {
              const entry = item as {
                marker?: string;
                seriesName?: string;
              };
              const value = entry.seriesName?.includes('清算')
                ? isDebtMode
                  ? data.debtLiquidationPrice
                  : data.liquidationPrice
                : isDebtMode
                  ? data.debtPrice
                  : data.collateralPrice;
              return `
                <div style="display:flex;justify-content:space-between;gap:18px;margin:4px 0;">
                  <span>${entry.marker ?? ''}${entry.seriesName ?? ''}</span>
                  <strong>${formatChartNumber(value, 6)}</strong>
                </div>
              `;
            })
            .join('');

          const distancePct = isDebtMode
            ? data.debtLiquidationDistancePct
            : data.liquidationDistancePct;
          const distanceColor = distancePct <= 10 ? '#ef4444' : '#3fbb7d';
          const hfColor =
            data.healthFactor <= 1 ? '#ef4444' : data.healthFactor <= 1.15 ? '#f59e0b' : '#3fbb7d';

          return `
            <div style="min-width:250px;">
              <div style="font-weight:700;margin-bottom:8px;">${String(data.timestamp)}</div>
              ${rows}
              <div style="height:1px;background:rgba(148,163,184,0.18);margin:8px 0;"></div>
              <div style="display:flex;justify-content:space-between;gap:18px;margin:4px 0;">
                <span>当前价格比</span>
                <strong>${formatChartNumber(data.priceRatio, 6)}</strong>
              </div>
              <div style="display:flex;justify-content:space-between;gap:18px;margin:4px 0;">
                <span>实时 Health Factor</span>
                <strong style="color:${hfColor};">${formatChartNumber(data.healthFactor, 3)}</strong>
              </div>
              <div style="display:flex;justify-content:space-between;gap:18px;">
                <span>距离清算空间</span>
                <strong style="color:${distanceColor};">
                  ${formatChartNumber(distancePct, 2)}%
                </strong>
              </div>
            </div>
          `;
        },
      },
      dataset: {
        dimensions: [
          'timestamp',
          'collateralPrice',
          'debtPrice',
          'liquidationPrice',
          'debtLiquidationPrice',
          'priceRatio',
          'healthFactor',
          'liquidationDistancePct',
          'debtLiquidationDistancePct',
          'riskMargin',
        ],
        source: chartData,
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        axisLabel: {
          color: '#94a3b8',
        },
        axisLine: {
          lineStyle: {
            color: '#334155',
          },
        },
        axisTick: {
          show: false,
        },
      },
      yAxis,
      dataZoom: [
        {
          type: 'inside',
          start: 70,
          end: 100,
        },
        {
          type: 'slider',
          height: 22,
          bottom: 16,
          start: 70,
          end: 100,
          showDetail: false,
          borderColor: 'rgba(148, 163, 184, 0.16)',
          fillerColor: 'rgba(96, 165, 250, 0.16)',
          handleStyle: {
            color: '#60a5fa',
          },
          textStyle: {
            color: '#94a3b8',
          },
        },
      ],
      series: [
        {
          name: currentLabel,
          type: 'line',
          yAxisIndex: 0,
          encode: {
            x: 'timestamp',
            y: currentKey,
          },
          smooth: true,
          showSymbol: false,
          lineStyle: {
            width: 2.4,
            color: currentColor,
          },
          areaStyle: {
            opacity: 1,
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: areaStartColor },
              { offset: 1, color: 'rgba(15, 23, 42, 0)' },
            ]),
          },
          emphasis: {
            focus: 'series',
            lineStyle: {
              width: 3,
            },
          },
        },
        {
          name: liquidationLabel,
          type: 'line',
          yAxisIndex: 0,
          encode: {
            x: 'timestamp',
            y: liquidationKey,
          },
          smooth: true,
          showSymbol: false,
          z: 8,
          zlevel: 1,
          lineStyle: {
            width: 2,
            type: [5, 5] as unknown as 'dashed',
            color: '#f59e0b',
          },
          emphasis: {
            focus: 'series',
            lineStyle: {
              width: 2.8,
            },
          },
        },
      ],
    };

    chart.setOption(option);

    const handleResize = () => {
      chart.resize();
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.dispose();
    };
  }, [chartData, collateralSymbol, debtSymbol, mode]);

  if (chartData.length === 0) {
    return null;
  }

  const modeCopy =
    mode === 'collateral'
      ? '抵押物视角：观察抵押品价格距离抵押品清算价还有多远。'
      : '借款物视角：观察借款物价格距离借款物清算价还有多远。';

  return (
    <div className="morpho-dynamic-liquidation-card">
      <div className="morpho-dynamic-liquidation-header">
        <div>
          <div className="morpho-dynamic-liquidation-title-row">
            <strong>动态清算线</strong>
            <ChartInfoButton title="动态清算线读图提示" items={dynamicLiquidationExplainItems} />
          </div>
          <span>{modeCopy}</span>
        </div>
        <div
          className="morpho-dynamic-liquidation-switch"
          role="tablist"
          aria-label="清算线视角切换"
        >
          <button
            type="button"
            className={mode === 'collateral' ? 'active' : ''}
            onClick={() => setMode('collateral')}
            role="tab"
            aria-selected={mode === 'collateral'}
          >
            抵押物
          </button>
          <button
            type="button"
            className={mode === 'debt' ? 'active' : ''}
            onClick={() => setMode('debt')}
            role="tab"
            aria-selected={mode === 'debt'}
          >
            借款物
          </button>
        </div>
      </div>
      <div ref={chartRef} className="morpho-dynamic-liquidation-chart" style={{ height }} />
    </div>
  );
}
