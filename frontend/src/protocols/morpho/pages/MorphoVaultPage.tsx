import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type MouseEvent,
  type ReactNode,
} from 'react';
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
  fetchMorphoVaultsWithMeta,
  fetchMorphoVaultWithMeta,
  fetchMorphoVaultV2WithMeta,
  MORPHO_VAULT_SAMPLE_ADDRESS,
  MORPHO_VAULT_V2_SAMPLE_ADDRESS,
  type MorphoVaultsItem,
  type MorphoVaultsProtocol,
  type MorphoVaultsSortField,
  type MorphoVaultsSortOrder,
  type MorphoVaultAllocation,
  type MorphoVaultResponse,
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
type MorphoVaultProtocolFilter = 'all' | MorphoVaultsProtocol;
type MorphoVaultViewMode = 'list' | 'query';

interface ExpandedVaultDetailState {
  key: string;
  loading: boolean;
  error: string;
  vault: MorphoVaultResponse | null;
  vaultV2: MorphoVaultV2Response | null;
}

interface AdapterVaultV1DetailState {
  address: string;
  loading: boolean;
  error: string;
  vault: MorphoVaultResponse | null;
}

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
const LIQUIDITY_BAR_RADIUS = 5;
const MORPHO_VAULT_HISTORY_STORAGE_KEY = 'morpho_vault_search_history_by_version';
const MORPHO_VAULT_LEGACY_HISTORY_STORAGE_KEY = 'morpho_vault_search_history';
const MORPHO_VAULT_HISTORY_LIMIT = 30;
const MORPHO_VAULTS_PAGE_SIZE = 10;

type MorphoVaultSearchHistoryByVersion = Record<MorphoVaultVersion, string[]>;

function emptyMorphoVaultSearchHistory(): MorphoVaultSearchHistoryByVersion {
  return { v1: [], v2: [] };
}

function normalizeVaultHistoryList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, MORPHO_VAULT_HISTORY_LIMIT);
}

function loadMorphoVaultSearchHistory(): MorphoVaultSearchHistoryByVersion {
  try {
    const stored = localStorage.getItem(MORPHO_VAULT_HISTORY_STORAGE_KEY);
    if (!stored) {
      const legacy = normalizeVaultHistoryList(
        JSON.parse(localStorage.getItem(MORPHO_VAULT_LEGACY_HISTORY_STORAGE_KEY) ?? '[]'),
      );
      return { v1: legacy, v2: [] };
    }
    const parsed = JSON.parse(stored) as unknown;
    if (!parsed || typeof parsed !== 'object') return emptyMorphoVaultSearchHistory();
    const record = parsed as Partial<Record<MorphoVaultVersion, unknown>>;
    return {
      v1: normalizeVaultHistoryList(record.v1),
      v2: normalizeVaultHistoryList(record.v2),
    };
  } catch {
    return emptyMorphoVaultSearchHistory();
  }
}

function saveMorphoVaultSearchHistory(history: MorphoVaultSearchHistoryByVersion): void {
  try {
    localStorage.setItem(
      MORPHO_VAULT_HISTORY_STORAGE_KEY,
      JSON.stringify({
        v1: history.v1.slice(0, MORPHO_VAULT_HISTORY_LIMIT),
        v2: history.v2.slice(0, MORPHO_VAULT_HISTORY_LIMIT),
      }),
    );
  } catch {
    // localStorage may be unavailable or full; vault search should still work.
  }
}

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

function buildVaultV2NetApyTooltip(vault: MorphoVaultV2Response): string {
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

function isMorphoMarketId(value: string): boolean {
  return /^0x[a-fA-F0-9]{64}$/.test(value.trim());
}

function resolveMarketPairLabel(
  collateralSymbol: string | null | undefined,
  loanSymbol: string | null | undefined,
  fallbackMarketId: string,
): string {
  if (collateralSymbol && loanSymbol) return `${collateralSymbol} / ${loanSymbol}`;
  if (loanSymbol) return loanSymbol;
  if (collateralSymbol) return collateralSymbol;
  return compactMarketId(fallbackMarketId);
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
  return mixHexColor(hex, '#ffffff', 0.38);
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

interface VaultV2AdapterChartItem {
  key: string;
  label: string;
  displayName: string;
  amountUsd: number;
  share: number;
  color: string;
  targetType: 'vault-v1' | 'market' | null;
  targetId: string | null;
  dataSource: string | null;
}

function AllocationTooltipContent({ item }: { item: AllocationHistogramItem | null }) {
  if (!item) return null;

  return (
    <div className="morpho-market-chart-tooltip">
      <div className="morpho-market-chart-tooltip-title">
        <span style={{ background: item.color }} />
        <strong>{item.label}</strong>
      </div>
      <div className="morpho-market-chart-tooltip-row">
        <span>分配资产</span>
        <strong>{formatCompactUsd(String(item.quotaUsd))}</strong>
      </div>
      <div className="morpho-market-chart-tooltip-row">
        <span>流动性</span>
        <strong>{formatCompactUsd(String(item.liquidityUsd))}</strong>
      </div>
      <div className="morpho-market-chart-tooltip-row">
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

function VaultV2AdapterTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: VaultV2AdapterChartItem }>;
}) {
  if (!active || !payload?.length) return null;
  const item = payload.find((entry) => entry.payload?.key)?.payload;
  if (!item) return null;

  return (
    <div className="morpho-market-chart-tooltip">
      <div className="morpho-market-chart-tooltip-title">
        <span style={{ background: item.color }} />
        <strong>{item.label}</strong>
      </div>
      <div className="morpho-market-chart-tooltip-row">
        <span>占比</span>
        <strong>{percentFormatter.format(item.share * 100)}%</strong>
      </div>
      <div className="morpho-market-chart-tooltip-row">
        <span>金额</span>
        <strong>{formatCompactUsd(String(item.amountUsd))}</strong>
      </div>
      <div className="morpho-market-chart-tooltip-row">
        <span>查询目标</span>
        <strong>{item.targetType === 'vault-v1' ? 'Vault V1' : item.targetType || 'N/A'}</strong>
      </div>
    </div>
  );
}

interface AllocationLiquidityShapeProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: AllocationHistogramItem;
  fill?: string;
  fillOpacity?: number;
  stroke?: string;
  strokeWidth?: number;
  radius?: number;
}

