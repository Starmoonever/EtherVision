import { useCallback, useEffect, useMemo, useState, type MouseEvent } from 'react';
import { isAddress } from 'viem';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  fetchMorphoVault,
  fetchMorphoVaultReallocations,
  MORPHO_VAULT_SAMPLE_ADDRESS,
  type MorphoVaultAllocation,
  type MorphoVaultReallocationPoint,
  type MorphoVaultResponse,
} from '../../../api/morpho';
import { copyToClipboard } from '../../../shared/utils/copyToClipboard';
import type { MorphoMarketView } from '../../../hooks/useMorphoData';
import { MorphoMarketTable, type MorphoSortMode } from '../components/MorphoMarketTable';

interface MorphoVaultPageProps {
  selectedMarketId: string;
  onMarketSelect: (marketId: string) => void;
  queryMarkets: MorphoMarketView[];
  expandedMarketId: string;
  onToggleMarket: (market: MorphoMarketView) => void;
  marketStateLoadingById: Record<string, boolean>;
  marketStateErrorById: Record<string, string>;
  sortMode: MorphoSortMode;
  onSortModeChange: (value: MorphoSortMode) => void;
}

const usdFormatter = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 2,
});

const compactUsdFormatter = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 2,
  notation: 'compact',
});

const numberFormatter = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 4,
});

const percentFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const ALLOCATION_COLORS = [
  '#38bdf8',
  '#22c55e',
  '#f59e0b',
  '#a78bfa',
  '#f472b6',
  '#14b8a6',
  '#f97316',
];
const vaultTooltipContentStyle = {
  border: '1px solid rgba(125, 211, 252, 0.22)',
  borderRadius: 8,
  background: 'rgba(8, 15, 29, 0.96)',
  boxShadow: '0 18px 36px rgba(2, 6, 23, 0.38)',
  color: '#e2e8f0',
};
const vaultTooltipLabelStyle = {
  color: '#bae6fd',
  fontWeight: 800,
};

