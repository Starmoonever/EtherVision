import { useEffect, useMemo, useState } from 'react';
import { fetchMakerDaoIlksWithMeta, type MakerDaoIlkItem } from '../../../api/makerdao';
import { mergeRequestMetas, type AggregatedRequestMeta } from '../../../api/requestMeta';
import { ChartDataStatus } from '../../../components/ChartAssist';
import { PageHero } from '../../../shared/components/PageHero';

interface MakerDaoMarketPageProps {
  active: boolean;
}

type SortMode = 'alpha' | 'updated_desc';
type ContractStatusFilter = 'all' | 'deployed' | 'internal';
type IlkGroup = 'all' | 'native' | 'rwa' | 'direct' | 'stable' | 'lp' | 'system' | 'other';

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

function normalizeProtocol(value: string): string {
  if (!value) return 'MakerDAO';
  return value.toLowerCase() === 'makerdao' ? 'MakerDAO' : value;
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
          <label className="makerdao-market-search">
            <span>搜索 Ilk / Symbol</span>
            <input
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="ETH-A / RWA / WBTC..."
            />
          </label>

          <label className="makerdao-market-select">
            <span>合约状态</span>
            <select
              value={contractStatusFilter}
              onChange={(event) =>
                setContractStatusFilter(event.target.value as ContractStatusFilter)
              }
            >
              <option value="all">全部状态</option>
              <option value="deployed">已部署合约</option>
              <option value="internal">系统内部账户</option>
            </select>
          </label>

          <label className="makerdao-market-select">
            <span>排序</span>
            <select
              value={sortMode}
              onChange={(event) => setSortMode(event.target.value as SortMode)}
            >
              <option value="alpha">按字母顺序</option>
              <option value="updated_desc">按最近更新时间</option>
            </select>
          </label>
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
    </div>
  );
}