function AllocationLiquidityShape({
  x = 0,
  y = 0,
  width = 0,
  height = 0,
  payload,
  fill = '#10b981',
  fillOpacity = 1,
  stroke = 'none',
  strokeWidth = 0,
  radius = LIQUIDITY_BAR_RADIUS,
}: AllocationLiquidityShapeProps) {
  if (!payload || width <= 0 || height <= 0) return null;
  const cornerRadius = Math.min(radius, width / 2, height);
  const right = x + width;
  const bottom = y + height;
  const path = [
    `M ${x} ${bottom}`,
    `L ${x} ${y + cornerRadius}`,
    `Q ${x} ${y} ${x + cornerRadius} ${y}`,
    `L ${right - cornerRadius} ${y}`,
    `Q ${right} ${y} ${right} ${y + cornerRadius}`,
    `L ${right} ${bottom}`,
    'Z',
  ].join(' ');

  return (
    <g className="morpho-vault-bar-hit-target">
      <path
        d={path}
        fill={fill}
        fillOpacity={fillOpacity}
        stroke={stroke}
        strokeWidth={strokeWidth}
      />
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
  onMarketPin?: (marketId: string) => void;
}

function AllocationAxisTick({
  x = 0,
  y = 0,
  payload,
  index = 0,
  items,
  selectedMarketId,
  onMarketSelect,
  onMarketPin,
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
      onClick={() => {
        onMarketPin?.(item.marketId);
        onMarketSelect(item.marketId);
      }}
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

function MorphoVaultsSortButton({
  field,
  sortBy,
  sortOrder,
  onSortChange,
}: {
  field: MorphoVaultsSortField;
  sortBy: MorphoVaultsSortField;
  sortOrder: MorphoVaultsSortOrder;
  onSortChange: (field: MorphoVaultsSortField) => void;
}) {
  const active = field === sortBy;
  const directionClass = active && sortOrder === 'asc' ? 'morpho-vaults-sort-up' : '';
  return (
    <button
      type="button"
      className={
        active
          ? `morpho-vaults-sort-btn morpho-vaults-sort-btn-active ${directionClass}`
          : 'morpho-vaults-sort-btn'
      }
      onClick={() => onSortChange(field)}
      aria-label={`按 ${field} 排序`}
      aria-pressed={active}
    >
      <span aria-hidden="true" />
    </button>
  );
}

function MorphoVaultsAssetHeader({
  assetInput,
  onAssetInputChange,
  onAssetCommit,
}: {
  assetInput: string;
  onAssetInputChange: (value: string) => void;
  onAssetCommit: () => void;
}) {
  return (
    <div className="morpho-market-asset-header">
      <span className="morpho-market-sort-header">底层资产</span>
      <div className="morpho-market-header-filter-control morpho-vaults-header-filter-control">
        <label className="morpho-market-header-search-field">
          <span className="morpho-market-header-search-icon" aria-hidden="true" />
          <input
            className="morpho-market-header-filter-input"
            type="text"
            value={assetInput}
            onChange={(event) => onAssetInputChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                onAssetCommit();
              }
            }}
            placeholder="symbol / 地址"
            aria-label="按底层资产筛选 Vault"
          />
        </label>
      </div>
    </div>
  );
}

function MorphoVaultsTable({
  vaults,
  loading,
  error,
  assetInput,
  protocolFilter,
  sortBy,
  sortOrder,
  total,
  page,
  totalPages,
  fetchedAt,
  onAssetInputChange,
  onAssetCommit,
  onProtocolFilterChange,
  onSortChange,
  onPageChange,
  onRefresh,
  expandedVaultKey,
  expandedVaultContent,
  onToggleVault,
}: {
  vaults: MorphoVaultsItem[];
  loading: boolean;
  error: string;
  assetInput: string;
  protocolFilter: MorphoVaultProtocolFilter;
  sortBy: MorphoVaultsSortField;
  sortOrder: MorphoVaultsSortOrder;
  total: number;
  page: number;
  totalPages: number;
  fetchedAt: number | null;
  onAssetInputChange: (value: string) => void;
  onAssetCommit: () => void;
  onProtocolFilterChange: (value: MorphoVaultProtocolFilter) => void;
  onSortChange: (field: MorphoVaultsSortField) => void;
  onPageChange: (page: number) => void;
  onRefresh: () => void;
  expandedVaultKey: string;
  expandedVaultContent: ReactNode;
  onToggleVault: (vault: MorphoVaultsItem) => void;
}) {
  const { copied, copy } = useCopiedValue();
  const pageStart = total === 0 ? 0 : (page - 1) * MORPHO_VAULTS_PAGE_SIZE + 1;
  const pageEnd = Math.min(page * MORPHO_VAULTS_PAGE_SIZE, total);
  const refreshedAtText = fetchedAt
    ? new Date(fetchedAt).toLocaleString('zh-CN', { hour12: false })
    : 'N/A';

  return (
    <section className="card morpho-detail-card morpho-vaults-table-shell">
      <div className="card-header">
        <div>
          <span className="card-title morpho-section-title">Vault 列表</span>
          <p className="morpho-section-subtitle">
            按资产与版本筛选 Morpho vaults，并按流动性、资产总美元值或 APY 排序。
          </p>
        </div>
        <div className="morpho-vaults-controls">
          <div className="morpho-market-table-status">
            <span>更新 {refreshedAtText}</span>
            <button type="button" onClick={onRefresh}>
              刷新
            </button>
          </div>
        </div>
      </div>

      <div className="table-wrap">
        <table className="pos-table morpho-table morpho-vaults-table">
          <colgroup>
            <col className="morpho-vaults-col-vault" />
            <col className="morpho-vaults-col-asset" />
            <col className="morpho-vaults-col-metric" />
            <col className="morpho-vaults-col-metric" />
            <col className="morpho-vaults-col-apy" />
            <col className="morpho-vaults-col-version" />
          </colgroup>
          <thead>
            <tr>
              <th>
                <span className="morpho-market-sort-header">Vault</span>
              </th>
              <th>
                <MorphoVaultsAssetHeader
                  assetInput={assetInput}
                  onAssetInputChange={onAssetInputChange}
                  onAssetCommit={onAssetCommit}
                />
              </th>
              <th className="right">
                <span className="morpho-vaults-sort-header">
                  资产总美元值
                  <MorphoVaultsSortButton
                    field="total_assets_usd"
                    sortBy={sortBy}
                    sortOrder={sortOrder}
                    onSortChange={onSortChange}
                  />
                </span>
              </th>
              <th className="right">
                <span className="morpho-vaults-sort-header">
                  流动性
                  <MorphoVaultsSortButton
                    field="liquidity"
                    sortBy={sortBy}
                    sortOrder={sortOrder}
                    onSortChange={onSortChange}
                  />
                </span>
              </th>
              <th className="right">
                <span className="morpho-vaults-sort-header">
                  APY
                  <MorphoVaultsSortButton
                    field="apy"
                    sortBy={sortBy}
                    sortOrder={sortOrder}
                    onSortChange={onSortChange}
                  />
                </span>
              </th>
              <th>
                <div className="morpho-vaults-version-header">
                  <SegmentedControl
                    ariaLabel="Morpho vault 列表版本"
                    value={protocolFilter}
                    onChange={(value) => onProtocolFilterChange(value as MorphoVaultProtocolFilter)}
                    options={[
                      { value: 'all', label: 'All', activeClassName: 'active-purple' },
                      { value: 'v1', label: 'V1', activeClassName: 'active-purple' },
                      { value: 'v2', label: 'V2', activeClassName: 'active-purple' },
                    ]}
                  />
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            {error ? (
              <tr>
                <td colSpan={6}>
                  <div className="morpho-market-table-error-row">{error}</div>
                </td>
              </tr>
            ) : null}
            {loading ? (
              <tr>
                <td colSpan={6}>
                  <div className="morpho-market-inline-state">
                    <div className="spinner"></div>
                  </div>
                </td>
              </tr>
            ) : vaults.length === 0 ? (
              <tr>
                <td colSpan={6}>
                  <div className="morpho-market-inline-state">
                    <span className="empty-text">当前筛选条件下没有可展示的 Morpho vault。</span>
                  </div>
                </td>
              </tr>
            ) : (
              vaults.map((vault) => {
                const vaultKey = `${vault.protocol}:${vault.address.toLowerCase()}`;
                const isExpanded = vaultKey === expandedVaultKey;

                return (
                  <Fragment key={vaultKey}>
                    <tr
                      className={
                        isExpanded
                          ? 'morpho-market-row morpho-market-row-active morpho-vaults-row'
                          : 'morpho-market-row morpho-vaults-row'
                      }
                      onClick={() => onToggleVault(vault)}
                    >
                      <td>
                        <div className="morpho-vaults-name-cell">
                          <strong title={vault.name}>{vault.name || 'Morpho Vault'}</strong>
                          <div className="morpho-vaults-address-line">
                            <span className="mono" title={vault.address}>
                              {compactAddress(vault.address)}
                            </span>
                            <button
                              type="button"
                              className={
                                copied === vault.address
                                  ? 'morpho-market-copy-btn morpho-market-copy-btn-copied'
                                  : 'morpho-market-copy-btn'
                              }
                              onClick={(event) => void copy(event, vault.address)}
                              title="复制 Vault 地址"
                              aria-label="复制 Vault 地址"
                            >
                              <span className="morpho-market-copy-icon" aria-hidden="true" />
                            </button>
                          </div>
                        </div>
                      </td>
                      <td>
                        <div className="morpho-market-asset-cell">
                          <span className="token-symbol">{vault.asset.asset || 'N/A'}</span>
                          <span
                            className="mono morpho-market-token-address-text"
                            title={vault.asset.token_address}
                          >
                            {compactAddress(vault.asset.token_address)}
                          </span>
                          <button
                            type="button"
                            className={
                              copied === vault.asset.token_address
                                ? 'morpho-market-copy-btn morpho-market-copy-btn-copied morpho-market-address-copy-btn'
                                : 'morpho-market-copy-btn morpho-market-address-copy-btn'
                            }
                            onClick={(event) => void copy(event, vault.asset.token_address)}
                            title="复制底层资产地址"
                            aria-label="复制底层资产地址"
                          >
                            <span className="morpho-market-copy-icon" aria-hidden="true" />
                          </button>
                        </div>
                      </td>
                      <td className="right">
                        <span className="morpho-compact-metric">
                          {formatCompactUsd(String(vault.total_assets_usd))}
                        </span>
                      </td>
                      <td className="right">
                        <span className="morpho-compact-metric">
                          {formatCompactUsd(String(vault.liquidity))}
                        </span>
                      </td>
                      <td className="right">
                        <span className="morpho-compact-metric morpho-rate-line-supply">
                          {formatPercent(String(vault.apy))}
                        </span>
                      </td>
                      <td>
                        <span className="morpho-vault-version">
                          {String(vault.protocol).toUpperCase()}
                        </span>
                      </td>
                    </tr>
                    {isExpanded ? (
                      <tr className="morpho-vaults-detail-row">
                        <td colSpan={6}>
                          <div className="morpho-vaults-inline-detail">{expandedVaultContent}</div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="morpho-market-pagination">
        <span>
          显示 {pageStart.toLocaleString()}-{pageEnd.toLocaleString()} / {total.toLocaleString()}
          ，第 {page} / {totalPages} 页
        </span>
        <div className="morpho-market-pagination-actions">
          <button
            type="button"
            className="switch-btn"
            disabled={page <= 1}
            onClick={() => onPageChange(Math.max(1, page - 1))}
          >
            上一页
          </button>
          <button
            type="button"
            className="switch-btn"
            disabled={page >= totalPages}
            onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          >
            下一页
          </button>
        </div>
      </div>
    </section>
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
            </div>
            <div className="metric-box">
              <span className="metric-label">流动性</span>
              <strong>{formatSmartUsd(vault.liquidity_usd)}</strong>
            </div>
            <div className="metric-box">
              <span className="metric-label">净年化收益率</span>
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
  const netApyTooltip = buildVaultV2NetApyTooltip(vault);

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
                <span className="metric-label">资产总美元值</span>
                <strong>{formatSmartUsd(vault.total_assets_usd)}</strong>
              </div>
              <div className="metric-box">
                <span className="metric-label">流动性</span>
                <strong>{formatSmartUsd(vault.liquidity_usd)}</strong>
              </div>
              <div className="metric-box">
                <span className="metric-label">净年化收益率</span>
                <button
                  type="button"
                  className="morpho-vault-apy-trigger"
                  data-tooltip={netApyTooltip}
                  aria-label={netApyTooltip}
                >
                  <strong>{formatPercent(vault.net_apy)}</strong>
                </button>
                <small>APY {formatPercent(vault.apy)}</small>
              </div>
            </div>
          </div>
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
  const [hoveredMarketId, setHoveredMarketId] = useState<string | null>(null);
  const [pinnedMarketId, setPinnedMarketId] = useState<string | null>(null);
  const defaultMarketId = selectedMarketId || legendItems[0]?.marketId || null;
  const activeMarketId = hoveredMarketId ?? pinnedMarketId ?? defaultMarketId;
  const activeAllocation =
    legendItems.find((item) => item.marketId === activeMarketId) ?? legendItems[0] ?? null;
  const highlightedMarketId = activeAllocation?.marketId ?? selectedMarketId;
  const idleShare = useMemo(
    () => legendItems.filter((item) => item.isIdle).reduce((sum, item) => sum + item.share, 0),
    [legendItems],
  );
  const largestShare = legendItems[0]?.share ?? 0;

  useEffect(() => {
    setHoveredMarketId(null);
    setPinnedMarketId(null);
  }, [vault.address, legendItems.length]);

  useEffect(() => {
    if (!selectedMarketId) return;
    setPinnedMarketId(selectedMarketId);
  }, [selectedMarketId]);

  const previewMarket = (marketId: string | null) => {
    setHoveredMarketId(marketId);
  };

  const pinMarket = (marketId: string, shouldQuery = false) => {
    setPinnedMarketId(marketId);
    setHoveredMarketId(marketId);
    if (shouldQuery) onMarketSelect(marketId);
  };

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
                      onMouseLeave={() => previewMarket(null)}
                    >
                      {legendItems.map((item) => {
                        const isActive = item.marketId === highlightedMarketId;
                        return (
                          <Cell
                            key={item.marketId}
                            fill={item.color}
                            stroke={
                              isActive ? createPieActiveStroke(item.color) : 'rgba(2, 6, 23, 0.96)'
                            }
                            strokeWidth={isActive ? 4.4 : 3.2}
                            opacity={1}
                            className={
                              isActive
                                ? 'morpho-vault-pie-slice morpho-vault-pie-slice-active'
                                : 'morpho-vault-pie-slice'
                            }
                            onMouseEnter={() => previewMarket(item.marketId)}
                            onClick={() => pinMarket(item.marketId, true)}
                          />
                        );
                      })}
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
            </div>
          ) : (
            <div className="morpho-vault-empty-chart">
              <strong>暂无分配数据</strong>
              <span>该 vault 当前没有可展示的 supply allocation。</span>
            </div>
          )}
        </div>

        <div className="morpho-vault-allocation-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={legendItems}
              barGap={0}
              margin={{ top: 12, right: 10, bottom: 40, left: 6 }}
              className="morpho-vault-clickable-chart"
              onMouseMove={(event) => {
                const activeEvent = event as unknown as {
                  activeTooltipIndex?: number;
                  activePayload?: Array<{ payload?: AllocationHistogramItem }>;
                };
                const payload = activeEvent.activePayload?.find(
                  (entry) => entry.payload?.marketId,
                )?.payload;
                if (payload?.marketId) {
                  previewMarket(payload.marketId);
                  return;
                }
                if (typeof activeEvent.activeTooltipIndex === 'number') {
                  previewMarket(legendItems[activeEvent.activeTooltipIndex]?.marketId ?? null);
                }
              }}
              onMouseLeave={() => previewMarket(null)}
              onClick={(event) => {
                const activeEvent = event as unknown as {
                  activeTooltipIndex?: number;
                  activePayload?: Array<{ payload?: AllocationHistogramItem }>;
                };
                const payload = activeEvent.activePayload?.find(
                  (entry) => entry.payload?.marketId,
                )?.payload;
                const marketId =
                  payload?.marketId ??
                  (typeof activeEvent.activeTooltipIndex === 'number'
                    ? legendItems[activeEvent.activeTooltipIndex]?.marketId
                    : null);
                if (marketId) pinMarket(marketId, true);
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
                    onMarketPin={(marketId) => pinMarket(marketId)}
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
                cursor={{ fill: 'rgba(55, 69, 103, 0.42)' }}
              />
              <Bar
                dataKey="allocation"
                barSize={30}
                stackId="quota-stack"
                radius={[5, 5, 0, 0]}
                isAnimationActive={false}
              >
                {legendItems.map((item) => (
                  <Cell
                    key={`allocation-${item.marketId}`}
                    fill={item.color}
                    fillOpacity={1}
                    stroke={
                      item.marketId === highlightedMarketId
                        ? createPieActiveStroke(item.color)
                        : hexToRgba(item.color, 0.74)
                    }
                    strokeWidth={item.marketId === highlightedMarketId ? 3.5 : 1}
                    className={
                      item.marketId === highlightedMarketId
                        ? 'morpho-vault-bar-cell morpho-vault-bar-cell-active'
                        : 'morpho-vault-bar-cell'
                    }
                    onMouseEnter={() => previewMarket(item.marketId)}
                    onClick={() => pinMarket(item.marketId, true)}
                  />
                ))}
              </Bar>
              <Bar
                dataKey="liquidity"
                barSize={30}
                radius={[5, 5, 0, 0]}
                shape={<AllocationLiquidityShape radius={LIQUIDITY_BAR_RADIUS} />}
                isAnimationActive={false}
              >
                {legendItems.map((item) => (
                  <Cell
                    key={`liquidity-${item.marketId}`}
                    fill={createLiquidityColor(item.color)}
                    fillOpacity={item.marketId === highlightedMarketId ? 0.9 : 0.72}
                    stroke={
                      item.marketId === highlightedMarketId
                        ? createPieActiveStroke(item.color)
                        : 'none'
                    }
                    strokeWidth={item.marketId === highlightedMarketId ? 2.5 : 0}
                    className={
                      item.marketId === highlightedMarketId
                        ? 'morpho-vault-bar-cell morpho-vault-bar-cell-active'
                        : 'morpho-vault-bar-cell'
                    }
                    onMouseEnter={() => previewMarket(item.marketId)}
                    onClick={() => pinMarket(item.marketId, true)}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      {marketQuerySection ? (
        <div className="morpho-vault-allocation-market-section">
          <aside className="morpho-vault-market-directory" aria-label="Vault allocation markets">
            <div className="morpho-vault-market-directory-head">
              <strong>市场目录</strong>
              <span>{legendItems.length} markets</span>
            </div>
            <div className="morpho-vault-market-directory-list">
              {legendItems.map((item) => (
                <button
                  type="button"
                  key={item.marketId}
                  className={
                    item.marketId === selectedMarketId
                      ? 'morpho-vault-market-directory-item morpho-vault-market-directory-item-active'
                      : 'morpho-vault-market-directory-item'
                  }
                  onClick={() => {
                    pinMarket(item.marketId, true);
                  }}
                  title={item.marketId}
                >
                  <span
                    className="morpho-vault-market-directory-swatch"
                    style={{ background: item.color }}
                  />
                  <span className="morpho-vault-market-directory-main">
                    <strong>{item.displayName}</strong>
                    <small>{percentFormatter.format(item.share * 100)}%</small>
                  </span>
                  <span className="morpho-vault-market-directory-value">
                    {formatCompactUsd(String(item.supplyUsd))}
                  </span>
                </button>
              ))}
            </div>
          </aside>
          <div className="morpho-vault-market-query-result">{marketQuerySection}</div>
        </div>
      ) : null}
    </section>
  );
}

function createVaultV2AdapterChartItems(vault: MorphoVaultV2Response): VaultV2AdapterChartItem[] {
  const positiveAdapters = (vault.adapters ?? [])
    .flatMap((adapter, index) => {
      const marketPositions = adapter.market_positions ?? [];
      if (marketPositions.length > 0) {
        return marketPositions.map((position, positionIndex) => {
          const amountUsd = parseNumber(position.supply_assets_usd) ?? 0;
          const marketLabel = resolveMarketPairLabel(
            position.collateral_symbol,
            position.loan_symbol,
            position.market_id,
          );

          return {
            key: `${adapter.type ?? 'market'}:${position.market_id}`,
            label: marketLabel,
            displayName: marketLabel,
            amountUsd,
            share: 0,
            color: ALLOCATION_COLORS[(index + positionIndex) % ALLOCATION_COLORS.length],
            targetType: 'market' as const,
            targetId: position.market_id,
            dataSource: adapter.data_source,
          };
        });
      }

      const amountUsd = parseNumber(adapter.assets_usd) ?? 0;
      const label = adapter.type || `Adapter ${index + 1}`;
      const displayName =
        adapter.target_type === 'vault-v1'
          ? `V1 ${compactAddress(adapter.target_id)}`
          : adapter.target_type === 'market'
            ? compactMarketId(adapter.target_id ?? '')
            : label;

      return {
        key: `${adapter.type ?? 'adapter'}:${adapter.target_id ?? index}`,
        label,
        displayName,
        amountUsd,
        share: 0,
        color: ALLOCATION_COLORS[index % ALLOCATION_COLORS.length],
        targetType: adapter.target_type,
        targetId: adapter.target_id,
        dataSource: adapter.data_source,
      };
    })
    .filter((item) => item.amountUsd > 0 || item.targetId);
  const total = positiveAdapters.reduce((sum, item) => sum + item.amountUsd, 0);

  return positiveAdapters
    .map((item) => ({
      ...item,
      share: total > 0 ? item.amountUsd / total : 0,
    }))
    .sort((left, right) => right.amountUsd - left.amountUsd);
}

function VaultV2AdapterAxisTick({
  x = 0,
  y = 0,
  payload,
  index = 0,
  items,
  activeKey,
  onAdapterSelect,
}: {
  x?: number | string;
  y?: number | string;
  payload?: { value?: string };
  index?: number;
  items: VaultV2AdapterChartItem[];
  activeKey: string | null;
  onAdapterSelect: (item: VaultV2AdapterChartItem) => void;
}) {
  const item = items[index];
  if (!item) return null;
  const numericX = Number(x);
  const numericY = Number(y);
  const isSelected = item.key === activeKey;

  return (
    <g
      transform={`translate(${Number.isFinite(numericX) ? numericX : 0},${Number.isFinite(numericY) ? numericY : 0})`}
      className={
        isSelected
          ? 'morpho-vault-axis-tick morpho-vault-axis-tick-selected'
          : 'morpho-vault-axis-tick'
      }
      onClick={() => onAdapterSelect(item)}
      role="button"
      aria-label={`查询 ${item.label}`}
    >
      <title>{item.targetId ?? item.label}</title>
      <text x={0} y={0} dy={16} textAnchor="end" transform="rotate(-45)">
        {payload?.value ?? item.displayName}
      </text>
    </g>
  );
}

function MorphoVaultV2AdapterChart({
  vault,
  onVaultV1Select,
  onMarketSelect,
  queryResultSection,
}: {
  vault: MorphoVaultV2Response;
  onVaultV1Select: (address: string) => void;
  onMarketSelect: (marketId: string) => void;
  queryResultSection?: ReactNode;
}) {
  const adapterItems = useMemo(() => createVaultV2AdapterChartItems(vault), [vault]);
  const totalUsd = useMemo(
    () => adapterItems.reduce((sum, item) => sum + item.amountUsd, 0),
    [adapterItems],
  );
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const [pinnedKey, setPinnedKey] = useState<string | null>(null);
  const activeKey = hoveredKey ?? pinnedKey;
  const activeAdapter = adapterItems.find((item) => item.key === activeKey) ?? null;
  const targetCount = adapterItems.filter((item) => item.targetId).length;
  const v1Count = adapterItems.filter((item) => item.targetType === 'vault-v1').length;

  useEffect(() => {
    setHoveredKey(null);
    setPinnedKey(null);
  }, [vault.address, adapterItems.length]);

  const selectAdapter = (item: VaultV2AdapterChartItem) => {
    setPinnedKey(item.key);
    setHoveredKey(item.key);
    if (!item.targetId) return;
    if (item.targetType === 'vault-v1') {
      onVaultV1Select(item.targetId);
      return;
    }
    if (item.targetType === 'market') {
      onMarketSelect(item.targetId);
    }
  };

  const previewAdapter = (key: string | null) => {
    setHoveredKey(key);
  };

  const selectEventAdapter = (event: unknown) => {
    const activeEvent = event as {
      activeTooltipIndex?: number;
      activePayload?: Array<{ payload?: VaultV2AdapterChartItem }>;
    };
    const payload = activeEvent.activePayload?.find((entry) => entry.payload?.key)?.payload;
    return (
      payload ??
      (typeof activeEvent.activeTooltipIndex === 'number'
        ? adapterItems[activeEvent.activeTooltipIndex]
        : null)
    );
  };

  return (
    <section className="card morpho-detail-card morpho-vault-allocation-card morpho-vault-v2-adapters-card">
      <div className="card-header">
        <div>
          <span className="card-title morpho-section-title">Adapters</span>
          <p className="morpho-section-subtitle">
            饼图展示各 adapter 占比，柱状图展示资产美元金额。
          </p>
        </div>
        <div className="morpho-vault-insight-strip">
          <span>{adapterItems.length} 个 分配</span>
          <span>{targetCount} 个 Markets 分配</span>
          <span>{v1Count} 个 Vault V1 分配</span>
        </div>
      </div>

      <div className="morpho-vault-allocation-layout">
        <div className="morpho-vault-pie-panel">
          {adapterItems.length > 0 ? (
            <div className="morpho-vault-pie-layout">
              <div className="morpho-vault-pie">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
                    <Pie
                      data={adapterItems}
                      dataKey="amountUsd"
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
                      onMouseLeave={() => setHoveredKey(null)}
                    >
                      {adapterItems.map((item) => {
                        const isActive = item.key === activeAdapter?.key;
                        return (
                          <Cell
                            key={item.key}
                            fill={item.color}
                            stroke={
                              isActive ? createPieActiveStroke(item.color) : 'rgba(2, 6, 23, 0.96)'
                            }
                            strokeWidth={isActive ? 4.4 : 3.2}
                            opacity={1}
                            className={
                              isActive
                                ? 'morpho-vault-pie-slice morpho-vault-pie-slice-active'
                                : 'morpho-vault-pie-slice'
                            }
                            onMouseEnter={() => previewAdapter(item.key)}
                            onClick={() => selectAdapter(item)}
                          />
                        );
                      })}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
                <div className="morpho-vault-pie-center">
                  <span>{activeAdapter?.label ?? vault.asset.symbol ?? 'Adapters'}</span>
                  <strong>
                    {activeAdapter
                      ? `${percentFormatter.format(activeAdapter.share * 100)}%`
                      : formatCompactUsd(String(totalUsd))}
                  </strong>
                  {activeAdapter ? (
                    <small>{formatCompactUsd(String(activeAdapter.amountUsd))}</small>
                  ) : null}
                </div>
              </div>
            </div>
          ) : (
            <div className="morpho-vault-empty-chart">
              <strong>暂无 adapters 数据</strong>
              <span>该 V2 vault 当前没有可展示的 adapter 金额。</span>
            </div>
          )}
        </div>

        <div className="morpho-vault-allocation-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={adapterItems}
              barGap={0}
              margin={{ top: 12, right: 10, bottom: 40, left: 6 }}
              className="morpho-vault-clickable-chart"
              onMouseMove={(event) => {
                const item = selectEventAdapter(event);
                setHoveredKey(item?.key ?? null);
              }}
              onMouseLeave={() => setHoveredKey(null)}
              onClick={(event) => {
                const item = selectEventAdapter(event);
                if (item) selectAdapter(item);
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
                  <VaultV2AdapterAxisTick
                    {...props}
                    items={adapterItems}
                    activeKey={activeAdapter?.key ?? null}
                    onAdapterSelect={selectAdapter}
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
                content={<VaultV2AdapterTooltip />}
                cursor={{ fill: 'rgba(55, 69, 103, 0.42)' }}
              />
              <Bar dataKey="amountUsd" barSize={30} radius={[5, 5, 0, 0]} isAnimationActive={false}>
                {adapterItems.map((item) => (
                  <Cell
                    key={item.key}
                    fill={item.color}
                    fillOpacity={1}
                    stroke={
                      item.key === activeAdapter?.key
                        ? createPieActiveStroke(item.color)
                        : hexToRgba(item.color, 0.74)
                    }
                    strokeWidth={item.key === activeAdapter?.key ? 3.5 : 1}
                    className={
                      item.key === activeAdapter?.key
                        ? 'morpho-vault-bar-cell morpho-vault-bar-cell-active'
                        : 'morpho-vault-bar-cell'
                    }
                    onMouseEnter={() => previewAdapter(item.key)}
                    onClick={() => selectAdapter(item)}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {queryResultSection ? (
        <div className="morpho-vault-v2-adapter-actions">
          <div className="morpho-vault-market-directory">
            <div className="morpho-vault-market-directory-head">
              <strong>检索目标</strong>
              <span>{targetCount} targets</span>
            </div>
            <div className="morpho-vault-market-directory-list">
              {adapterItems.map((item) => (
                <button
                  type="button"
                  key={item.key}
                  className={
                    item.key === activeAdapter?.key
                      ? 'morpho-vault-market-directory-item morpho-vault-market-directory-item-active'
                      : 'morpho-vault-market-directory-item'
                  }
                  onClick={() => selectAdapter(item)}
                  disabled={!item.targetId}
                  title={item.targetId ?? item.label}
                >
                  <span
                    className="morpho-vault-market-directory-swatch"
                    style={{ background: item.color }}
                  />
                  <span className="morpho-vault-market-directory-main">
                    <strong>{item.label}</strong>
                    <small>
                      {item.targetType === 'vault-v1'
                        ? '查询 Vault V1'
                        : item.targetType === 'market'
                          ? '查询 Market'
                          : '无查询目标'}
                    </small>
                  </span>
                  <span className="morpho-vault-market-directory-value">
                    {formatCompactUsd(String(item.amountUsd))}
                  </span>
                </button>
              ))}
            </div>
          </div>
          <div className="morpho-vault-market-query-result">{queryResultSection}</div>
        </div>
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
  const [activeVaultView, setActiveVaultView] = useState<MorphoVaultViewMode>('list');
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
  const [showVaultHistory, setShowVaultHistory] = useState(false);
  const [vaultSearchHistoryByVersion, setVaultSearchHistoryByVersion] = useState(() =>
    loadMorphoVaultSearchHistory(),
  );
  const [vaultsPage, setVaultsPage] = useState(1);
  const [vaultsAssetInput, setVaultsAssetInput] = useState('');
  const [vaultsAssetFilter, setVaultsAssetFilter] = useState('');
  const [vaultsProtocolFilter, setVaultsProtocolFilter] =
    useState<MorphoVaultProtocolFilter>('all');
  const [vaultsSortBy, setVaultsSortBy] = useState<MorphoVaultsSortField>('total_assets_usd');
  const [vaultsSortOrder, setVaultsSortOrder] = useState<MorphoVaultsSortOrder>('desc');
  const [vaults, setVaults] = useState<MorphoVaultsItem[]>([]);
  const [vaultsTotal, setVaultsTotal] = useState(0);
  const [vaultsLoading, setVaultsLoading] = useState(false);
  const [vaultsError, setVaultsError] = useState('');
  const [vaultsFetchedAt, setVaultsFetchedAt] = useState<number | null>(null);
  const [expandedVaultKey, setExpandedVaultKey] = useState('');
  const [expandedVaultDetail, setExpandedVaultDetail] = useState<ExpandedVaultDetailState>({
    key: '',
    loading: false,
    error: '',
    vault: null,
    vaultV2: null,
  });
  const [adapterVaultV1Detail, setAdapterVaultV1Detail] = useState<AdapterVaultV1DetailState>({
    address: '',
    loading: false,
    error: '',
    vault: null,
  });
  const activeVaultAddress = vaultAddressByVersion[vaultVersion];
  const vaultSearchHistory = vaultSearchHistoryByVersion[vaultVersion];
  const vaultsTotalPages = Math.max(1, Math.ceil(vaultsTotal / MORPHO_VAULTS_PAGE_SIZE));
  const rememberVaultAddress = useCallback((address: string, version: MorphoVaultVersion) => {
    const normalizedAddress = address.trim();
    if (!normalizedAddress) return;
    setVaultSearchHistoryByVersion((current) => {
      const next = {
        ...current,
        [version]: [
          normalizedAddress,
          ...current[version].filter(
            (item) => item.toLowerCase() !== normalizedAddress.toLowerCase(),
          ),
        ].slice(0, MORPHO_VAULT_HISTORY_LIMIT),
      };
      saveMorphoVaultSearchHistory(next);
      return next;
    });
  }, []);
  const clearVaultSearchHistory = useCallback((version: MorphoVaultVersion) => {
    setVaultSearchHistoryByVersion((current) => {
      const next = { ...current, [version]: [] };
      saveMorphoVaultSearchHistory(next);
      return next;
    });
  }, []);

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
          setAdapterVaultV1Detail({
            address: '',
            loading: false,
            error: '',
            vault: null,
          });
          const result = await fetchMorphoVaultV2WithMeta(normalizedAddress, { force });
          setVaultV2(result.data);
          setVaultFetchedAt(result.meta.fetchedAt);
          rememberVaultAddress(normalizedAddress, version);
        } else {
          setVaultV2(null);
          const result = await fetchMorphoVaultWithMeta(normalizedAddress, { force });
          setVault(result.data);
          setVaultFetchedAt(result.meta.fetchedAt);
          rememberVaultAddress(normalizedAddress, version);
        }
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : '无法加载 Morpho vault 数据');
      } finally {
        setLoading(false);
      }
    },
    [onMarketSelect, rememberVaultAddress, vaultVersion],
  );

  const loadVault = useCallback(
    async (force = false) => {
      await loadVaultForAddress(vaultAddress, force, vaultVersion);
    },
    [loadVaultForAddress, vaultAddress, vaultVersion],
  );

  const loadVaults = useCallback(
    async (force = false) => {
      const assetKeyword = vaultsAssetFilter.trim();
      const assetAddress = isAddress(assetKeyword, { strict: false }) ? assetKeyword : undefined;
      const asset = assetAddress ? undefined : assetKeyword || undefined;
      const protocol =
        vaultsProtocolFilter === 'all' ? undefined : (vaultsProtocolFilter as MorphoVaultsProtocol);

      setVaultsError('');
      setVaultsLoading(true);
      try {
        const result = await fetchMorphoVaultsWithMeta({
          force,
          page: vaultsPage,
          pageSize: MORPHO_VAULTS_PAGE_SIZE,
          sortBy: vaultsSortBy,
          sortOrder: vaultsSortOrder,
          asset,
          assetAddress,
          protocol,
        });
        setVaults(result.data.items);
        setVaultsTotal(result.data.total);
        setVaultsFetchedAt(result.meta.fetchedAt);
      } catch (listError) {
        setVaultsError(
          listError instanceof Error ? listError.message : '无法加载 Morpho vault 列表',
        );
      } finally {
        setVaultsLoading(false);
      }
    },
    [vaultsAssetFilter, vaultsPage, vaultsProtocolFilter, vaultsSortBy, vaultsSortOrder],
  );

  const commitVaultsAssetFilter = useCallback(() => {
    setVaultsAssetFilter(vaultsAssetInput.trim());
    setVaultsPage(1);
  }, [vaultsAssetInput]);

  const handleVaultsProtocolFilterChange = useCallback((value: MorphoVaultProtocolFilter) => {
    setVaultsProtocolFilter(value);
    setVaultsPage(1);
  }, []);

  const handleVaultsSortChange = useCallback(
    (field: MorphoVaultsSortField) => {
      setVaultsPage(1);
      if (field === vaultsSortBy) {
        setVaultsSortOrder((current) => (current === 'desc' ? 'asc' : 'desc'));
        return;
      }
      setVaultsSortBy(field);
      setVaultsSortOrder('desc');
    },
    [vaultsSortBy],
  );

  const handleVaultsPageChange = useCallback(
    (nextPage: number) => {
      setVaultsPage(Math.min(vaultsTotalPages, Math.max(1, nextPage)));
    },
    [vaultsTotalPages],
  );

  const handleVaultListToggle = useCallback(
    (item: MorphoVaultsItem) => {
      const key = `${item.protocol}:${item.address.toLowerCase()}`;
      if (expandedVaultKey === key) {
        setExpandedVaultKey('');
        setExpandedVaultDetail({
          key: '',
          loading: false,
          error: '',
          vault: null,
          vaultV2: null,
        });
        return;
      }

      const version = item.protocol === 'v2' ? 'v2' : 'v1';
      setExpandedVaultKey(key);
      setAdapterVaultV1Detail({
        address: '',
        loading: false,
        error: '',
        vault: null,
      });
      setExpandedVaultDetail({
        key,
        loading: true,
        error: '',
        vault: null,
        vaultV2: null,
      });

      void (async () => {
        try {
          if (version === 'v2') {
            const result = await fetchMorphoVaultV2WithMeta(item.address);
            setExpandedVaultDetail((current) =>
              current.key === key
                ? {
                    key,
                    loading: false,
                    error: '',
                    vault: null,
                    vaultV2: result.data,
                  }
                : current,
            );
            return;
          }

          const result = await fetchMorphoVaultWithMeta(item.address);
          setExpandedVaultDetail((current) =>
            current.key === key
              ? {
                  key,
                  loading: false,
                  error: '',
                  vault: result.data,
                  vaultV2: null,
                }
              : current,
          );
        } catch (detailError) {
          setExpandedVaultDetail((current) =>
            current.key === key
              ? {
                  key,
                  loading: false,
                  error:
                    detailError instanceof Error
                      ? detailError.message
                      : '无法加载 Morpho vault 数据',
                  vault: null,
                  vaultV2: null,
                }
              : current,
          );
        }
      })();
    },
    [expandedVaultKey, onMarketSelect],
  );

  const handleVaultV2AdapterVaultV1Select = useCallback(
    (address: string) => {
      const normalizedAddress = address.trim();
      if (!normalizedAddress) return;
      setVaultAddressByVersion((current) => ({ ...current, v1: normalizedAddress }));
      setActiveVaultView('query');
      setVaultVersion('v1');
      setVaultAddress(normalizedAddress);
      void loadVaultForAddress(normalizedAddress, false, 'v1');
    },
    [loadVaultForAddress],
  );

  const handleVaultV2AdapterMarketSelect = useCallback(
    (marketId: string) => {
      const normalizedMarketId = marketId.trim().toLowerCase();
      if (!isMorphoMarketId(normalizedMarketId)) {
        setAdapterVaultV1Detail({
          address: '',
          loading: false,
          error: '接口没有返回完整的 0x 开头 32 字节 market id，无法检索该市场。',
          vault: null,
        });
        return;
      }
      setAdapterVaultV1Detail({
        address: '',
        loading: false,
        error: '',
        vault: null,
      });
      onMarketSelect(normalizedMarketId);
    },
    [onMarketSelect],
  );

  const refreshedAtText = vaultFetchedAt
    ? new Date(vaultFetchedAt).toLocaleString('zh-CN', {
        hour12: false,
      })
    : 'N/A';

  useEffect(() => {
    if (activeVaultView !== 'query') return;
    setVaultAddress(activeVaultAddress);
    void loadVaultForAddress(activeVaultAddress, false, vaultVersion);
  }, [activeVaultAddress, activeVaultView, loadVaultForAddress, vaultVersion]);

  useEffect(() => {
    void loadVaults(false);
  }, [loadVaults]);

  useEffect(() => {
    setExpandedVaultKey('');
    setExpandedVaultDetail({
      key: '',
      loading: false,
      error: '',
      vault: null,
      vaultV2: null,
    });
  }, [vaultsAssetFilter, vaultsPage, vaultsProtocolFilter, vaultsSortBy, vaultsSortOrder]);

  const vaultMarketQuerySection = selectedMarketId ? (
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
      showColumnHeaders={false}
      showSummaryRows={false}
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
  );
  const vaultV2AdapterQuerySection = adapterVaultV1Detail.loading ? (
    <div className="morpho-market-inline-state">
      <div className="spinner"></div>
    </div>
  ) : adapterVaultV1Detail.error ? (
    <div className="morpho-market-table-error-row">{adapterVaultV1Detail.error}</div>
  ) : adapterVaultV1Detail.vault ? (
    <div className="morpho-vault-v1-inline-result">
      <MorphoVaultOverview vault={adapterVaultV1Detail.vault} />
      <MorphoVaultAllocationChart
        vault={adapterVaultV1Detail.vault}
        selectedMarketId={selectedMarketId}
        onMarketSelect={handleVaultV2AdapterMarketSelect}
      />
    </div>
  ) : (
    vaultMarketQuerySection
  );

  const expandedVaultContent =
    expandedVaultDetail.loading || expandedVaultDetail.key !== expandedVaultKey ? (
      <div className="morpho-market-inline-state">
        <div className="spinner"></div>
      </div>
    ) : expandedVaultDetail.error ? (
      <div className="morpho-market-table-error-row">{expandedVaultDetail.error}</div>
    ) : expandedVaultDetail.vaultV2 ? (
      <>
        <MorphoVaultV2Overview vault={expandedVaultDetail.vaultV2} />
        <MorphoVaultV2AdapterChart
          vault={expandedVaultDetail.vaultV2}
          onVaultV1Select={handleVaultV2AdapterVaultV1Select}
          onMarketSelect={handleVaultV2AdapterMarketSelect}
          queryResultSection={vaultV2AdapterQuerySection}
        />
      </>
    ) : expandedVaultDetail.vault ? (
      <>
        <MorphoVaultOverview vault={expandedVaultDetail.vault} />
        <MorphoVaultAllocationChart
          vault={expandedVaultDetail.vault}
          selectedMarketId={selectedMarketId}
          onMarketSelect={onMarketSelect}
          marketQuerySection={vaultMarketQuerySection}
        />
      </>
    ) : (
      <div className="morpho-market-inline-state">
        <span className="empty-text">暂无可展示的 Morpho vault 详情。</span>
      </div>
    );

  return (
    <div className="morpho-vault-page">
      <section className="card morpho-detail-card morpho-vault-mode-card">
        <SegmentedControl
          ariaLabel="Morpho vault 页面视图"
          value={activeVaultView}
          onChange={(value) => setActiveVaultView(value as MorphoVaultViewMode)}
          options={[
            { value: 'list', label: 'Vaults 列表' },
            { value: 'query', label: 'Vault 查询' },
          ]}
        />
      </section>

      {activeVaultView === 'list' ? (
        <MorphoVaultsTable
          vaults={vaults}
          loading={vaultsLoading}
          error={vaultsError}
          assetInput={vaultsAssetInput}
          protocolFilter={vaultsProtocolFilter}
          sortBy={vaultsSortBy}
          sortOrder={vaultsSortOrder}
          total={vaultsTotal}
          page={vaultsPage}
          totalPages={vaultsTotalPages}
          fetchedAt={vaultsFetchedAt}
          expandedVaultKey={expandedVaultKey}
          expandedVaultContent={expandedVaultContent}
          onAssetInputChange={setVaultsAssetInput}
          onAssetCommit={commitVaultsAssetFilter}
          onProtocolFilterChange={handleVaultsProtocolFilterChange}
          onSortChange={handleVaultsSortChange}
          onPageChange={handleVaultsPageChange}
          onRefresh={() => void loadVaults(true)}
          onToggleVault={handleVaultListToggle}
        />
      ) : (
        <>
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
              <div className="input-wrapper">
                <input
                  className="address-input"
                  value={vaultAddress}
                  onFocus={() => setShowVaultHistory(true)}
                  onBlur={() => window.setTimeout(() => setShowVaultHistory(false), 120)}
                  onChange={(event) => {
                    setVaultAddress(event.target.value);
                    setError('');
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void loadVault(false);
                  }}
                  placeholder="输入 Morpho vault 地址"
                />
                {showVaultHistory && vaultSearchHistory.length > 0 ? (
                  <div className="history-dropdown morpho-vault-search-history-dropdown">
                    <div className="history-header">
                      <span>{vaultVersion.toUpperCase()} Vault 搜索记录</span>
                      <button
                        type="button"
                        className="clear-history-btn"
                        onMouseDown={(event) => {
                          event.preventDefault();
                          clearVaultSearchHistory(vaultVersion);
                        }}
                      >
                        清除记录
                      </button>
                    </div>
                    <ul className="history-list">
                      {vaultSearchHistory.map((address) => (
                        <li
                          key={address}
                          className="history-item"
                          title={address}
                          onMouseDown={(event) => {
                            event.preventDefault();
                            setVaultAddress(address);
                            setShowVaultHistory(false);
                          }}
                        >
                          {address}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
              <button
                type="button"
                className="search-btn morpho-vault-query-btn"
                onClick={() => void loadVault(false)}
              >
                查询
              </button>
            </div>
            {(vaultVersion === 'v1' ? vault !== null : vaultV2 !== null) ? (
              <div className="morpho-vault-search-status">
                <span>更新 {refreshedAtText}</span>
                <button type="button" onClick={() => void loadVault(true)}>
                  刷新
                </button>
              </div>
            ) : null}
            {error ? <div className="morpho-banner morpho-banner-warn">{error}</div> : null}
          </section>

          {loading ? (
            <div className="card morpho-market-loading-card">
              <div className="spinner"></div>
            </div>
          ) : null}

          {vaultVersion === 'v2' && vaultV2 ? (
            <>
              <MorphoVaultV2Overview vault={vaultV2} />
              <MorphoVaultV2AdapterChart
                vault={vaultV2}
                onVaultV1Select={handleVaultV2AdapterVaultV1Select}
                onMarketSelect={handleVaultV2AdapterMarketSelect}
                queryResultSection={vaultV2AdapterQuerySection}
              />
            </>
          ) : null}

          {vaultVersion === 'v1' && vault ? (
            <>
              <MorphoVaultOverview vault={vault} />
              <MorphoVaultAllocationChart
                vault={vault}
                selectedMarketId={selectedMarketId}
                onMarketSelect={onMarketSelect}
                marketQuerySection={vaultMarketQuerySection}
              />
            </>
          ) : null}
        </>
      )}
    </div>
  );
}
