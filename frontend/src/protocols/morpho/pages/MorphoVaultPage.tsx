import { useCallback, useEffect, useMemo, useState, type MouseEvent } from 'react';
import { isAddress } from 'viem';
import {
  Bar,
  BarChart,
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
      const supplyUsd = parseNumber(allocation.supply_assets_usd) ?? 0;
      const supplyCapUsdRaw = parseNumber(allocation.supply_cap_usd);
      const isIdle = !allocation.collateral_symbol;
      const supplyCapUsd =
        !isIdle && supplyCapUsdRaw !== null && supplyCapUsdRaw < 1e30 ? supplyCapUsdRaw : null;
      const liquidityUsd = parseNumber(allocation.liquidity_usd) ?? 0;
      const histogramMaxUsd = Math.max(supplyUsd, liquidityUsd, supplyCapUsd ?? 0);

      return {
        marketId: allocation.market_id,
        label: resolveAllocationLabel(allocation),
        displayName: resolveAllocationDisplayName(allocation),
        shortId: compactMarketId(allocation.market_id),
        supplyUsd,
        supplyCapUsd,
        liquidityUsd,
        histogramMaxUsd,
        isIdle,
        hasLiquidityWarning: liquidityUsd < supplyUsd,
        allocation,
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
  return `$${compactUsdFormatter.format(value).replace('$', '')}`;
}

type AllocationHistogramItem = ReturnType<typeof createAllocationBars>[number];

interface AllocationHistogramShapeProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: AllocationHistogramItem;
  selectedMarketId?: string;
}