function parseNumber(value: string | null | undefined): number | null {
  if (!value) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatUsd(value: string | null | undefined): string {
  const numeric = parseNumber(value);
  return numeric === null ? 'N/A' : `$${usdFormatter.format(numeric)}`;
}

function formatSmartUsd(value: string | null | undefined): string {
  const numeric = parseNumber(value);
  if (numeric === null) return 'N/A';
  return Math.abs(numeric) >= 1_000_000 ? formatCompactUsd(value) : formatUsd(value);
}

function formatCompactUsd(value: string | null | undefined): string {
  const numeric = parseNumber(value);
  return numeric === null ? 'N/A' : `$${compactUsdFormatter.format(numeric)}`;
}

function formatNumber(value: string | null | undefined): string {
  const numeric = parseNumber(value);
  return numeric === null ? 'N/A' : numberFormatter.format(numeric);
}

function formatPercent(value: string | null | undefined): string {
  const numeric = parseNumber(value);
  return numeric === null ? 'N/A' : `${percentFormatter.format(numeric * 100)}%`;
}

function formatDays(value: string | null | undefined): string {
  const numeric = parseNumber(value);
  return numeric === null ? 'N/A' : `${numberFormatter.format(numeric)} 天`;
}

function buildVaultNetApyTooltip(vault: MorphoVaultResponse): string {
  return [
    `Net APY: ${formatPercent(vault.net_apy)}`,
    `Gross APY: ${formatPercent(vault.apy)}`,
    `Net APY excl. rewards: ${formatPercent(vault.net_apy_excluding_rewards)}`,
    `Avg net APY: ${formatPercent(vault.avg_net_apy)}`,
    `Avg net APY excl. rewards: ${formatPercent(vault.avg_net_apy_excluding_rewards)}`,
  ].join('\n');
}

function compactAddress(address: string | null | undefined): string {
  if (!address) return 'N/A';
  return `${address.slice(0, 8)}...${address.slice(-6)}`;
}

function compactMarketId(marketId: string): string {
  return `${marketId.slice(0, 8)}...${marketId.slice(-5)}`;
}

function resolveAllocationLabel(allocation: MorphoVaultAllocation): string {
  const collateral = allocation.collateral_symbol || 'Idle';
  const loan = allocation.loan_symbol || '?';
  return `${collateral} / ${loan}`;
}

function resolveAllocationDisplayName(allocation: MorphoVaultAllocation): string {
  return allocation.collateral_symbol || 'Idle';
}

function createAllocationBars(allocations: MorphoVaultAllocation[]) {
  return allocations
    .map((allocation) => {
      const allocationUsd = parseNumber(allocation.supply_assets_usd) ?? 0;
      const supplyCapUsdRaw = parseNumber(allocation.supply_cap_usd);
      const isIdle = !allocation.collateral_symbol;
      const supplyCapUsd =
        !isIdle && supplyCapUsdRaw !== null && supplyCapUsdRaw < 1e30 ? supplyCapUsdRaw : null;
      const liquidityUsd = parseNumber(allocation.liquidity_usd) ?? 0;

      return {
        marketId: allocation.market_id,
        label: resolveAllocationLabel(allocation),
        displayName: resolveAllocationDisplayName(allocation),
        shortId: compactMarketId(allocation.market_id),
        supplyUsd: allocationUsd,
        allocation: allocationUsd,
        quotaUsd: allocationUsd,
        supplyCapUsd,
        capReference: supplyCapUsd ?? allocationUsd,
        capGap: supplyCapUsd !== null ? Math.max(0, supplyCapUsd - allocationUsd) : 0,
        liquidityUsd,
        liquidity: liquidityUsd,
        isIdle,
        rawAllocation: allocation,
      };
    })
    .sort((left, right) => right.supplyUsd - left.supplyUsd);
}

function createAllocationLegendItems(
  bars: ReturnType<typeof createAllocationBars>,
  totalTvl: number,
) {
  return bars.map((item, index) => ({
    ...item,
    color: ALLOCATION_COLORS[index % ALLOCATION_COLORS.length],
    share: totalTvl > 0 ? item.supplyUsd / totalTvl : 0,
  }));
}

function formatAxisUsd(value: number): string {
  if (value <= 0) return '$0';
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(0)}B`;
  if (value >= 100_000_000) return `$${(value / 1_000_000).toFixed(0)}M`;
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  return `$${compactUsdFormatter.format(value).replace('$', '')}`;
}

type AllocationHistogramItem = ReturnType<typeof createAllocationBars>[number];

interface AllocationCapLineProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: AllocationHistogramItem;
  highlightedMarketId?: string;
}

function AllocationCapLine({
  x = 0,
  y = 0,
  width = 0,
  height = 0,
  payload,
  highlightedMarketId = '',
}: AllocationCapLineProps) {
  if (!payload || payload.isIdle || payload.supplyCapUsd === null || width <= 0 || height <= 0) {
    return null;
  }

  const isHighlighted = payload.marketId === highlightedMarketId;
  const capWidth = Math.min(Math.max(width * 0.82, 26), width - 2);
  const capX = x + (width - capWidth) / 2;
  const capY = Math.max(8, y - 7);

  return (
    <g className="morpho-vault-bar-hit-target">
      <line
        x1={capX}
        y1={capY}
        x2={capX + capWidth}
        y2={capY}
        stroke={isHighlighted ? '#cbd5e1' : '#64748b'}
        strokeWidth={isHighlighted ? 3 : 2.4}
        strokeDasharray="6 3"
        strokeLinecap="round"
      />
      <line
        x1={capX}
        y1={capY - 4}
        x2={capX}
        y2={capY + 4}
        stroke={isHighlighted ? '#cbd5e1' : '#64748b'}
        strokeWidth={isHighlighted ? 2.2 : 1.8}
        strokeLinecap="round"
      />
      <line
        x1={capX + capWidth}
        y1={capY - 4}
        x2={capX + capWidth}
        y2={capY + 4}
        stroke={isHighlighted ? '#cbd5e1' : '#64748b'}
        strokeWidth={isHighlighted ? 2.2 : 1.8}
        strokeLinecap="round"
      />
    </g>
  );
}

interface AllocationLiquidityShapeProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: AllocationHistogramItem;
  fill?: string;
}

function AllocationLiquidityShape({
  x = 0,
  y = 0,
  width = 0,
  height = 0,
  payload,
  fill = '#10b981',
}: AllocationLiquidityShapeProps) {
  if (!payload || width <= 0 || height <= 0) return null;

  return (
    <g className="morpho-vault-bar-hit-target">
      <rect x={x} y={y} width={width} height={height} rx={1} fill={fill} />
    </g>
  );
}

interface AllocationAxisTickProps {
  x?: number | string;
  y?: number | string;
  payload?: { value?: string };
  index?: number;
  items: AllocationHistogramItem[];
  selectedMarketId: string;
  onMarketSelect: (marketId: string) => void;
}

function AllocationAxisTick({
  x = 0,
  y = 0,
  payload,
  index = 0,
  items,
  selectedMarketId,
  onMarketSelect,
}: AllocationAxisTickProps) {
  const item = items[index];
  const isSelected = item?.marketId === selectedMarketId;
  if (!item) return null;
  const numericX = Number(x);
  const numericY = Number(y);

  return (
    <g
      transform={`translate(${Number.isFinite(numericX) ? numericX : 0},${Number.isFinite(numericY) ? numericY : 0})`}
      className={
        isSelected
          ? 'morpho-vault-axis-tick morpho-vault-axis-tick-selected'
          : 'morpho-vault-axis-tick'
      }
      onClick={() => onMarketSelect(item.marketId)}
      role="button"
      aria-label={`查询 ${item.label}`}
    >
      <title>{item.marketId}</title>
      <text x={0} y={0} dy={16} textAnchor="end" transform="rotate(-45)">
        {payload?.value ?? item.displayName}
      </text>
    </g>
  );
}

function useCopiedValue() {
  const [copied, setCopied] = useState('');

  const copy = async (event: MouseEvent<HTMLButtonElement>, value: string) => {
    event.stopPropagation();
    const ok = await copyToClipboard(value);
    if (!ok) return;
    setCopied(value);
    window.setTimeout(() => {
      setCopied((current) => (current === value ? '' : current));
    }, 1400);
  };

  return { copied, copy };
}

function MorphoVaultCopyLine({
  label,
  value,
  copied,
  onCopy,
}: {
  label: string;
  value: string | null | undefined;
  copied: string;
  onCopy: (event: MouseEvent<HTMLButtonElement>, value: string) => void;
}) {
  if (!value) return null;
  return (
    <button
      type="button"
      className={
        copied === value
          ? 'morpho-vault-copy-line morpho-vault-copy-line-copied'
          : 'morpho-vault-copy-line'
      }
      onClick={(event) => onCopy(event, value)}
      title={`复制${label}: ${value}`}
    >
      <span>{compactAddress(value)}</span>
      <i aria-hidden="true" />
    </button>
  );
}

function MorphoVaultOverview({ vault }: { vault: MorphoVaultResponse }) {
  const { copied, copy } = useCopiedValue();
  const netApyTooltip = buildVaultNetApyTooltip(vault);

  return (
    <section className="card morpho-detail-card morpho-vault-overview-card">
      <div className="morpho-vault-hero-band">
        <div className="morpho-vault-hero-meta">
          <span className="morpho-vault-kicker">Vault</span>
          <div className="morpho-vault-hero-actions">
            <MorphoVaultCopyLine
              label="Vault 地址"
              value={vault.address}
              copied={copied}
              onCopy={copy}
            />
            <span className="morpho-vault-version">V2</span>
          </div>
        </div>
        <h2>{vault.name || vault.symbol || 'Morpho Vault'}</h2>
        <div className="morpho-vault-hero-summary">
          <p>
            以 {vault.asset.symbol || '底层资产'} 为基底，当前总资产{' '}
            {formatCompactUsd(vault.total_assets_usd)}，净收益 {formatPercent(vault.net_apy)}。
          </p>
          <div className="morpho-vault-tag-row morpho-vault-tag-row-hero">
            <span className="morpho-vault-tag">Fee {formatPercent(vault.fee)}</span>
            <span className="morpho-vault-tag">Timelock {formatDays(vault.timelock_days)}</span>
          </div>
        </div>
      </div>

      <div className="morpho-vault-detail-layout">
        <div className="morpho-vault-detail-main">
          <div className="morpho-vault-metric-grid">
            <div className="metric-box morpho-vault-asset-box">
              <span className="metric-label">底层资产</span>
              <strong>{vault.asset.symbol || 'N/A'}</strong>
              <MorphoVaultCopyLine
                label="底层资产地址"
                value={vault.asset.address}
                copied={copied}
                onCopy={copy}
              />
            </div>
            <div className="metric-box">
              <span className="metric-label">资产总美元值</span>
              <strong>{formatSmartUsd(vault.total_assets_usd)}</strong>
              <small>
                {formatNumber(vault.total_assets)} {vault.asset.symbol || ''}
              </small>
            </div>
            <div className="metric-box">
              <span className="metric-label">Liquidity Buffer</span>
              <strong>{formatSmartUsd(vault.liquidity_usd)}</strong>
              <small>由 allocation 与 cap 推导</small>
            </div>
            <div className="metric-box">
              <span className="metric-label">Net APY</span>
              <button
                type="button"
                className="morpho-vault-apy-trigger"
                data-tooltip={netApyTooltip}
                aria-label={netApyTooltip}
              >
                <strong>{formatPercent(vault.net_apy)}</strong>
              </button>
              <small>Gross APY {formatPercent(vault.apy)}</small>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function MorphoVaultAllocationChart({
  vault,
  selectedMarketId,
  onMarketSelect,
}: {
  vault: MorphoVaultResponse;
  selectedMarketId: string;
  onMarketSelect: (marketId: string) => void;
}) {
  const bars = useMemo(() => createAllocationBars(vault.allocations), [vault.allocations]);
  const totalTvl = useMemo(() => bars.reduce((sum, item) => sum + item.supplyUsd, 0), [bars]);
  const legendItems = useMemo(() => createAllocationLegendItems(bars, totalTvl), [bars, totalTvl]);
  const selectedAllocationIndex = legendItems.findIndex(
    (item) => item.marketId === selectedMarketId,
  );
  const [hoveredAllocationIndex, setHoveredAllocationIndex] = useState<number | null>(null);
  const activeAllocationIndex =
    hoveredAllocationIndex ?? (selectedAllocationIndex >= 0 ? selectedAllocationIndex : 0);
  const activeAllocation = legendItems[activeAllocationIndex] ?? legendItems[0] ?? null;
  const highlightedMarketId = activeAllocation?.marketId ?? selectedMarketId;
  const idleShare = useMemo(
    () => legendItems.filter((item) => item.isIdle).reduce((sum, item) => sum + item.share, 0),
    [legendItems],
  );
  const largestShare = legendItems[0]?.share ?? 0;

  useEffect(() => {
    setHoveredAllocationIndex(null);
  }, [vault.address, legendItems.length]);

  return (
    <section className="card morpho-detail-card morpho-vault-allocation-card">
      <div className="card-header">
        <div>
          <span className="card-title morpho-section-title">Allocation</span>
          <p className="morpho-section-subtitle">
            按 vault 当前市场分配顺序展示，点击市场标签查询 market state。
          </p>
        </div>
        <div className="morpho-vault-insight-strip">
          <span>{legendItems.length} 个分配</span>
          <span>最大仓位 {percentFormatter.format(largestShare * 100)}%</span>
          <span>Idle {percentFormatter.format(idleShare * 100)}%</span>
        </div>
      </div>
      <div className="morpho-vault-allocation-layout">
        <div className="morpho-vault-pie-panel">
          {legendItems.length > 0 ? (
            <div className="morpho-vault-pie-layout">
              <div className="morpho-vault-pie">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
                    <Pie
                      data={legendItems}
                      dataKey="supplyUsd"
                      nameKey="label"
                      cx="50%"
                      cy="50%"
                      innerRadius="76%"
                      outerRadius="88%"
                      startAngle={90}
                      endAngle={-270}
                      paddingAngle={1.6}
                      cornerRadius={5}
                      labelLine={false}
                      isAnimationActive={false}
                      onClick={(item) => {
                        const payload = item.payload as AllocationHistogramItem | undefined;
                        if (payload?.marketId) onMarketSelect(payload.marketId);
                      }}
                      onMouseEnter={(_, index) => setHoveredAllocationIndex(index)}
                      onMouseLeave={() => setHoveredAllocationIndex(null)}
                    >
                      {legendItems.map((item, index) => (
                        <Cell
                          key={item.marketId}
                          fill={item.color}
                          stroke="rgba(8, 15, 29, 0.82)"
                          strokeWidth={2}
                          opacity={activeAllocationIndex === index ? 1 : 0.7}
                          className="morpho-vault-pie-slice"
                        />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(value) => [formatUsd(String(value)), '分配资产']}
                      labelFormatter={(label) => String(label)}
                      contentStyle={vaultTooltipContentStyle}
                      labelStyle={vaultTooltipLabelStyle}
                      itemStyle={{ color: '#e2e8f0' }}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="morpho-vault-pie-center">
                  <span>{activeAllocation ? 'Selected %' : 'Total TVL'}</span>
                  <strong>
                    {activeAllocation
                      ? `${percentFormatter.format(activeAllocation.share * 100)}%`
                      : formatCompactUsd(String(totalTvl))}
                  </strong>
                  {activeAllocation ? (
                    <small>{formatCompactUsd(String(activeAllocation.supplyUsd))}</small>
                  ) : null}
                </div>
              </div>
              <div className="morpho-vault-allocation-list">
                {legendItems.map((item, index) => (
                  <button
                    type="button"
                    key={item.marketId}
                    className={
                      item.marketId === selectedMarketId
                        ? 'morpho-vault-allocation-item morpho-vault-allocation-item-active morpho-vault-allocation-item-selected'
                        : activeAllocationIndex === index
                          ? 'morpho-vault-allocation-item morpho-vault-allocation-item-active'
                          : 'morpho-vault-allocation-item'
                    }
                    onClick={() => onMarketSelect(item.marketId)}
                    onMouseEnter={() => setHoveredAllocationIndex(index)}
                    onMouseLeave={() => setHoveredAllocationIndex(null)}
                    title={item.marketId}
                  >
                    <span
                      className="morpho-vault-allocation-swatch"
                      style={{ background: item.color }}
                    />
                    <span className="morpho-vault-allocation-name">{item.label}</span>
                    <span className="morpho-vault-allocation-value">
                      {formatCompactUsd(String(item.supplyUsd))}
                    </span>
                    <span className="morpho-vault-allocation-share">
                      {percentFormatter.format(item.share * 100)}%
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="morpho-vault-empty-chart">
              <strong>暂无分配数据</strong>
              <span>该 vault 当前没有可展示的 supply allocation。</span>
            </div>
          )}
        </div>

        <div className="morpho-vault-allocation-chart">
          <div className="morpho-vault-chart-legend">
            <span>
              <i className="morpho-vault-legend-cap" />
              Cap
            </span>
            <span>
              <i className="morpho-vault-legend-allocation" />
              Quota
            </span>
            <span>
              <i className="morpho-vault-legend-liquidity" />
              Liquidity
            </span>
          </div>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={bars}
              barGap={0}
              margin={{ top: 12, right: 10, bottom: 84, left: 6 }}
              className="morpho-vault-clickable-chart"
              onClick={(event) => {
                const activeEvent = event as unknown as {
                  activePayload?: Array<{ payload?: AllocationHistogramItem }>;
                };
                const payload = activeEvent.activePayload?.[0]?.payload;
                if (payload?.marketId) onMarketSelect(payload.marketId);
              }}
            >
              <CartesianGrid
                vertical={false}
                stroke="rgba(148, 163, 184, 1)"
                strokeOpacity={0.05}
              />
              <XAxis
                dataKey="displayName"
                height={62}
                interval={0}
                tickLine={false}
                tick={(props) => (
                  <AllocationAxisTick
                    {...props}
                    items={bars}
                    selectedMarketId={highlightedMarketId}
                    onMarketSelect={onMarketSelect}
                  />
                )}
                stroke="rgba(148, 163, 184, 0.42)"
              />
              <YAxis
                domain={[0, 'auto']}
                tickCount={5}
                allowDecimals={false}
                tickFormatter={formatAxisUsd}
                tick={{ fill: '#94a3b8', fontSize: 11, fontWeight: 700 }}
                axisLine={false}
                tickLine={false}
                width={44}
              />
              <Tooltip
                formatter={(_, name, item) => {
                  const payload = item.payload as AllocationHistogramItem | undefined;
                  if (!payload) return ['N/A', String(name)];
                  return [
                    [
                      `Quota ${formatUsd(String(payload.quotaUsd))}`,
                      payload.isIdle
                        ? 'Cap Idle'
                        : `Cap ${formatUsd(String(payload.supplyCapUsd))}`,
                      `Liquidity ${formatUsd(String(payload.liquidityUsd))}`,
                    ].join(' / '),
                    'Market',
                  ];
                }}
                labelFormatter={(_, items) => {
                  const payload = items?.[0]?.payload as AllocationHistogramItem | undefined;
                  return payload ? `${payload.label} · ${payload.shortId}` : '';
                }}
                contentStyle={vaultTooltipContentStyle}
                labelStyle={vaultTooltipLabelStyle}
                itemStyle={{ color: '#e2e8f0' }}
                cursor={{ fill: 'rgba(15, 23, 42, 0.42)' }}
              />
              <Bar
                dataKey="allocation"
                fill="#3b82f6"
                barSize={24}
                stackId="quota-stack"
                radius={[2, 2, 0, 0]}
                isAnimationActive={false}
              >
                {bars.map((item) => (
                  <Cell
                    key={`allocation-${item.marketId}`}
                    fill={item.marketId === highlightedMarketId ? '#60a5fa' : '#3b82f6'}
                    fillOpacity={item.marketId === highlightedMarketId ? 1 : 0.45}
                  />
                ))}
              </Bar>
              <Bar
                dataKey="capGap"
                fill="transparent"
                barSize={24}
                stackId="quota-stack"
                shape={<AllocationCapLine highlightedMarketId={highlightedMarketId} />}
                legendType="none"
                isAnimationActive={false}
              />
              <Bar
                dataKey="liquidity"
                barSize={4}
                radius={[1, 1, 0, 0]}
                shape={<AllocationLiquidityShape />}
                isAnimationActive={false}
              >
                {bars.map((item) => (
                  <Cell
                    key={`liquidity-${item.marketId}`}
                    fill="#10b981"
                    fillOpacity={item.marketId === highlightedMarketId ? 1 : 0.55}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </section>
  );
}

function MorphoVaultReallocationChart({ points }: { points: MorphoVaultReallocationPoint[] }) {
  const maxCount = Math.max(1, ...points.map((point) => point.reallocation_count));

  return (
    <section className="card morpho-detail-card morpho-vault-reallocation-card">
      <div className="card-header">
        <div>
          <span className="card-title morpho-section-title">重分配次数</span>
          <p className="morpho-section-subtitle">
            预留后端接口，后续展示每天 vault reallocation 次数。
          </p>
        </div>
      </div>
      {points.length > 0 ? (
        <div className="morpho-vault-reallocation-bars">
          {points.map((point) => (
            <div className="morpho-vault-reallocation-item" key={point.date}>
              <span
                style={{ height: `${Math.max(6, (point.reallocation_count / maxCount) * 100)}%` }}
              />
              <small>{point.date.slice(5)}</small>
            </div>
          ))}
        </div>
      ) : (
        <div className="morpho-vault-empty-chart">
          <strong>等待后端接入</strong>
          <span>接口预留：/api/morpho/vault/reallocations</span>
        </div>
      )}
    </section>
  );
}

export function MorphoVaultPage({
  selectedMarketId,
  onMarketSelect,
  queryMarkets,
  expandedMarketId,
  onToggleMarket,
  marketStateLoadingById,
  marketStateErrorById,
  sortMode,
  onSortModeChange,
}: MorphoVaultPageProps) {
  const [vaultAddress, setVaultAddress] = useState(MORPHO_VAULT_SAMPLE_ADDRESS);
  const [vault, setVault] = useState<MorphoVaultResponse | null>(null);
  const [reallocationPoints, setReallocationPoints] = useState<MorphoVaultReallocationPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadVaultForAddress = useCallback(
    async (address: string, force = false) => {
      const normalizedAddress = address.trim();
      setError('');

      if (!isAddress(normalizedAddress, { strict: false })) {
        setError('请输入有效的 Morpho vault 地址');
        return;
      }

      setLoading(true);
      try {
        const [vaultData, reallocationData] = await Promise.all([
          fetchMorphoVault(normalizedAddress, { force }),
          fetchMorphoVaultReallocations(normalizedAddress, { force }),
        ]);
        setVault(vaultData);
        setReallocationPoints(reallocationData.points);
        const firstMarketId = vaultData.allocations.find(
          (allocation) => allocation.market_id,
        )?.market_id;
        if (firstMarketId) {
          onMarketSelect(firstMarketId);
        }
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : '无法加载 Morpho vault 数据');
      } finally {
        setLoading(false);
      }
    },
    [onMarketSelect],
  );

  const loadVault = useCallback(
    async (force = false) => {
      await loadVaultForAddress(vaultAddress, force);
    },
    [loadVaultForAddress, vaultAddress],
  );

  useEffect(() => {
    void loadVaultForAddress(MORPHO_VAULT_SAMPLE_ADDRESS, false);
  }, [loadVaultForAddress]);

  return (
    <div className="morpho-vault-page">
      <section className="card morpho-detail-card morpho-vault-search-card">
        <div className="card-header">
          <div>
            <span className="card-title morpho-section-title">Vault 搜索</span>
            <p className="morpho-section-subtitle">输入 Morpho vault 地址查询实时详情。</p>
          </div>
        </div>
        <div className="morpho-vault-search-row">
          <input
            className="address-input"
            value={vaultAddress}
            onChange={(event) => {
              setVaultAddress(event.target.value);
              setError('');
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void loadVault(true);
            }}
            placeholder="输入 Morpho vault 地址"
          />
          <button type="button" className="switch-btn" onClick={() => void loadVault(true)}>
            查询
          </button>
        </div>
        {error ? <div className="protocol-banner protocol-banner-warn">{error}</div> : null}
      </section>

      {loading ? (
        <div className="card morpho-market-loading-card">
          <div className="spinner"></div>
        </div>
      ) : null}

      {vault ? (
        <>
          <MorphoVaultOverview vault={vault} />
          <MorphoVaultAllocationChart
            vault={vault}
            selectedMarketId={selectedMarketId}
            onMarketSelect={onMarketSelect}
          />
          {selectedMarketId ? (
            <MorphoMarketTable
              markets={queryMarkets}
              expandedMarketId={expandedMarketId}
              onToggleMarket={onToggleMarket}
              marketStateLoadingById={marketStateLoadingById}
              marketStateErrorById={marketStateErrorById}
              title="市场查询结果"
              subtitle={`来自 Vault allocation: ${compactMarketId(selectedMarketId)}`}
              sortMode={sortMode}
              onSortModeChange={onSortModeChange}
              totalMarkets={queryMarkets.length}
              page={1}
              totalPages={1}
              pageSize={Math.max(queryMarkets.length, 1)}
              onPageChange={() => undefined}
              showSorting={false}
              showPagination={false}
              showTableHeaderWhenEmpty={false}
              emptyText="正在等待该市场的 state 详情。"
            />
          ) : (
            <section className="card morpho-detail-card morpho-vault-market-placeholder">
              <strong>市场查询结果</strong>
              <span>点击 allocation 图底部市场标签后，将在这里查询并展示 market state。</span>
            </section>
          )}
          <MorphoVaultReallocationChart points={reallocationPoints} />
        </>
      ) : null}
    </div>
  );
}
