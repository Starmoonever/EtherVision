import { useCallback, useEffect, useMemo, useState, type MouseEvent, type ReactNode } from 'react';
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
  fetchMorphoVaultWithMeta,
  fetchMorphoVaultV2WithMeta,
  MORPHO_VAULT_SAMPLE_ADDRESS,
  MORPHO_VAULT_V2_SAMPLE_ADDRESS,
  type MorphoVaultAllocation,
  type MorphoVaultResponse,
  type MorphoVaultV2Gate,
  type MorphoVaultV2Response,
} from '../../../api/morpho';
import { copyToClipboard } from '../../../shared/utils/copyToClipboard';
import type { MorphoMarketView } from '../../../hooks/useMorphoData';
import { SegmentedControl } from '../../../shared/components/SegmentedControl';
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

type MorphoVaultVersion = 'v1' | 'v2';

const usdFormatter = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 2,
});

const numberFormatter = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 4,
});

const percentFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const ALLOCATION_COLORS = [
  '#60a5fa',
  '#4ade80',
  '#fb923c',
  '#f472b6',
  '#2dd4bf',
  '#facc15',
  '#c084fc',
  '#38bdf8',
  '#f87171',
  '#a3e635',
  '#f0abfc',
  '#34d399',
];
const vaultTooltipContentStyle = {
  border: '1px solid rgba(15, 23, 42, 0.92)',
  borderRadius: 8,
  background: 'rgba(2, 6, 23, 0.98)',
  boxShadow: '0 20px 40px rgba(2, 6, 23, 0.52)',
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
  if (numeric === null) return 'N/A';
  const absolute = Math.abs(numeric);
  if (absolute >= 1_000_000_000)
    return `$${(numeric / 1_000_000_000).toFixed(absolute >= 10_000_000_000 ? 0 : 1).replace(/\.0$/, '')}B`;
  if (absolute >= 1_000_000)
    return `$${(numeric / 1_000_000).toFixed(absolute >= 100_000_000 ? 0 : 1).replace(/\.0$/, '')}M`;
  if (absolute >= 1_000)
    return `$${(numeric / 1_000).toFixed(absolute >= 100_000 ? 0 : 1).replace(/\.0$/, '')}K`;
  return `$${usdFormatter.format(numeric)}`;
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

function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'N/A';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
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

function hexToRgba(hex: string, alpha: number): string {
  const normalized = hex.replace('#', '');
  if (!/^[\da-f]{6}$/i.test(normalized)) return hex;
  const red = Number.parseInt(normalized.slice(0, 2), 16);
  const green = Number.parseInt(normalized.slice(2, 4), 16);
  const blue = Number.parseInt(normalized.slice(4, 6), 16);
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function mixHexColor(hex: string, mixWith: string, weight: number): string {
  const normalized = hex.replace('#', '');
  const target = mixWith.replace('#', '');
  if (!/^[\da-f]{6}$/i.test(normalized) || !/^[\da-f]{6}$/i.test(target)) return hex;

  const sourceRgb = [0, 2, 4].map((offset) =>
    Number.parseInt(normalized.slice(offset, offset + 2), 16),
  );
  const targetRgb = [0, 2, 4].map((offset) =>
    Number.parseInt(target.slice(offset, offset + 2), 16),
  );
  const mixed = sourceRgb.map((channel, index) =>
    Math.round(channel * (1 - weight) + targetRgb[index] * weight),
  );
  return `#${mixed.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`;
}

function createLiquidityColor(hex: string): string {
  return mixHexColor(hex, '#ffffff', 0.5);
}

function createLiquidityStrokeColor(hex: string): string {
  return mixHexColor(hex, '#ffffff', 0.68);
}

function createPieActiveStroke(hex: string): string {
  return mixHexColor(hex, '#f8fafc', 0.44);
}

function formatAxisUsd(value: number): string {
  if (value <= 0) return '$0';
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(0)}B`;
  if (value >= 100_000_000) return `$${(value / 1_000_000).toFixed(0)}M`;
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  return formatCompactUsd(String(value));
}

type AllocationHistogramItem = ReturnType<typeof createAllocationLegendItems>[number];

function AllocationTooltipContent({ item }: { item: AllocationHistogramItem | null }) {
  if (!item) return null;

  return (
    <div style={vaultTooltipContentStyle}>
      <div style={vaultTooltipLabelStyle}>{item.label}</div>
      <div className="morpho-vault-chart-tooltip-row">
        <span>分配资产</span>
        <strong>{formatCompactUsd(String(item.quotaUsd))}</strong>
      </div>
      <div className="morpho-vault-chart-tooltip-row">
        <span>流动性</span>
        <strong>{formatCompactUsd(String(item.liquidityUsd))}</strong>
      </div>
      <div className="morpho-vault-chart-tooltip-row">
        <span>市场容量</span>
        <strong>{item.isIdle ? 'Idle' : formatCompactUsd(String(item.supplyCapUsd))}</strong>
      </div>
    </div>
  );
}

function AllocationBarTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: AllocationHistogramItem }>;
}) {
  if (!active || !payload?.length) return null;
  const item = payload.find((entry) => entry.payload?.marketId)?.payload ?? null;
  return <AllocationTooltipContent item={item} />;
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
            <span className="morpho-vault-version">V1</span>
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

function MorphoVaultV2Overview({ vault }: { vault: MorphoVaultV2Response }) {
  const { copied, copy } = useCopiedValue();
  const gateCards: Array<{
    key: string;
    label: string;
    desc: string;
    gate: MorphoVaultV2Gate | null;
  }> = [
    {
      key: 'receive_assets_gate',
      label: '资金存入',
      desc: '任何人是否可以直接存入资产，以及管理员是否仍保留拦截能力。',
      gate: vault.gates_config.receive_assets_gate,
    },
    {
      key: 'send_shares_gate',
      label: '份额赎回',
      desc: '赎回相关指令的门控状态，决定退出路径是否保持开放。',
      gate: vault.gates_config.send_shares_gate,
    },
    {
      key: 'receive_shares_gate',
      label: '份额转让',
      desc: '份额接收与流转是否保持开放，是否仍受管理员门控影响。',
      gate: vault.gates_config.receive_shares_gate,
    },
    {
      key: 'send_assets_gate',
      label: '资产出库',
      desc: '资产发出流程的最后一道门控，常用于极端情况下的合规审计。',
      gate: vault.gates_config.send_assets_gate,
    },
  ];

  return (
    <>
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
          <h2>{vault.name || vault.symbol || 'Morpho Vault V2'}</h2>
          <div className="morpho-vault-hero-summary">
            <p>
              以 {vault.asset.symbol || '底层资产'} 为基底，当前总资产{' '}
              {formatCompactUsd(vault.total_assets_usd)}，净收益 {formatPercent(vault.net_apy)}。
            </p>
            <div className="morpho-vault-tag-row morpho-vault-tag-row-hero">
              <span className="morpho-vault-tag">
                Management Fee {formatPercent(vault.management_fee)}
              </span>
              <span className="morpho-vault-tag">
                Performance Fee {formatPercent(vault.performance_fee)}
              </span>
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
                <span className="metric-label">Total Assets</span>
                <strong>{formatSmartUsd(vault.total_assets_usd)}</strong>
                <small>{formatNumber(vault.total_assets)}</small>
              </div>
              <div className="metric-box">
                <span className="metric-label">Liquidity</span>
                <strong>{formatSmartUsd(vault.liquidity_usd)}</strong>
                <small>{formatNumber(vault.liquidity)}</small>
              </div>
              <div className="metric-box">
                <span className="metric-label">Net APY</span>
                <strong>{formatPercent(vault.net_apy)}</strong>
                <small>APY {formatPercent(vault.apy)}</small>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="card morpho-detail-card morpho-vault-v2-info-card">
        <div className="card-header">
          <div>
            <span className="card-title morpho-section-title">基础信息</span>
            <p className="morpho-section-subtitle">V2 vault 的基础属性与创建信息。</p>
          </div>
        </div>
        <div className="morpho-vault-v2-detail-grid">
          <div className="metric-box">
            <span className="metric-label">Type</span>
            <strong>{vault.type || 'N/A'}</strong>
          </div>
          <div className="metric-box">
            <span className="metric-label">Creation Block</span>
            <strong>{vault.creation_block_number?.toLocaleString('en-US') || 'N/A'}</strong>
          </div>
          <div className="metric-box">
            <span className="metric-label">Creation Time</span>
            <strong>{formatDateTime(vault.creation_timestamp)}</strong>
          </div>
        </div>
      </section>

      <section className="card morpho-detail-card morpho-vault-v2-gates-card">
        <div className="card-header">
          <div>
            <span className="card-title morpho-section-title">Gate Config</span>
            <p className="morpho-section-subtitle">
              展示 V2 vault 四类门控的开放状态、治理保留权与待生效变更。
            </p>
          </div>
        </div>
        <div className="morpho-vault-v2-gates-grid">
          {gateCards.map((item) => {
            const gate = item.gate;
            const isOpen = gate?.address === null;
            const isLocked = gate?.abdicated === true;
            const hasPending = Boolean(
              gate?.pending_address ||
              gate?.pending_executable_at ||
              gate?.pending_abdication_executable_at,
            );

            return (
              <div className="morpho-vault-gate-card" key={item.key}>
                <div className="morpho-vault-gate-card-head">
                  <div>
                    <strong>{item.label}</strong>
                    <p>{item.desc}</p>
                  </div>
                  <div className="morpho-vault-gate-badges">
                    <span
                      className={
                        isOpen
                          ? 'morpho-vault-gate-badge morpho-vault-gate-badge-open'
                          : 'morpho-vault-gate-badge morpho-vault-gate-badge-guarded'
                      }
                    >
                      {isOpen ? 'Open' : 'Guarded'}
                    </span>
                    <span
                      className={
                        isLocked
                          ? 'morpho-vault-gate-badge morpho-vault-gate-badge-locked'
                          : 'morpho-vault-gate-badge morpho-vault-gate-badge-admin'
                      }
                    >
                      {isLocked ? 'Locked' : 'Admin'}
                    </span>
                  </div>
                </div>
                {hasPending ? (
                  <div className="morpho-vault-gate-pending-banner">
                    <strong>检测到待处理门控变更</strong>
                    <span>
                      {gate?.pending_address ? compactAddress(gate.pending_address) : '地址待定'}
                      {gate?.pending_executable_at
                        ? ` · 可执行于 ${formatDateTime(gate.pending_executable_at)}`
                        : gate?.pending_abdication_executable_at
                          ? ` · 待废弃于 ${formatDateTime(gate.pending_abdication_executable_at)}`
                          : ''}
                    </span>
                  </div>
                ) : null}
                <div className="morpho-vault-gate-footer">
                  <span>当前门控地址</span>
                  {gate?.address ? (
                    <MorphoVaultCopyLine
                      label={`${item.label} Gate`}
                      value={gate.address}
                      copied={copied}
                      onCopy={copy}
                    />
                  ) : (
                    <strong>None (Permissionless)</strong>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </>
  );
}

function MorphoVaultAllocationChart({
  vault,
  selectedMarketId,
  onMarketSelect,
  marketQuerySection,
}: {
  vault: MorphoVaultResponse;
  selectedMarketId: string;
  onMarketSelect: (marketId: string) => void;
  marketQuerySection?: ReactNode;
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
  const activeAllocationColor = activeAllocation?.color ?? '#38bdf8';
  const activeLiquidityColor = createLiquidityColor(activeAllocationColor);

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
          <span>最大分配 {percentFormatter.format(largestShare * 100)}%</span>
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
                      innerRadius="65%"
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
                          stroke={
                            activeAllocationIndex === index
                              ? createPieActiveStroke(item.color)
                              : 'rgba(2, 6, 23, 0.96)'
                          }
                          strokeWidth={activeAllocationIndex === index ? 4.4 : 3.2}
                          opacity={1}
                          className={
                            activeAllocationIndex === index
                              ? 'morpho-vault-pie-slice morpho-vault-pie-slice-active'
                              : 'morpho-vault-pie-slice'
                          }
                        />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
                <div className="morpho-vault-pie-center">
                  <span>
                    {activeAllocation ? activeAllocation.displayName : vault.asset.symbol || 'TVL'}
                  </span>
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
              <i
                className="morpho-vault-legend-allocation"
                style={{ background: activeAllocationColor }}
              />
              Allocation
            </span>
            <span>
              <i
                className="morpho-vault-legend-liquidity"
                style={{ background: activeLiquidityColor }}
              />
              Liquidity
            </span>
          </div>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={legendItems}
              barGap={0}
              margin={{ top: 12, right: 10, bottom: 84, left: 6 }}
              className="morpho-vault-clickable-chart"
              onMouseMove={(event) => {
                const activeEvent = event as unknown as {
                  activePayload?: Array<{ payload?: AllocationHistogramItem }>;
                };
                const payload = activeEvent.activePayload?.[0]?.payload;
                if (!payload?.marketId) return;
                const index = legendItems.findIndex((item) => item.marketId === payload.marketId);
                if (index >= 0) setHoveredAllocationIndex(index);
              }}
              onMouseLeave={() => setHoveredAllocationIndex(null)}
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
                    items={legendItems}
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
                content={<AllocationBarTooltip />}
                cursor={{ fill: 'rgba(15, 23, 42, 0.42)' }}
              />
              <Bar
                dataKey="allocation"
                barSize={24}
                stackId="quota-stack"
                radius={[2, 2, 0, 0]}
                isAnimationActive={false}
              >
                {legendItems.map((item) => (
                  <Cell
                    key={`allocation-${item.marketId}`}
                    fill={item.color}
                    fillOpacity={1}
                    stroke={
                      item.marketId === highlightedMarketId ? hexToRgba(item.color, 0.95) : 'none'
                    }
                    strokeWidth={item.marketId === highlightedMarketId ? 2 : 0}
                    className={
                      item.marketId === highlightedMarketId
                        ? 'morpho-vault-bar-cell morpho-vault-bar-cell-active'
                        : 'morpho-vault-bar-cell'
                    }
                  />
                ))}
              </Bar>
              <Bar
                dataKey="liquidity"
                barSize={24}
                radius={[2, 2, 0, 0]}
                shape={<AllocationLiquidityShape />}
                isAnimationActive={false}
              >
                {legendItems.map((item) => (
                  <Cell
                    key={`liquidity-${item.marketId}`}
                    fill={createLiquidityColor(item.color)}
                    fillOpacity={1}
                    stroke={createLiquidityStrokeColor(item.color)}
                    strokeWidth={item.marketId === highlightedMarketId ? 2 : 1}
                    className={
                      item.marketId === highlightedMarketId
                        ? 'morpho-vault-bar-cell morpho-vault-bar-cell-active'
                        : 'morpho-vault-bar-cell'
                    }
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      {marketQuerySection ? (
        <div className="morpho-vault-allocation-market-section">{marketQuerySection}</div>
      ) : null}
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
  const [vaultVersion, setVaultVersion] = useState<MorphoVaultVersion>('v1');
  const [vaultAddressByVersion, setVaultAddressByVersion] = useState<
    Record<MorphoVaultVersion, string>
  >({
    v1: MORPHO_VAULT_SAMPLE_ADDRESS,
    v2: MORPHO_VAULT_V2_SAMPLE_ADDRESS,
  });
  const [vaultAddress, setVaultAddress] = useState(MORPHO_VAULT_SAMPLE_ADDRESS);
  const [vault, setVault] = useState<MorphoVaultResponse | null>(null);
  const [vaultV2, setVaultV2] = useState<MorphoVaultV2Response | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [vaultFetchedAt, setVaultFetchedAt] = useState<number | null>(null);
  const [vaultFromCache, setVaultFromCache] = useState(false);
  const activeVaultAddress = vaultAddressByVersion[vaultVersion];

  const loadVaultForAddress = useCallback(
    async (address: string, force = false, version: MorphoVaultVersion = vaultVersion) => {
      const normalizedAddress = address.trim();
      setError('');

      if (!isAddress(normalizedAddress, { strict: false })) {
        setError('请输入有效的 Morpho vault 地址');
        return;
      }

      setLoading(true);
      try {
        setVaultAddressByVersion((current) => ({
          ...current,
          [version]: normalizedAddress,
        }));

        if (version === 'v2') {
          setVault(null);
          const result = await fetchMorphoVaultV2WithMeta(normalizedAddress, { force });
          setVaultV2(result.data);
          setVaultFetchedAt(result.meta.fetchedAt);
          setVaultFromCache(result.meta.fromCache);
        } else {
          setVaultV2(null);
          const result = await fetchMorphoVaultWithMeta(normalizedAddress, { force });
          setVault(result.data);
          setVaultFetchedAt(result.meta.fetchedAt);
          setVaultFromCache(result.meta.fromCache);
          const firstMarketId = result.data.allocations.find(
            (allocation) => allocation.market_id,
          )?.market_id;
          if (firstMarketId) {
            onMarketSelect(firstMarketId);
          }
        }
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : '无法加载 Morpho vault 数据');
      } finally {
        setLoading(false);
      }
    },
    [onMarketSelect, vaultVersion],
  );

  const loadVault = useCallback(
    async (force = false) => {
      await loadVaultForAddress(vaultAddress, force, vaultVersion);
    },
    [loadVaultForAddress, vaultAddress, vaultVersion],
  );

  const refreshedAtText = vaultFetchedAt
    ? new Date(vaultFetchedAt).toLocaleString('zh-CN', {
        hour12: false,
      })
    : 'N/A';

  useEffect(() => {
    setVaultAddress(activeVaultAddress);
    void loadVaultForAddress(activeVaultAddress, false, vaultVersion);
  }, [activeVaultAddress, loadVaultForAddress, vaultVersion]);

  return (
    <div className="morpho-vault-page">
      <section className="card morpho-detail-card morpho-vault-search-card">
        <div className="card-header">
          <div>
            <span className="card-title morpho-section-title">Vault 搜索</span>
            <p className="morpho-section-subtitle">
              输入 Morpho vault 地址查询实时详情，并在 V1 / V2 间切换查看不同接口。
            </p>
          </div>
          <div className="morpho-vault-version-switch">
            <SegmentedControl
              ariaLabel="Morpho vault 版本"
              value={vaultVersion}
              onChange={(value) => setVaultVersion(value as MorphoVaultVersion)}
              options={[
                { value: 'v1', label: 'Vault V1', activeClassName: 'active-purple' },
                { value: 'v2', label: 'Vault V2', activeClassName: 'active-purple' },
              ]}
            />
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

      {(vaultVersion === 'v1' ? vault !== null : vaultV2 !== null) ? (
        <div className="card morpho-detail-card morpho-market-toolbar">
          <div className="morpho-market-toolbar-copy">
            <strong>数据状态</strong>
            <span>
              最近更新 {refreshedAtText} {vaultFromCache ? '· 缓存命中' : '· 实时拉取'}
            </span>
          </div>
          <div className="morpho-market-toolbar-actions">
            <button type="button" className="switch-btn" onClick={() => void loadVault(true)}>
              刷新数据
            </button>
          </div>
        </div>
      ) : null}

      {vaultVersion === 'v2' && vaultV2 ? <MorphoVaultV2Overview vault={vaultV2} /> : null}

      {vaultVersion === 'v1' && vault ? (
        <>
          <MorphoVaultOverview vault={vault} />
          <MorphoVaultAllocationChart
            vault={vault}
            selectedMarketId={selectedMarketId}
            onMarketSelect={onMarketSelect}
            marketQuerySection={
              selectedMarketId ? (
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
                  embedded
                  forceExpanded
                />
              ) : (
                <section className="morpho-vault-market-placeholder morpho-vault-market-placeholder-embedded">
                  <strong>市场查询结果</strong>
                  <span>点击 allocation 图表中的市场后，会在这里直接展示对应 market state。</span>
                </section>
              )
            }
          />
        </>
      ) : null}
    </div>
  );
}