function AllocationHistogramColumn({
  x = 0,
  y = 0,
  width = 0,
  height = 0,
  payload,
  selectedMarketId = '',
}: AllocationHistogramShapeProps) {
  if (!payload || width <= 0 || height <= 0 || payload.histogramMaxUsd <= 0) return null;

  const isSelected = payload.marketId === selectedMarketId;
  const bottom = y + height;
  const allocationWidth = Math.min(20, Math.max(6, width * 0.48));
  const liquidityWidth = Math.min(8, Math.max(3, width * 0.18));
  const barGap = Math.min(5, Math.max(2, width * 0.08));
  const groupWidth = allocationWidth + barGap + liquidityWidth;
  const groupX = x + (width - groupWidth) / 2;
  const allocationX = groupX;
  const liquidityX = groupX + allocationWidth + barGap;
  const toHeight = (value: number | null) =>
    value === null ? 0 : Math.max(value > 0 ? 3 : 0, (value / payload.histogramMaxUsd) * height);
  const capHeight = payload.isIdle ? 0 : toHeight(payload.supplyCapUsd);
  const allocationHeight = toHeight(payload.supplyUsd);
  const liquidityHeight = toHeight(payload.liquidityUsd);
  const barTop = bottom - Math.max(allocationHeight, liquidityHeight);
  const triangleX = groupX + groupWidth / 2;
  const triangleY = Math.max(y + 6, barTop - 12);

  return (
    <g
      className={
        [
          'morpho-vault-histogram-column',
          payload.hasLiquidityWarning ? 'morpho-vault-histogram-column-warning' : '',
          isSelected ? 'morpho-vault-histogram-column-selected' : '',
        ]
          .filter(Boolean)
          .join(' ') || undefined
      }
    >
      {isSelected ? (
        <rect
          x={groupX - 5}
          y={y}
          width={groupWidth + 10}
          height={height}
          rx={7}
          fill="rgba(125, 211, 252, 0.07)"
          className="morpho-vault-histogram-selected-frame"
        />
      ) : null}
      {capHeight > 0 ? (
        <line
          x1={groupX - 5}
          y1={bottom - capHeight}
          x2={groupX + groupWidth + 5}
          y2={bottom - capHeight}
          stroke="rgba(226, 232, 240, 0.46)"
          strokeWidth={2}
          strokeLinecap="round"
        />
      ) : null}
      {allocationHeight > 0 ? (
        <rect
          x={allocationX}
          y={bottom - allocationHeight}
          width={allocationWidth}
          height={allocationHeight}
          rx={4}
          fill={isSelected ? '#7dd3fc' : '#38bdf8'}
          fillOpacity={0.82}
        />
      ) : null}
      {liquidityHeight > 0 ? (
        <rect
          x={liquidityX}
          y={bottom - liquidityHeight}
          width={liquidityWidth}
          height={liquidityHeight}
          rx={3}
          fill="#86efac"
          className="morpho-vault-histogram-liquidity"
        />
      ) : null}
      {payload.hasLiquidityWarning ? (
        <path
          d={`M${triangleX},${triangleY} L${triangleX - 5},${triangleY + 9} L${triangleX + 5},${triangleY + 9} Z`}
          className="morpho-vault-histogram-risk-triangle"
        />
      ) : null}
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
  const shouldShowLabel =
    isSelected || items.length <= 8 || index % Math.ceil(items.length / 8) === 0;

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
      {shouldShowLabel ? (
        <text x={0} y={0} dy={18} textAnchor="middle">
          {payload?.value ?? item.displayName}
        </text>
      ) : (
        <circle cx={0} cy={16} r={2.2} />
      )}
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

  return (
    <section className="card morpho-detail-card morpho-vault-overview-card">
      <div className="morpho-vault-detail-layout">
        <div className="morpho-vault-detail-main">
          <div className="morpho-vault-identity">
            <div>
              <span className="morpho-vault-kicker">Vault</span>
              <h2>{vault.name || vault.symbol || 'Morpho Vault'}</h2>
              <MorphoVaultCopyLine
                label="Vault 地址"
                value={vault.address}
                copied={copied}
                onCopy={copy}
              />
            </div>
            <span className="morpho-vault-version">V2</span>
          </div>

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
              <strong>{formatUsd(vault.total_assets_usd)}</strong>
              <small>
                {formatNumber(vault.total_assets)} {vault.asset.symbol || ''}
              </small>
            </div>
            <div className="metric-box">
              <span className="metric-label">Liquidity</span>
              <strong>{formatUsd(vault.liquidity_usd)}</strong>
              <small>由 supply cap 与已分配资产推导</small>
            </div>
            <div className="metric-box">
              <span className="metric-label">Net APY</span>
              <strong>{formatPercent(vault.net_apy)}</strong>
              <small>APY {formatPercent(vault.apy)}</small>
            </div>
          </div>
        </div>
      </div>

      <div className="morpho-vault-sub-metrics">
        <span>fee {formatPercent(vault.fee)}</span>
        <span>timelock {formatDays(vault.timelock_days)}</span>
        <span>net APY excl. rewards {formatPercent(vault.net_apy_excluding_rewards)}</span>
        <span>avg net APY {formatPercent(vault.avg_net_apy)}</span>
        <span>avg net APY excl. rewards {formatPercent(vault.avg_net_apy_excluding_rewards)}</span>
        <span>{vault.data_source === 'mock' ? 'mock: frontend/openapi.json' : 'api'}</span>
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
                      innerRadius="66%"
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
                  <span>{activeAllocation ? 'Selected' : 'Total TVL'}</span>
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
              Supply Cap
            </span>
            <span>
              <i className="morpho-vault-legend-allocation" />
              Allocation
            </span>
            <span>
              <i className="morpho-vault-legend-liquidity" />
              Market Liquidity
            </span>
            <span>
              <i className="morpho-vault-legend-warning" />
              Liquidity &lt; Allocation
            </span>
          </div>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={bars}
              margin={{ top: 10, right: 4, bottom: 0, left: 0 }}
              onClick={(event) => {
                const activeEvent = event as unknown as {
                  activePayload?: Array<{ payload?: AllocationHistogramItem }>;
                };
                const payload = activeEvent.activePayload?.[0]?.payload;
                if (payload?.marketId) onMarketSelect(payload.marketId);
              }}
            >
              <XAxis
                dataKey="displayName"
                height={42}
                interval={0}
                tickLine={false}
                tick={(props) => (
                  <AllocationAxisTick
                    {...props}
                    items={bars}
                    selectedMarketId={selectedMarketId}
                    onMarketSelect={onMarketSelect}
                  />
                )}
                stroke="rgba(148, 163, 184, 0.42)"
              />
              <YAxis
                tickFormatter={formatAxisUsd}
                tick={{ fill: '#94a3b8', fontSize: 11, fontWeight: 700 }}
                axisLine={false}
                tickLine={false}
                width={52}
              />
              <Tooltip
                formatter={(_, name, item) => {
                  const payload = item.payload as AllocationHistogramItem | undefined;
                  if (!payload) return ['N/A', String(name)];
                  return [
                    [
                      `Allocation ${formatUsd(String(payload.supplyUsd))}`,
                      payload.isIdle
                        ? 'Supply Cap Idle'
                        : `Supply Cap ${formatUsd(String(payload.supplyCapUsd))}`,
                      `Liquidity ${formatUsd(String(payload.liquidityUsd))}`,
                    ].join(' / '),
                    payload.hasLiquidityWarning ? 'Liquidity Warning' : 'Market Column',
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
                dataKey="histogramMaxUsd"
                shape={<AllocationHistogramColumn selectedMarketId={selectedMarketId} />}
                barSize={34}
                isAnimationActive={false}
              />
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
        <div>
          <span className="card-title morpho-section-title">Vault 搜索</span>
          <p className="morpho-section-subtitle">
            输入 Morpho vault 地址查询详情；后端未接入时使用 frontend/openapi.json 样例。
          </p>
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
