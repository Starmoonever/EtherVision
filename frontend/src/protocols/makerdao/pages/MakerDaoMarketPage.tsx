import {
  Fragment,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import {
  fetchMakerDaoIlksWithMeta,
  fetchMakerDaoPositionsWithMeta,
  type MakerDaoIlkItem,
  type MakerDaoPositionListItem,
  type MakerDaoPositionsResponse,
} from '../../../api/makerdao';
import { fetchAssetPriceWithMeta } from '../../../api/price';
import { mergeRequestMetas, type AggregatedRequestMeta } from '../../../api/requestMeta';
import { ChartDataStatus } from '../../../components/ChartAssist';
import { PageHero } from '../../../shared/components/PageHero';
import { copyToClipboard } from '../../../shared/utils/copyToClipboard';

interface MakerDaoMarketPageProps {
  active: boolean;
}

type SortMode = 'alpha' | 'updated_desc';
type ContractStatusFilter = 'all' | 'deployed' | 'internal';
type IlkGroup = 'all' | 'native' | 'rwa' | 'direct' | 'stable' | 'lp' | 'system' | 'other';
type PositionScopeFilter = 'all' | 'user' | 'system';
type PositionHealthFilter = 'all' | 'healthy' | 'unhealthy';
type PositionSortBy =
  | 'health_factor'
  | 'collateral_value_usd'
  | 'debt_value_usd'
  | 'liquidation_price_usd'
  | 'ilk';
type PositionOrder = 'asc' | 'desc';

interface MakerDaoIlkView extends MakerDaoIlkItem {
  key: string;
  group: Exclude<IlkGroup, 'all'>;
  groupLabel: string;
  contractStatus: Exclude<ContractStatusFilter, 'all'>;
  searchText: string;
  updatedAtLabel: string;
  updatedAtTitle: string;
  isStale: boolean;
  explorerUrl: string | null;
}

const EMPTY_META: AggregatedRequestMeta = {
  lastUpdatedAt: null,
  cacheStatus: 'none',
};
const METADATA_PAGE_SIZE = 10;
const POSITIONS_PAGE_SIZE = 25;
const PRICE_FAILURE_TTL_MS = 5 * 60 * 1000;
const priceFailureCache = new Map<string, number>();

const GROUP_LABELS: Record<Exclude<IlkGroup, 'all'>, string> = {
  native: 'Native Crypto',
  rwa: 'Real World Assets',
  direct: 'Direct Deposit / D3M',
  stable: 'Stablecoins',
  lp: 'LP / Structured',
  system: 'System Internal',
  other: 'Other Ilks',
};

const GROUP_OPTIONS: Array<{ value: IlkGroup; label: string }> = [
  { value: 'all', label: '全部分组' },
  { value: 'native', label: GROUP_LABELS.native },
  { value: 'rwa', label: GROUP_LABELS.rwa },
  { value: 'direct', label: GROUP_LABELS.direct },
  { value: 'stable', label: GROUP_LABELS.stable },
  { value: 'lp', label: GROUP_LABELS.lp },
  { value: 'system', label: GROUP_LABELS.system },
  { value: 'other', label: GROUP_LABELS.other },
];

const POSITION_SORT_OPTIONS: Array<{ value: PositionSortBy; label: string }> = [
  { value: 'collateral_value_usd', label: '抵押价值' },
  { value: 'debt_value_usd', label: '债务价值' },
  { value: 'health_factor', label: '健康因子' },
  { value: 'liquidation_price_usd', label: '清算价格' },
  { value: 'ilk', label: 'Ilk' },
];

const CONTRACT_STATUS_OPTIONS: Array<{ value: ContractStatusFilter; label: string }> = [
  { value: 'all', label: '全部状态' },
  { value: 'deployed', label: '已部署合约' },
  { value: 'internal', label: '系统内部账户' },
];

const METADATA_SORT_OPTIONS: Array<{ value: SortMode; label: string }> = [
  { value: 'alpha', label: '字母顺序' },
  { value: 'updated_desc', label: '最近更新' },
];

const POSITION_SCOPE_OPTIONS: Array<{ value: PositionScopeFilter; label: string }> = [
  { value: 'all', label: '全部仓位' },
  { value: 'user', label: '普通 Vault' },
  { value: 'system', label: '系统仓位' },
];

const POSITION_HEALTH_OPTIONS: Array<{ value: PositionHealthFilter; label: string }> = [
  { value: 'all', label: '全部状态' },
  { value: 'healthy', label: '健康' },
  { value: 'unhealthy', label: '非健康' },
];

const POSITION_ORDER_OPTIONS: Array<{ value: PositionOrder; label: string }> = [
  { value: 'desc', label: '↓ 从高到低' },
  { value: 'asc', label: '↑ 从低到高' },
];

const HEALTH_FACTOR_EXPLAIN_ITEMS = [
  {
    term: '黄色闪烁',
    meaning: '表示健康因子低于 1.1，仓位已进入高风险区。',
    riskHint: '表示接近清算边界的账户或系统仓位。',
  },
  {
    term: '绿色闪烁无风险',
    meaning: '表示∞健康因子，通常来自没有活跃债务但仍有抵押价值的仓位。',
    riskHint: '这类仓位单独高亮为原生无风险状态。',
  },
  {
    term: '绿色静态无风险',
    meaning: '表示健康因子大于 5 且小于∞，当前风险极低。',
    riskHint: '这类仓位作为高健康因子地址标识。',
  },
  {
    term: '橙色',
    meaning: '表示健康因子处于观察区间，需要关注抵押价值与清算价格变化。',
    riskHint: '适合作为风险巡检时的次优先级观察对象。',
  },
];

function normalizeProtocol(value: string): string {
  if (!value) return 'MakerDAO';
  return value.toLowerCase() === 'makerdao' ? 'MakerDAO' : value;
}

interface MakerDaoSegmentedControlProps<T extends string> {
  label: string;
  value: T;
  options: Array<{ value: T; label: string; title?: string }>;
  ariaLabel: string;
  onChange: (value: T) => void;
}

function MakerDaoSegmentedControl<T extends string>({
  label,
  value,
  options,
  ariaLabel,
  onChange,
}: MakerDaoSegmentedControlProps<T>) {
  return (
    <div className="makerdao-filter-control">
      <span className="metric-label">{label}</span>
      <div className="makerdao-switch-group" aria-label={ariaLabel}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`makerdao-switch-btn ${value === option.value ? 'active' : ''}`}
            onClick={() => onChange(option.value)}
            title={option.title || option.label}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function MakerDaoSearchControl({
  label,
  value,
  placeholder,
  onChange,
  onKeyDown,
}: {
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
  onKeyDown?: (event: ReactKeyboardEvent<HTMLInputElement>) => void;
}) {
  return (
    <label className="makerdao-filter-control makerdao-filter-search-control">
      <span className="metric-label">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
      />
    </label>
  );
}

function normalizeChain(value: string): string {
  if (!value) return 'Ethereum';
  return value.toLowerCase() === 'ethereum' ? 'Ethereum' : value;
}

function shortAddress(value: string | null | undefined): string {
  if (!value) return 'System Internal';
  return value.length > 14 ? `${value.slice(0, 6)}...${value.slice(-4)}` : value;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'N/A';
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return new Date(timestamp).toLocaleString('zh-CN', { hour12: false });
}

function formatRelativeTime(value: string | null | undefined): { label: string; stale: boolean } {
  if (!value) return { label: '更新时间未知', stale: true };
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return { label: value, stale: true };

  const diffMs = Date.now() - timestamp;
  const absMs = Math.abs(diffMs);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;

  if (absMs < minute) return { label: '刚刚更新', stale: false };
  if (absMs < hour) return { label: `${Math.round(absMs / minute)} 分钟前`, stale: false };
  if (absMs < day) return { label: `${Math.round(absMs / hour)} 小时前`, stale: false };
  return { label: `${Math.round(absMs / day)} 天前`, stale: diffMs > day };
}

function toNumber(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = typeof value === 'number' ? value : Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatScientificNumber(value: string | number | null | undefined, digits = 2): string {
  const number = toNumber(value);
  if (!Number.isFinite(number)) return '--';
  if (number === 0) return '0';
  return number.toExponential(digits);
}

function formatScientificUsd(value: string | number | null | undefined): string {
  return `$${formatScientificNumber(value, 2)}`;
}

function formatUsdFixed(value: string | number | null | undefined): string {
  const number = toNumber(value);
  if (!Number.isFinite(number)) return '--';
  return `$${number.toFixed(2)}`;
}

function getCollateralPriceKey(item: MakerDaoPositionListItem): string {
  return (item.collateral_token_address || '').trim().toLowerCase();
}

function getCollateralPriceAsset(item: MakerDaoPositionListItem): string {
  return (item.collateral_token_address || '').trim();
}

function isPriceFailureCached(key: string): boolean {
  const failedAt = priceFailureCache.get(key);
  if (!failedAt) return false;
  if (Date.now() - failedAt < PRICE_FAILURE_TTL_MS) return true;
  priceFailureCache.delete(key);
  return false;
}

function formatLiquidationBuffer(
  currentPrice: number | null | undefined,
  liquidationPrice: string | number | null | undefined,
): string {
  const price = Number(currentPrice);
  const liquidation = toNumber(liquidationPrice);
  if (!Number.isFinite(price) || price <= 0 || !Number.isFinite(liquidation)) return '--';
  return `${(((price - liquidation) / price) * 100).toFixed(2)}%`;
}

function formatPercentFixed(value: string | number | null | undefined, multiplier = 1): string {
  const number = toNumber(value) * multiplier;
  if (!Number.isFinite(number)) return '--';
  return `${number.toFixed(2)}%`;
}

function formatHealthFactor(
  healthFactor: string | number | null | undefined,
  debtValue: string | number | null | undefined,
): string {
  const raw = String(healthFactor ?? '')
    .trim()
    .toLowerCase();
  const debt = Number(debtValue);
  const health = Number(healthFactor);
  if (debt === 0 && (raw === '0' || health === 0)) return '无风险';
  if (raw === 'inf' || raw === 'infinity') return '无风险';
  const number = toNumber(healthFactor);
  if (!Number.isFinite(number) || number > 5) return '无风险';
  return number.toFixed(2);
}

function getHealthFactorValue(
  healthFactor: string | number | null | undefined,
  debtValue: string | number | null | undefined,
): number {
  const raw = String(healthFactor ?? '')
    .trim()
    .toLowerCase();
  const debt = Number(debtValue);
  const numericValue = Number(healthFactor);

  if (raw === 'inf' || raw === 'infinity') return Infinity;
  if (debt === 0 && numericValue === 0) return Infinity;
  if (Number.isFinite(numericValue)) return numericValue;

  const fallback = toNumber(healthFactor);
  return Number.isFinite(fallback) ? fallback : 0;
}

function shouldBlinkHealthFactorInfinity(item: MakerDaoPositionListItem): boolean {
  if (formatHealthFactor(item.health_factor, item.debt_value_usd) !== '无风险') return false;

  const debt = toNumber(item.debt_value_usd);
  const collateral = toNumber(item.collateral_value_usd);
  if (debt === 0 && collateral > 0) return true;

  const parsed = Number(item.health_factor);
  if (Number.isFinite(parsed) && parsed > 5) return false;

  return true;
}

function positionRiskClass(item: MakerDaoPositionListItem): string {
  if (!item.is_healthy) return 'makerdao-risk-danger';
  const healthFactor = getHealthFactorValue(item.health_factor, item.debt_value_usd);
  if (toNumber(item.debt_value_usd) <= 0) return 'makerdao-risk-neutral';
  if (healthFactor <= 1.2) return 'makerdao-risk-watch';
  return 'makerdao-risk-safe';
}

function positionRiskLabel(item: MakerDaoPositionListItem): string {
  if (!item.is_healthy) return '高风险';
  if (toNumber(item.debt_value_usd) <= 0) return '无活跃债务';
  if (getHealthFactorValue(item.health_factor, item.debt_value_usd) <= 1.2) return '需观察';
  return '健康';
}

function getMakerDaoHealthFactorTone(
  value: number,
  display: string,
): {
  color: string;
  className: string;
  fontWeight: number;
} {
  if (display === '无风险' || value > 2) {
    return { color: '#22c55e', className: '', fontWeight: 800 };
  }
  if (value <= 1.1) {
    return { color: '#FFBB28', className: 'makerdao-hf-pulse', fontWeight: 900 };
  }
  if (value <= 1.5) {
    return { color: '#f59e0b', className: '', fontWeight: 800 };
  }
  return { color: '#e2e8f0', className: '', fontWeight: 700 };
}

function MakerDaoHealthFactorCell({ item }: { item: MakerDaoPositionListItem }) {
  const display = formatHealthFactor(item.health_factor, item.debt_value_usd);
  const value = getHealthFactorValue(item.health_factor, item.debt_value_usd);
  const tone = getMakerDaoHealthFactorTone(value, display);
  const className = [
    'right',
    'mono',
    'makerdao-health-factor-cell',
    tone.className,
    display === '无风险' && shouldBlinkHealthFactorInfinity(item) ? 'makerdao-hf-pulse-safe' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <td
      className={className}
      style={{
        color: tone.color,
        fontWeight: tone.fontWeight,
      }}
    >
      {display}
    </td>
  );
}

function MakerDaoHealthFactorInfoButton() {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [panelStyle, setPanelStyle] = useState<{ top: number; left: number; width: number }>({
    top: 0,
    left: 16,
    width: 360,
  });

  useEffect(() => {
    if (!open) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  useLayoutEffect(() => {
    if (!open) return;

    const updatePosition = () => {
      const triggerRect = wrapRef.current?.getBoundingClientRect();
      if (!triggerRect) return;

      const viewportPadding = 16;
      const maxWidth = Math.min(360, window.innerWidth - viewportPadding * 2);
      const panelWidth = Math.max(260, maxWidth);
      const desiredLeft = triggerRect.left + triggerRect.width / 2 - panelWidth / 2;
      const clampedLeft = Math.min(
        Math.max(viewportPadding, desiredLeft),
        window.innerWidth - panelWidth - viewportPadding,
      );

      setPanelStyle({
        top: Math.min(triggerRect.bottom + 8, window.innerHeight - 24),
        left: clampedLeft,
        width: panelWidth,
      });
    };

    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);

    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [open]);

  return (
    <div ref={wrapRef} className="makerdao-info-button-wrap">
      <button
        type="button"
        className={`makerdao-info-button ${open ? 'active' : ''}`}
        onClick={() => setOpen((value) => !value)}
        title="查看指标解释"
        aria-label="查看健康因子显示说明"
      >
        ?
      </button>

      {open ? (
        <div
          className="makerdao-info-panel"
          style={{
            top: `${panelStyle.top}px`,
            left: `${panelStyle.left}px`,
            width: `${panelStyle.width}px`,
          }}
        >
          <div className="makerdao-info-panel-title">健康因子显示说明</div>
          {HEALTH_FACTOR_EXPLAIN_ITEMS.map((item) => (
            <div key={item.term} className="makerdao-info-panel-item">
              <div className="makerdao-info-panel-term">{item.term}</div>
              <div className="makerdao-info-panel-meaning">含义：{item.meaning}</div>
              <div className="makerdao-info-panel-risk">观察重点：{item.riskHint}</div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

interface MakerDaoPositionsTableProps {
  items: MakerDaoPositionListItem[];
  collateralPrices: Record<string, number>;
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  pageInput: string;
  hasPreviousPage: boolean;
  hasNextPage: boolean;
  expandedPositionUid: string | null;
  onExpandedPositionChange: (uid: string | null) => void;
  onPageChange: (page: number) => void;
  onPageInputChange: (value: string) => void;
  onPageJump: () => void;
}

function MakerDaoPositionsTable({
  items,
  collateralPrices,
  page,
  pageSize,
  total,
  totalPages,
  pageInput,
  hasPreviousPage,
  hasNextPage,
  expandedPositionUid,
  onExpandedPositionChange,
  onPageChange,
  onPageInputChange,
  onPageJump,
}: MakerDaoPositionsTableProps) {
  const [copiedKey, setCopiedKey] = useState('');

  const handleCopyAddress = async (
    event: ReactMouseEvent<HTMLButtonElement>,
    value: string | null | undefined,
    key: string,
  ) => {
    event.stopPropagation();
    const text = value?.trim();
    if (!text) return;

    const copied = await copyToClipboard(text);
    if (!copied) return;

    setCopiedKey(key);
    window.setTimeout(() => {
      setCopiedKey((current) => (current === key ? '' : current));
    }, 1400);
  };

  return (
    <>
      <div className="table-wrap makerdao-position-table-wrap">
        <table className="pos-table makerdao-position-main-table">
          <thead>
            <tr>
              <th>排名</th>
              <th>URN</th>
              <th>Ilk</th>
              <th className="right">抵押价值</th>
              <th className="right">债务价值</th>
              <th className="right">
                <span className="makerdao-hf-heading">
                  <span>健康因子</span>
                  <MakerDaoHealthFactorInfoButton />
                </span>
              </th>
              <th className="right">清算价格</th>
              <th className="right">价格缓冲</th>
              <th className="center">状态</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => {
              const isExpanded = expandedPositionUid === item.position_uid;
              const currentPrice = collateralPrices[getCollateralPriceKey(item)];
              const liquidationBuffer = formatLiquidationBuffer(
                currentPrice,
                item.liquidation_price_usd,
              );
              const healthFactorValue = getHealthFactorValue(
                item.health_factor,
                item.debt_value_usd,
              );
              const rowClassName = [
                'makerdao-position-row',
                !item.is_healthy || healthFactorValue <= 1.2 ? 'makerdao-risk-row' : '',
              ]
                .filter(Boolean)
                .join(' ');
              return (
                <Fragment key={item.position_uid}>
                  <tr
                    className={rowClassName}
                    onClick={() => onExpandedPositionChange(isExpanded ? null : item.position_uid)}
                  >
                    <td>{(page - 1) * pageSize + index + 1}</td>
                    <td>
                      <div className="makerdao-position-address-cell">
                        <span className="mono" title={item.urn_address}>
                          {shortAddress(item.urn_address)}
                        </span>
                        {item.urn_address ? (
                          <button
                            type="button"
                            className="makerdao-address-copy-btn"
                            onClick={(event) =>
                              void handleCopyAddress(event, item.urn_address, item.position_uid)
                            }
                            title={`复制 ${item.urn_address}`}
                          >
                            {copiedKey === item.position_uid ? '已复制' : '复制'}
                          </button>
                        ) : null}
                        <span className="makerdao-position-scope">
                          {item.position_scope === 'system'
                            ? '系统仓位'
                            : `Vault #${item.vault_id ?? '--'}`}
                        </span>
                      </div>
                    </td>
                    <td>
                      <div className="makerdao-vault-cell">
                        <strong>{item.ilk || '--'}</strong>
                        <span>{item.collateral_symbol || item.vault_type || '--'}</span>
                      </div>
                    </td>
                    <td
                      className="right mono"
                      title={formatScientificUsd(item.collateral_value_usd)}
                    >
                      {formatScientificUsd(item.collateral_value_usd)}
                    </td>
                    <td className="right mono" title={formatScientificUsd(item.debt_value_usd)}>
                      {formatScientificUsd(item.debt_value_usd)}
                    </td>
                    <MakerDaoHealthFactorCell item={item} />
                    <td className="right mono" title={formatUsdFixed(item.liquidation_price_usd)}>
                      {formatUsdFixed(item.liquidation_price_usd)}
                    </td>
                    <td className="right mono" title={liquidationBuffer}>
                      {liquidationBuffer}
                    </td>
                    <td className="center">
                      <span className={`badge ${positionRiskClass(item)}`}>
                        {positionRiskLabel(item)}
                      </span>
                    </td>
                  </tr>
                  {isExpanded ? (
                    <tr className="makerdao-detail-row">
                      <td colSpan={9}>
                        <div className="makerdao-detail-panel">
                          <div className="makerdao-detail-grid">
                            <div className="makerdao-detail-item">
                              <span className="makerdao-detail-label">Position UID</span>
                              <span className="makerdao-detail-value mono">
                                {item.position_uid}
                              </span>
                            </div>
                            <div className="makerdao-detail-item">
                              <span className="makerdao-detail-label">URN 地址</span>
                              <span className="makerdao-detail-value mono">
                                {item.urn_address || '--'}
                              </span>
                            </div>
                            <div className="makerdao-detail-item">
                              <span className="makerdao-detail-label">Owner 地址</span>
                              <span className="makerdao-detail-value mono">
                                {item.owner_address || '--'}
                              </span>
                            </div>
                            <div className="makerdao-detail-item">
                              <span className="makerdao-detail-label">Proxy 地址</span>
                              <span className="makerdao-detail-value mono">
                                {item.proxy_address || '--'}
                              </span>
                            </div>
                            <div className="makerdao-detail-item">
                              <span className="makerdao-detail-label">抵押 Token</span>
                              <span className="makerdao-detail-value mono">
                                {item.collateral_token_address || '--'}
                              </span>
                            </div>
                            <div className="makerdao-detail-item">
                              <span className="makerdao-detail-label">债务 Token</span>
                              <span className="makerdao-detail-value mono">
                                {item.debt_token_address || '--'}
                              </span>
                            </div>
                            <div className="makerdao-detail-item">
                              <span className="makerdao-detail-label">抵押数量</span>
                              <span className="makerdao-detail-value">
                                {formatScientificNumber(item.collateral_amount, 4)}{' '}
                                {item.collateral_symbol || ''}
                              </span>
                            </div>
                            <div className="makerdao-detail-item">
                              <span className="makerdao-detail-label">债务数量</span>
                              <span className="makerdao-detail-value">
                                {formatScientificNumber(item.debt_amount, 4)} {item.debt_symbol}
                              </span>
                            </div>
                            <div className="makerdao-detail-item">
                              <span className="makerdao-detail-label">清算率</span>
                              <span className="makerdao-detail-value">
                                {formatPercentFixed(item.liquidation_ratio, 100)}
                              </span>
                            </div>
                            <div className="makerdao-detail-item">
                              <span className="makerdao-detail-label">更新时间</span>
                              <span className="makerdao-detail-value">
                                {formatDateTime(item.snapshot_at)}
                              </span>
                            </div>
                            <div className="makerdao-detail-item">
                              <span className="makerdao-detail-label">区块时间</span>
                              <span className="makerdao-detail-value">
                                {formatDateTime(item.block_timestamp)} · #
                                {item.block_number ?? '--'}
                              </span>
                            </div>
                            <div className="makerdao-detail-item">
                              <span className="makerdao-detail-label">数据来源</span>
                              <span className="makerdao-detail-value">{item.data_source}</span>
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="makerdao-position-table-footer">
        <span>
          共 {total.toLocaleString()} 条，当前第 {page} / {totalPages} 页
        </span>
        <div className="makerdao-position-table-actions">
          <label className="makerdao-page-jump">
            <span>页码</span>
            <input
              type="number"
              min="1"
              max={totalPages}
              value={pageInput}
              onChange={(event) => onPageInputChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  onPageJump();
                }
              }}
            />
          </label>
          <button
            type="button"
            className="makerdao-switch-btn"
            disabled={!hasPreviousPage}
            onClick={() => onPageChange(Math.max(page - 1, 1))}
          >
            上一页
          </button>
          <button type="button" className="makerdao-switch-btn" onClick={onPageJump}>
            跳转
          </button>
          <button
            type="button"
            className="makerdao-switch-btn"
            disabled={!hasNextPage}
            onClick={() => onPageChange(Math.min(page + 1, totalPages))}
          >
            下一页
          </button>
        </div>
      </div>
    </>
  );
}

function resolveIlkGroup(item: MakerDaoIlkItem): Exclude<IlkGroup, 'all'> {
  const ilk = String(item.ilk || '').toUpperCase();
  const symbol = String(item.gem_symbol || '').toUpperCase();

  if (ilk.startsWith('RWA')) return 'rwa';
  if (ilk.startsWith('DIRECT')) return 'direct';
  if (!item.gem_address) return 'system';
  if (
    ilk.startsWith('ETH') ||
    ilk.startsWith('WBTC') ||
    symbol === 'ETH' ||
    symbol === 'WETH' ||
    symbol === 'WBTC' ||
    symbol.includes('STETH') ||
    symbol.includes('RETH') ||
    symbol.includes('CBETH')
  ) {
    return 'native';
  }
  if (
    symbol.includes('USDC') ||
    symbol.includes('USDT') ||
    symbol.includes('GUSD') ||
    symbol.includes('USDP') ||
    symbol.includes('DAI') ||
    ilk.startsWith('PSM')
  ) {
    return 'stable';
  }
  if (symbol.includes('LP') || ilk.includes('UNIV2') || ilk.includes('GUNIV3')) return 'lp';
  return 'other';
}

function buildExplorerUrl(chain: string, address: string | null | undefined): string | null {
  if (!address) return null;
  const normalizedChain = chain.toLowerCase();
  const baseUrl =
    normalizedChain === 'ethereum' || normalizedChain === 'mainnet'
      ? 'https://etherscan.io/address/'
      : 'https://etherscan.io/address/';
  return `${baseUrl}${address}`;
}

function normalizeIlk(item: MakerDaoIlkItem, chain: string): MakerDaoIlkView {
  const group = resolveIlkGroup(item);
  const relative = formatRelativeTime(item.updated_at);
  const key = item.ilk || item.gem_address || item.gem_symbol || 'unknown';

  return {
    ...item,
    key,
    group,
    groupLabel: GROUP_LABELS[group],
    contractStatus: item.gem_address ? 'deployed' : 'internal',
    searchText: [item.ilk, item.gem_symbol, item.vault_type, item.gem_address]
      .filter(Boolean)
      .join(' ')
      .toLowerCase(),
    updatedAtLabel: relative.label,
    updatedAtTitle: formatDateTime(item.updated_at),
    isStale: relative.stale,
    explorerUrl: buildExplorerUrl(chain, item.gem_address),
  };
}

function compareIlks(a: MakerDaoIlkView, b: MakerDaoIlkView, sortMode: SortMode): number {
  if (sortMode === 'updated_desc') {
    const aTime = Date.parse(a.updated_at);
    const bTime = Date.parse(b.updated_at);
    if (Number.isNaN(aTime) && Number.isNaN(bTime)) return a.key.localeCompare(b.key);
    if (Number.isNaN(aTime)) return 1;
    if (Number.isNaN(bTime)) return -1;
    return bTime - aTime;
  }
  return (a.ilk || a.key).localeCompare(b.ilk || b.key);
}

export function MakerDaoMarketPage({ active }: MakerDaoMarketPageProps) {
  const [ilks, setIlks] = useState<MakerDaoIlkItem[]>([]);
  const [chain, setChain] = useState('Ethereum');
  const [protocol, setProtocol] = useState('MakerDAO');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [sortMode, setSortMode] = useState<SortMode>('alpha');
  const [groupFilter, setGroupFilter] = useState<IlkGroup>('all');
  const [contractStatusFilter, setContractStatusFilter] = useState<ContractStatusFilter>('all');
  const [page, setPage] = useState(1);
  const [pageInput, setPageInput] = useState('1');
  const [reloadNonce, setReloadNonce] = useState(0);
  const [meta, setMeta] = useState<AggregatedRequestMeta>(EMPTY_META);
  const [positionsData, setPositionsData] = useState<MakerDaoPositionsResponse | null>(null);
  const [positionsLoading, setPositionsLoading] = useState(false);
  const [positionsError, setPositionsError] = useState('');
  const [positionsPage, setPositionsPage] = useState(1);
  const [positionsPageInput, setPositionsPageInput] = useState('1');
  const [positionScope, setPositionScope] = useState<PositionScopeFilter>('all');
  const [positionHealth, setPositionHealth] = useState<PositionHealthFilter>('all');
  const [positionIlkInput, setPositionIlkInput] = useState('');
  const [positionIlk, setPositionIlk] = useState('');
  const [positionSortBy, setPositionSortBy] = useState<PositionSortBy>('collateral_value_usd');
  const [positionOrder, setPositionOrder] = useState<PositionOrder>('desc');
  const [includeEmptyPositions, setIncludeEmptyPositions] = useState(false);
  const [positionsReloadNonce, setPositionsReloadNonce] = useState(0);
  const [positionsMeta, setPositionsMeta] = useState<AggregatedRequestMeta>(EMPTY_META);
  const [expandedPositionUid, setExpandedPositionUid] = useState<string | null>(null);
  const [collateralPrices, setCollateralPrices] = useState<Record<string, number>>({});

  useEffect(() => {
    if (!active) return;
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError('');

      try {
        const result = await fetchMakerDaoIlksWithMeta();
        if (cancelled) return;
        setIlks(result.data.ilks ?? []);
        setChain(normalizeChain(result.data.chain));
        setProtocol(normalizeProtocol(result.data.protocol));
        setMeta(mergeRequestMetas([result.meta]));
      } catch (loadError) {
        if (cancelled) return;
        setIlks([]);
        setMeta(EMPTY_META);
        setError(loadError instanceof Error ? loadError.message : '无法加载 MakerDAO 资产元数据');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [active, reloadNonce]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;

    const loadPositions = async () => {
      setPositionsLoading(true);
      setPositionsError('');

      try {
        const result = await fetchMakerDaoPositionsWithMeta({
          page: positionsPage,
          pageSize: POSITIONS_PAGE_SIZE,
          sortBy: positionSortBy,
          order: positionOrder,
          positionScope,
          ilk: positionIlk,
          isHealthy: positionHealth === 'all' ? null : positionHealth === 'healthy' ? true : false,
          includeEmpty: includeEmptyPositions,
        });
        if (cancelled) return;
        setPositionsData(result.data);
        setPositionsMeta(mergeRequestMetas([result.meta]));
      } catch (loadError) {
        if (cancelled) return;
        setPositionsData(null);
        setPositionsMeta(EMPTY_META);
        setPositionsError(
          loadError instanceof Error ? loadError.message : '无法加载 MakerDAO 仓位总览',
        );
      } finally {
        if (!cancelled) setPositionsLoading(false);
      }
    };

    void loadPositions();

    return () => {
      cancelled = true;
    };
  }, [
    active,
    includeEmptyPositions,
    positionHealth,
    positionIlk,
    positionOrder,
    positionScope,
    positionSortBy,
    positionsPage,
    positionsReloadNonce,
  ]);

  const views = useMemo(() => ilks.map((item) => normalizeIlk(item, chain)), [chain, ilks]);
  const deployedCount = views.filter((item) => item.contractStatus === 'deployed').length;
  const internalCount = views.length - deployedCount;
  const staleCount = views.filter((item) => item.isStale).length;

  const groupCounts = useMemo(() => {
    return views.reduce<Record<Exclude<IlkGroup, 'all'>, number>>(
      (counts, item) => {
        counts[item.group] += 1;
        return counts;
      },
      {
        native: 0,
        rwa: 0,
        direct: 0,
        stable: 0,
        lp: 0,
        system: 0,
        other: 0,
      },
    );
  }, [views]);

  const filteredViews = useMemo(() => {
    const query = searchTerm.trim().toLowerCase();
    return views
      .filter((item) => (!query ? true : item.searchText.includes(query)))
      .filter((item) => (groupFilter === 'all' ? true : item.group === groupFilter))
      .filter((item) =>
        contractStatusFilter === 'all' ? true : item.contractStatus === contractStatusFilter,
      )
      .sort((a, b) => compareIlks(a, b, sortMode));
  }, [contractStatusFilter, groupFilter, searchTerm, sortMode, views]);

  useEffect(() => {
    setPage(1);
  }, [contractStatusFilter, groupFilter, searchTerm, sortMode]);

  useEffect(() => {
    setPositionsPage(1);
    setExpandedPositionUid(null);
  }, [
    includeEmptyPositions,
    positionHealth,
    positionIlk,
    positionOrder,
    positionScope,
    positionSortBy,
  ]);

  const totalPages = Math.max(1, Math.ceil(filteredViews.length / METADATA_PAGE_SIZE));
  const normalizedPage = Math.min(page, totalPages);
  const pageStart = (normalizedPage - 1) * METADATA_PAGE_SIZE;
  const visibleCards = filteredViews.slice(pageStart, pageStart + METADATA_PAGE_SIZE);
  const hasNextPage = normalizedPage < totalPages;
  const hasPreviousPage = normalizedPage > 1;

  useEffect(() => {
    setPageInput(String(normalizedPage));
  }, [normalizedPage]);

  const goToPage = () => {
    const parsed = Number.parseInt(pageInput, 10);
    if (!Number.isFinite(parsed)) {
      setPageInput(String(normalizedPage));
      return;
    }
    setPage(Math.min(Math.max(parsed, 1), totalPages));
  };

  const positionsTotalPages = Math.max(
    1,
    Math.ceil((positionsData?.total ?? 0) / POSITIONS_PAGE_SIZE),
  );
  const normalizedPositionsPage = Math.min(positionsPage, positionsTotalPages);
  const hasPreviousPositionsPage = normalizedPositionsPage > 1;
  const hasNextPositionsPage = normalizedPositionsPage < positionsTotalPages;

  useEffect(() => {
    setPositionsPageInput(String(normalizedPositionsPage));
  }, [normalizedPositionsPage]);

  const goToPositionsPage = () => {
    const parsed = Number.parseInt(positionsPageInput, 10);
    if (!Number.isFinite(parsed)) {
      setPositionsPageInput(String(normalizedPositionsPage));
      return;
    }
    setPositionsPage(Math.min(Math.max(parsed, 1), positionsTotalPages));
  };

  const positionItems = useMemo(() => positionsData?.items ?? [], [positionsData]);
  const positionAggregates = positionsData?.aggregates;

  useEffect(() => {
    if (!active || !positionItems.length) {
      setCollateralPrices({});
      return;
    }

    let cancelled = false;
    const priceTargets = Array.from(
      new Map(
        positionItems
          .map((item) => {
            const key = getCollateralPriceKey(item);
            const asset = getCollateralPriceAsset(item);
            return key && asset && !isPriceFailureCached(key) ? [key, asset] : null;
          })
          .filter((entry): entry is [string, string] => Boolean(entry)),
      ).entries(),
    );

    if (!priceTargets.length) {
      setCollateralPrices({});
      return;
    }

    const loadPrices = async () => {
      const entries = await Promise.all(
        priceTargets.map(async ([key, asset]) => {
          try {
            const result = await fetchAssetPriceWithMeta(asset, { chain: 'ethereum' });
            priceFailureCache.delete(key);
            return [key, result.data] as const;
          } catch {
            priceFailureCache.set(key, Date.now());
            return [key, null] as const;
          }
        }),
      );

      if (cancelled) return;
      setCollateralPrices((current) => {
        const next = { ...current };
        for (const [key, price] of entries) {
          if (price === null) {
            delete next[key];
          } else {
            next[key] = price;
          }
        }
        return next;
      });
    };

    void loadPrices();

    return () => {
      cancelled = true;
    };
  }, [active, positionItems]);

  return (
    <div className="makerdao-dashboard makerdao-market-dashboard">
      <PageHero
        title="MakerDAO 宏观市场评估"
        subtitle="当前仅展示 ilk 基础元数据，用于抵押资产导航、合约地址溯源与数据更新时间追踪。"
      />

      <section className="makerdao-asset-navigator">
        <div className="makerdao-asset-navigator-header">
          <div>
            <span className="makerdao-market-kicker">Ilk Metadata Navigator</span>
            <h2 className="makerdao-market-title">协议抵押资产导航</h2>
            <p className="makerdao-market-copy">
              展示资产名称、Vault 类型、合约地址和更新时间；不展示利率、限额或清算参数。
            </p>
          </div>
          <div className="makerdao-asset-navigator-meta">
            <span className="badge green-badge">{chain}</span>
            <span className="badge badge-brand-soft">{protocol}</span>
            <ChartDataStatus meta={meta} />
            <button
              type="button"
              className="makerdao-refresh-btn"
              onClick={() => setReloadNonce((value) => value + 1)}
              disabled={loading}
              title="刷新元数据"
            >
              ↻
            </button>
          </div>
        </div>

        <div className="summary-grid makerdao-metadata-summary-grid">
          <div className="metric-box">
            <span className="metric-label">Ilk 总数</span>
            <span className="metric-value blue">{views.length.toLocaleString()}</span>
          </div>
          <div className="metric-box">
            <span className="metric-label">已部署合约</span>
            <span className="metric-value green">{deployedCount.toLocaleString()}</span>
          </div>
          <div className="metric-box">
            <span className="metric-label">系统内部账户</span>
            <span className="metric-value">{internalCount.toLocaleString()}</span>
          </div>
          <div className="metric-box">
            <span className="metric-label">超过 24h 未更新</span>
            <span className={`metric-value ${staleCount > 0 ? 'red' : 'green'}`}>
              {staleCount.toLocaleString()}
            </span>
          </div>
        </div>

        <div className="makerdao-metadata-groups">
          {GROUP_OPTIONS.map((item) => (
            <button
              key={item.value}
              type="button"
              className={groupFilter === item.value ? 'active' : ''}
              onClick={() => setGroupFilter(item.value)}
            >
              <span>{item.value === 'all' ? 'All' : item.label}</span>
              <strong>
                {item.value === 'all'
                  ? views.length.toLocaleString()
                  : groupCounts[item.value as Exclude<IlkGroup, 'all'>]}
              </strong>
            </button>
          ))}
        </div>

        <div className="makerdao-metadata-filters">
          <MakerDaoSearchControl
            label="搜索 Ilk / Symbol"
            value={searchTerm}
            onChange={setSearchTerm}
            placeholder="ETH-A / RWA / WBTC..."
          />

          <MakerDaoSegmentedControl
            label="合约状态"
            value={contractStatusFilter}
            options={CONTRACT_STATUS_OPTIONS}
            ariaLabel="MakerDAO ilk contract status filter"
            onChange={setContractStatusFilter}
          />

          <MakerDaoSegmentedControl
            label="排序"
            value={sortMode}
            options={METADATA_SORT_OPTIONS}
            ariaLabel="MakerDAO ilk sort mode"
            onChange={setSortMode}
          />
        </div>

        {loading ? (
          <div className="makerdao-parameter-empty">
            <div className="spinner"></div>
          </div>
        ) : null}

        {!loading && error ? (
          <div className="makerdao-notice makerdao-notice-warn">
            <strong>无法加载 MakerDAO 资产元数据</strong>
            <span>{error}</span>
          </div>
        ) : null}

        {!loading && !error && !visibleCards.length ? (
          <div className="makerdao-parameter-empty">没有匹配当前筛选条件的资产元数据</div>
        ) : null}

        {!loading && !error && visibleCards.length ? (
          <>
            <div className="makerdao-metadata-card-grid">
              {visibleCards.map((item) => (
                <article key={item.key} className="makerdao-metadata-card">
                  <div className="makerdao-metadata-card-head">
                    <div className="makerdao-asset-token">
                      <span>{(item.gem_symbol || item.ilk || '?').slice(0, 3)}</span>
                    </div>
                    <div className="makerdao-asset-title">
                      <strong>{item.gem_symbol || 'System'}</strong>
                      <span>{item.ilk || 'N/A'}</span>
                    </div>
                    <span className="makerdao-asset-ilk">{item.vault_type || 'vault'}</span>
                  </div>

                  <div className="makerdao-metadata-group-row">
                    <span className="badge badge-brand-soft">{item.groupLabel}</span>
                    <span
                      className={`badge ${item.contractStatus === 'deployed' ? 'green-badge' : 'makerdao-risk-neutral'}`}
                    >
                      {item.contractStatus === 'deployed' ? '已部署合约' : 'System Internal'}
                    </span>
                  </div>

                  {item.explorerUrl ? (
                    <a
                      className="makerdao-metadata-address"
                      href={item.explorerUrl}
                      target="_blank"
                      rel="noreferrer"
                      title={item.gem_address || undefined}
                    >
                      <span className="mono">{shortAddress(item.gem_address)}</span>
                      <strong>打开 ↗</strong>
                    </a>
                  ) : (
                    <div className="makerdao-metadata-address makerdao-metadata-address-muted">
                      <span>System Internal</span>
                      <strong>无外部合约</strong>
                    </div>
                  )}

                  <div className={`makerdao-metadata-time ${item.isStale ? 'stale' : ''}`}>
                    <span>{item.isStale ? '!' : '●'}</span>
                    <div>
                      <strong>{item.updatedAtLabel}</strong>
                      <small>{item.updatedAtTitle}</small>
                    </div>
                  </div>
                </article>
              ))}
            </div>

            <div className="makerdao-parameter-footer">
              <span>
                正在展示 {visibleCards.length.toLocaleString()} /{' '}
                {filteredViews.length.toLocaleString()} 个匹配资产，共{' '}
                {views.length.toLocaleString()} 个 ilk。第 {normalizedPage} / {totalPages} 页
              </span>
              <div className="makerdao-pagination-controls">
                <button
                  type="button"
                  className="makerdao-page-btn"
                  disabled={!hasPreviousPage}
                  onClick={() => setPage((current) => Math.max(current - 1, 1))}
                >
                  上一页
                </button>
                <label className="makerdao-page-jump">
                  <span>页码</span>
                  <input
                    type="number"
                    min="1"
                    max={totalPages}
                    value={pageInput}
                    onChange={(event) => setPageInput(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        goToPage();
                      }
                    }}
                  />
                </label>
                <button type="button" className="makerdao-page-btn" onClick={goToPage}>
                  跳转
                </button>
                <button
                  type="button"
                  className="makerdao-page-btn"
                  disabled={!hasNextPage}
                  onClick={() => setPage((current) => Math.min(current + 1, totalPages))}
                >
                  下一页
                </button>
              </div>
            </div>
          </>
        ) : null}
      </section>

      <section className="makerdao-positions-overview">
        <div className="makerdao-asset-navigator-header">
          <div>
            <span className="makerdao-market-kicker">Positions Overview</span>
            <h2 className="makerdao-market-title">MakerDAO 仓位总览</h2>
            <p className="makerdao-market-copy">
              基于当前仓位缓存展示普通 Vault 与系统 urn 的抵押、债务、健康因子和清算风险。
            </p>
          </div>
          <div className="makerdao-asset-navigator-meta">
            <span className="badge green-badge">{positionsData?.chain || chain}</span>
            <span className="badge badge-brand-soft">{positionsData?.protocol || protocol}</span>
            <ChartDataStatus meta={positionsMeta} />
            <button
              type="button"
              className="makerdao-refresh-btn"
              onClick={() => setPositionsReloadNonce((value) => value + 1)}
              disabled={positionsLoading}
              title="刷新仓位总览"
            >
              ↻
            </button>
          </div>
        </div>

        <div className="summary-grid makerdao-positions-summary-grid">
          <div className="metric-box">
            <span className="metric-label">总仓位数</span>
            <span className="metric-value blue">
              {(positionAggregates?.total_positions ?? 0).toLocaleString()}
            </span>
          </div>
          <div className="metric-box">
            <span className="metric-label">普通 Vault</span>
            <span className="metric-value">
              {(positionAggregates?.user_positions ?? 0).toLocaleString()}
            </span>
          </div>
          <div className="metric-box">
            <span className="metric-label">系统仓位</span>
            <span className="metric-value green">
              {(positionAggregates?.system_positions ?? 0).toLocaleString()}
            </span>
          </div>
          <div className="metric-box">
            <span className="metric-label">非健康仓位</span>
            <span
              className={`metric-value ${(positionAggregates?.unhealthy_positions ?? 0) > 0 ? 'red' : 'green'}`}
            >
              {(positionAggregates?.unhealthy_positions ?? 0).toLocaleString()}
            </span>
          </div>
          <div className="metric-box">
            <span className="metric-label">总抵押价值</span>
            <span className="metric-value green">
              {formatScientificUsd(positionAggregates?.total_collateral_value_usd)}
            </span>
          </div>
          <div className="metric-box">
            <span className="metric-label">总债务价值</span>
            <span className="metric-value red">
              {formatScientificUsd(positionAggregates?.total_debt_value_usd)}
            </span>
          </div>
        </div>

        <div className="makerdao-positions-filters makerdao-positions-filter-stack">
          <div className="makerdao-positions-filter-row">
            <MakerDaoSearchControl
              label="ILK筛选"
              value={positionIlkInput}
              onChange={(value) => setPositionIlkInput(value.toUpperCase())}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  setPositionIlk(event.currentTarget.value.trim().toUpperCase());
                }
              }}
              placeholder="ETH-A / LITE-PSM... Enter"
            />

            <MakerDaoSegmentedControl
              label="排序字段"
              value={positionSortBy}
              options={POSITION_SORT_OPTIONS}
              ariaLabel="MakerDAO position sort field"
              onChange={setPositionSortBy}
            />

            <MakerDaoSegmentedControl
              label="排序方向"
              value={positionOrder}
              options={POSITION_ORDER_OPTIONS}
              ariaLabel="MakerDAO position sort order"
              onChange={setPositionOrder}
            />
          </div>

          <div className="makerdao-positions-filter-row">
            <MakerDaoSegmentedControl
              label="仓位范围"
              value={positionScope}
              options={POSITION_SCOPE_OPTIONS}
              ariaLabel="MakerDAO position scope filter"
              onChange={setPositionScope}
            />

            <MakerDaoSegmentedControl
              label="健康状态"
              value={positionHealth}
              options={POSITION_HEALTH_OPTIONS}
              ariaLabel="MakerDAO position health filter"
              onChange={setPositionHealth}
            />

            <MakerDaoSegmentedControl
              label="空仓"
              value={includeEmptyPositions ? 'include' : 'exclude'}
              options={[
                { value: 'exclude', label: '排除空仓' },
                { value: 'include', label: '包含空仓' },
              ]}
              ariaLabel="MakerDAO include empty positions"
              onChange={(value) => setIncludeEmptyPositions(value === 'include')}
            />
          </div>
        </div>

        {positionsLoading ? (
          <div className="makerdao-parameter-empty">
            <div className="spinner"></div>
          </div>
        ) : null}

        {!positionsLoading && positionsError ? (
          <div className="makerdao-notice makerdao-notice-warn">
            <strong>无法加载 MakerDAO 仓位总览</strong>
            <span>{positionsError}</span>
          </div>
        ) : null}

        {!positionsLoading && !positionsError && !positionItems.length ? (
          <div className="makerdao-parameter-empty">没有匹配当前筛选条件的 MakerDAO 仓位</div>
        ) : null}

        {!positionsLoading && !positionsError && positionItems.length ? (
          <MakerDaoPositionsTable
            items={positionItems}
            collateralPrices={collateralPrices}
            page={normalizedPositionsPage}
            pageSize={POSITIONS_PAGE_SIZE}
            total={positionsData?.total ?? 0}
            totalPages={positionsTotalPages}
            pageInput={positionsPageInput}
            hasPreviousPage={hasPreviousPositionsPage}
            hasNextPage={hasNextPositionsPage}
            expandedPositionUid={expandedPositionUid}
            onExpandedPositionChange={setExpandedPositionUid}
            onPageChange={setPositionsPage}
            onPageInputChange={setPositionsPageInput}
            onPageJump={goToPositionsPage}
          />
        ) : null}
      </section>
    </div>
  );
}
