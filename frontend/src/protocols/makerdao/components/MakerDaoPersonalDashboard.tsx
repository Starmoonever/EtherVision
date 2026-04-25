import { Fragment, useEffect, useMemo, useState } from 'react';
import {
  fetchMakerDaoPositionWithMeta,
  type MakerDaoPositionAsset,
  type MakerDaoPositionResponse,
  type MakerDaoVaultPosition,
} from '../../../api/makerdao';
import { mergeRequestMetas, type AggregatedRequestMeta } from '../../../api/requestMeta';
import { ChartDataStatus } from '../../../components/ChartAssist';
import { copyToClipboard } from '../../../shared/utils/copyToClipboard';

interface MakerDaoPersonalDashboardProps {
  address: string;
}

function toNum(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatUsd(value: string | number | null | undefined): string {
  return `$${toNum(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatTokenAmount(value: string | number | null | undefined): string {
  const num = toNum(value);
  return num.toLocaleString(undefined, {
    minimumFractionDigits: num > 0 && num < 1 ? 6 : 2,
    maximumFractionDigits: num > 0 && num < 1 ? 6 : 2,
  });
}

function formatPercentRatio(value: string | number | null | undefined): string {
  const num = toNum(value);
  const percent = num <= 10 ? num * 100 : num;
  return `${percent.toFixed(2)}%`;
}

function formatHealthFactor(value: string | number | null | undefined): string {
  const raw = String(value ?? '')
    .trim()
    .toLowerCase();
  if (raw === 'inf' || raw === 'infinity' || raw === '∞') return '∞';
  const num = toNum(value);
  if (!Number.isFinite(num) || num >= 1e12) return '∞';
  if (num <= 0) return '--';
  return num.toFixed(2);
}

function healthTone(value: string | number | null | undefined): 'green' | 'blue' | 'red' {
  const hf = toNum(value);
  if (!Number.isFinite(hf) || hf >= 2) return 'green';
  if (hf >= 1.35) return 'blue';
  return 'red';
}

function getMakerHealthFactorValue(
  healthFactor: string | number | null | undefined,
  debtValueUsd: string | number | null | undefined,
): number {
  const raw = String(healthFactor ?? '')
    .trim()
    .toLowerCase();
  const debt = toNum(debtValueUsd);
  const numericValue = Number(healthFactor);

  if (raw === 'inf' || raw === 'infinity') return Infinity;
  if (debt === 0 && numericValue === 0) return Infinity;
  if (Number.isFinite(numericValue)) return numericValue;

  const fallback = toNum(healthFactor);
  return Number.isFinite(fallback) ? fallback : 0;
}

function formatMakerHealthFactor(
  healthFactor: string | number | null | undefined,
  debtValueUsd: string | number | null | undefined,
): string {
  const raw = String(healthFactor ?? '')
    .trim()
    .toLowerCase();
  const debt = toNum(debtValueUsd);
  const health = Number(healthFactor);

  if (debt === 0 && (raw === '0' || health === 0)) return '无风险';
  if (raw === 'inf' || raw === 'infinity') return '无风险';

  const value = getMakerHealthFactorValue(healthFactor, debtValueUsd);
  if (!Number.isFinite(value) || value > 5) return '无风险';
  if (value <= 0) return '--';
  return value.toFixed(2);
}

function shouldBlinkMakerHealthFactorInfinity(item: MakerDaoVaultPosition): boolean {
  if (formatMakerHealthFactor(item.health_factor, item.debt_value_usd) !== '无风险') return false;

  const debt = toNum(item.debt_value_usd);
  const collateral = toNum(item.collateral_value_usd);
  if (debt === 0 && collateral > 0) return true;

  const parsed = Number(item.health_factor);
  if (Number.isFinite(parsed) && parsed > 5) return false;

  return true;
}

function isNativeMakerHealthFactorInfinity(item: MakerDaoVaultPosition): boolean {
  if (formatMakerHealthFactor(item.health_factor, item.debt_value_usd) !== '无风险') return false;

  const raw = String(item.health_factor ?? '')
    .trim()
    .toLowerCase();
  if (raw === 'inf' || raw === 'infinity') return true;

  const debt = toNum(item.debt_value_usd);
  const collateral = toNum(item.collateral_value_usd);
  const parsed = Number(item.health_factor);
  return debt === 0 && parsed === 0 && collateral > 0;
}

function getMakerHealthFactorTone(value: number, display: string) {
  if (display === '无风险' || value > 2) {
    return { color: '#22c55e', className: '', fontWeight: 800 };
  }
  if (value <= 1.1) {
    return { color: '#FFBB28', className: 'justlend-hf-pulse', fontWeight: 900 };
  }
  if (value <= 1.5) {
    return { color: '#f59e0b', className: '', fontWeight: 800 };
  }
  return { color: '#e2e8f0', className: '', fontWeight: 700 };
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'N/A';
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return new Date(timestamp).toLocaleString('zh-CN', { hour12: false });
}

function shortAddress(value: string | null | undefined): string {
  if (!value) return '--';
  return value.length > 12 ? `${value.slice(0, 6)}…${value.slice(-4)}` : value;
}

function compactDataSource(value: string | null | undefined): string {
  const text = String(value || '').trim();
  return text || 'N/A';
}

function vaultKey(item: MakerDaoVaultPosition): string {
  return item.vault_uid || `${item.vault_id}-${item.urn_address}`;
}

function roleLabel(role: string): string {
  const normalized = role.trim().toLowerCase();
  if (normalized === 'collateral') return '抵押';
  if (normalized === 'debt' || normalized === 'borrow') return '债务';
  return role || '--';
}

function findWorstVault(positions: MakerDaoVaultPosition[]): MakerDaoVaultPosition | null {
  const activeDebtVaults = positions.filter((item) => toNum(item.debt_value_usd) > 0);
  const candidates = activeDebtVaults.length ? activeDebtVaults : positions;
  return candidates.reduce<MakerDaoVaultPosition | null>((worst, item) => {
    if (!worst) return item;
    const currentHf = toNum(item.health_factor);
    const worstHf = toNum(worst.health_factor);
    if (currentHf > 0 && (worstHf <= 0 || currentHf < worstHf)) return item;
    return worst;
  }, null);
}

function riskLabel(vault: MakerDaoVaultPosition | null): string {
  if (!vault) return '空仓位';
  if (toNum(vault.debt_value_usd) <= 0) return '无活跃债务';
  if (!vault.is_healthy) return '高风险';

  const hf = toNum(vault.health_factor);
  if (hf > 0 && hf < 1.35) return '需重点观察';
  if (hf > 0 && hf < 2) return '相对可控';
  return '相对稳健';
}

function riskToneClass(vault: MakerDaoVaultPosition | null): string {
  const label = riskLabel(vault);
  if (label === '高风险') return 'justlend-risk-danger';
  if (label === '需重点观察') return 'justlend-risk-watch';
  if (label === '空仓位' || label === '无活跃债务') return 'justlend-risk-neutral';
  return 'justlend-risk-safe';
}

export function MakerDaoPersonalDashboard({ address }: MakerDaoPersonalDashboardProps) {
  const [data, setData] = useState<MakerDaoPositionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expandedVaultKey, setExpandedVaultKey] = useState('');
  const [copiedKey, setCopiedKey] = useState('');
  const [vaultIdFilter, setVaultIdFilter] = useState('');
  const [ilkFilter, setIlkFilter] = useState('');
  const [meta, setMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });

  const normalizedVaultIdFilter = vaultIdFilter.trim();
  const normalizedIlkFilter = ilkFilter.trim();

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError('');

      try {
        const result = await fetchMakerDaoPositionWithMeta({
          address,
          includeEmpty: true,
        });
        if (cancelled) return;
        setData(result.data);
        setMeta(mergeRequestMetas([result.meta]));
      } catch (loadError) {
        if (cancelled) return;
        setData(null);
        setError(loadError instanceof Error ? loadError.message : '无法加载 MakerDAO 仓位');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    if (address) {
      void load();
    }

    return () => {
      cancelled = true;
    };
  }, [address]);

  const handleCopy = async (value: string | null | undefined, key: string) => {
    const text = value?.trim();
    if (!text) return;

    const copied = await copyToClipboard(text);
    if (!copied) return;

    setCopiedKey(key);
    window.setTimeout(() => {
      setCopiedKey((current) => (current === key ? '' : current));
    }, 1400);
  };

  const positions = data?.positions ?? [];
  const sortedPositions = useMemo(
    () =>
      [...positions].sort((a, b) => toNum(b.collateral_value_usd) - toNum(a.collateral_value_usd)),
    [positions],
  );
  const visiblePositions = useMemo(() => {
    return sortedPositions.filter((item) => {
      const vaultMatches =
        !normalizedVaultIdFilter || String(item.vault_id).includes(normalizedVaultIdFilter);
      const ilkText = `${item.ilk || ''} ${item.vault_type || ''}`.toLowerCase();
      const ilkMatches =
        !normalizedIlkFilter || ilkText.includes(normalizedIlkFilter.toLowerCase());
      return vaultMatches && ilkMatches;
    });
  }, [normalizedIlkFilter, normalizedVaultIdFilter, sortedPositions]);
  const summary = useMemo(() => {
    const totalCollateralUsd = positions.reduce(
      (sum, item) => sum + toNum(item.collateral_value_usd),
      0,
    );
    const totalDebtUsd = positions.reduce((sum, item) => sum + toNum(item.debt_value_usd), 0);
    const activeCollateralPositions = positions.filter(
      (item) => toNum(item.collateral_value_usd) !== 0,
    );
    const healthyCount = activeCollateralPositions.filter((item) => item.is_healthy).length;
    const worstVault = findWorstVault(positions);

    return {
      totalCollateralUsd,
      totalDebtUsd,
      healthyCount,
      activeCollateralCount: activeCollateralPositions.length,
      worstVault,
    };
  }, [positions]);

  if (loading) {
    return (
      <div className="card makerdao-loading-card">
        <div className="spinner"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <span className="card-title">MakerDAO 个人账户分析</span>
            <span className="badge green-badge">Ethereum</span>
          </div>
          <span className="address-badge">{shortAddress(address)}</span>
        </div>
        <div className="makerdao-notice makerdao-notice-warn">
          <strong>后端暂未返回可用 MakerDAO 仓位数据</strong>
          <span>{error}</span>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="card makerdao-loading-card">
        <span className="empty-text">暂无 MakerDAO 仓位数据</span>
      </div>
    );
  }

  const refreshedAtText = meta.lastUpdatedAt
    ? new Date(meta.lastUpdatedAt).toLocaleString('zh-CN', { hour12: false })
    : formatDateTime(positions[0]?.snapshot_at);
  const worstVault = summary.worstVault;
  const riskFocusText = worstVault
    ? `Vault #${worstVault.vault_id || '--'} · ${worstVault.ilk || worstVault.vault_type || '--'}`
    : '暂无活跃 Vault';
  const riskBadgeClass = riskToneClass(worstVault);
  const overviewMetaItems = [
    { label: '地址', value: data.address || address, mono: true },
    { label: '最近更新', value: refreshedAtText },
    { label: '数据状态', value: meta.cacheStatus === 'hit' ? '缓存命中' : '实时拉取' },
  ];

  const renderCopyButton = (value: string | null | undefined, key: string, label = '复制') => {
    if (!value?.trim()) return null;
    return (
      <button
        type="button"
        className="makerdao-copy-btn"
        onClick={() => void handleCopy(value, key)}
        title={`复制 ${value}`}
      >
        {copiedKey === key ? '已复制' : label}
      </button>
    );
  };

  const renderAddressDetail = (label: string, value: string | null | undefined, key: string) => (
    <div className="makerdao-detail-item">
      <span className="makerdao-detail-label">{label}</span>
      <div className="makerdao-detail-value-row">
        <span className="makerdao-full-address mono" title={value || undefined}>
          {value || '--'}
        </span>
        {renderCopyButton(value, key)}
      </div>
    </div>
  );

  const renderAssetRows = (assets: MakerDaoPositionAsset[], vaultId: number) => {
    if (!assets.length) {
      return <div className="makerdao-empty-detail">暂无资产明细</div>;
    }

    return (
      <div className="makerdao-asset-list">
        {assets.map((asset, index) => {
          const copyKey = `asset:${vaultId}:${index}:${asset.token_address}`;
          return (
            <div
              key={`${asset.role}-${asset.token_address}-${index}`}
              className="makerdao-asset-row"
            >
              <div className="makerdao-asset-main">
                <span className="badge badge-brand-soft">{roleLabel(asset.role)}</span>
                <strong>{asset.symbol || '--'}</strong>
                <span className="mono">{formatTokenAmount(asset.amount)}</span>
              </div>
              <div className="makerdao-asset-side">
                <strong>{formatUsd(asset.value_usd)}</strong>
                <div className="makerdao-detail-value-row">
                  <span className="makerdao-full-address mono" title={asset.token_address}>
                    {asset.token_address || '--'}
                  </span>
                  {renderCopyButton(asset.token_address, copyKey)}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    );
  };
  return (
    <div className="makerdao-dashboard">
      <div className="card makerdao-account-card">
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <span className="card-title">账户概览</span>
            <span className="badge green-badge">{data.chain || 'Ethereum'}</span>
            <span className="badge badge-brand-soft">{data.protocol || 'MakerDAO'}</span>
            <span className={`badge ${riskBadgeClass}`}>{riskLabel(worstVault)}</span>
          </div>
          <ChartDataStatus meta={meta} />
        </div>

        <div className="justlend-overview-grid makerdao-overview-grid">
          <div className="justlend-overview-copy">
            <div className="justlend-market-kicker">Vault Overview</div>
            <h2 className="justlend-market-title">
              {worstVault ? `当前重点关注 ${riskFocusText}` : '当前地址没有 MakerDAO Vault 仓位'}
            </h2>
            <p className="justlend-market-copy">
              MakerDAO 个人账户分析会按 Vault 汇总抵押价值、DAI 债务、健康因子与清算价格，
              用来快速判断该地址是否存在需要优先排查的 Vault。
            </p>
          </div>

          <div className="justlend-overview-side makerdao-overview-side">
            <div className="justlend-overview-pills makerdao-overview-pills">
              {overviewMetaItems.map((item) => (
                <div key={item.label} className="justlend-overview-pill makerdao-overview-pill">
                  <span className="justlend-overview-pill-label">{item.label}</span>
                  <span
                    className={`justlend-overview-pill-value ${item.mono ? 'mono' : ''}`}
                    title={item.value}
                  >
                    {item.value}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="summary-grid makerdao-summary-grid">
          <div className="metric-box">
            <span className="metric-label">当前抵押数量</span>
            <span className="metric-value blue">{summary.activeCollateralCount}</span>
          </div>
          <div className="metric-box">
            <span className="metric-label">总抵押价值</span>
            <span className="metric-value green">{formatUsd(summary.totalCollateralUsd)}</span>
          </div>
          <div className="metric-box">
            <span className="metric-label">总债务价值</span>
            <span className="metric-value red">{formatUsd(summary.totalDebtUsd)}</span>
          </div>
          <div className="metric-box">
            <span className="metric-label">最低健康因子</span>
            <span className={`metric-value ${healthTone(worstVault?.health_factor)}`}>
              {formatHealthFactor(worstVault?.health_factor)}
            </span>
          </div>
          <div className="metric-box">
            <span className="metric-label">健康 Vault</span>
            <span className="metric-value green">
              {summary.healthyCount}/{summary.activeCollateralCount}
            </span>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Vault 明细</span>
          <span className="badge green-badge">
            显示 {visiblePositions.length}/{data.total_positions ?? sortedPositions.length} 项
          </span>
        </div>

        <div className="makerdao-table-filter-bar">
          <div className="makerdao-filter-row">
            <label className="makerdao-filter-field">
              <span>Vault ID</span>
              <input
                type="number"
                min="0"
                inputMode="numeric"
                value={vaultIdFilter}
                onChange={(event) => setVaultIdFilter(event.target.value)}
                placeholder="过滤编号"
              />
            </label>
            <label className="makerdao-filter-field">
              <span>Ilk</span>
              <input
                type="text"
                value={ilkFilter}
                onChange={(event) => setIlkFilter(event.target.value)}
                placeholder="过滤 ETH-C"
              />
            </label>
          </div>
        </div>

        {visiblePositions.length === 0 ? (
          <p className="empty-text">该地址暂无 MakerDAO Vault 仓位记录</p>
        ) : (
          <div className="table-wrap">
            <table className="pos-table makerdao-vault-table">
              <thead>
                <tr>
                  <th>Vault</th>
                  <th>抵押品</th>
                  <th className="right">抵押数量</th>
                  <th className="right">抵押价值</th>
                  <th className="right">债务</th>
                  <th className="right">清算率</th>
                  <th className="right">清算价格</th>
                  <th className="right">健康因子</th>
                </tr>
              </thead>
              <tbody>
                {visiblePositions.map((item) => {
                  const key = vaultKey(item);
                  const expanded = expandedVaultKey === key;
                  const healthFactorDisplay = formatMakerHealthFactor(
                    item.health_factor,
                    item.debt_value_usd,
                  );
                  const healthFactorValue = getMakerHealthFactorValue(
                    item.health_factor,
                    item.debt_value_usd,
                  );
                  const healthFactorTone = getMakerHealthFactorTone(
                    healthFactorValue,
                    healthFactorDisplay,
                  );
                  const healthFactorClassName = [
                    healthFactorTone.className,
                    healthFactorDisplay === '无风险' && shouldBlinkMakerHealthFactorInfinity(item)
                      ? 'justlend-hf-pulse-safe'
                      : '',
                    isNativeMakerHealthFactorInfinity(item) ? 'justlend-hf-native-infinity' : '',
                  ]
                    .filter(Boolean)
                    .join(' ');
                  return (
                    <Fragment key={key}>
                      <tr>
                        <td>
                          <div className="makerdao-vault-cell">
                            <strong>#{item.vault_id}</strong>
                            <span>{item.ilk || item.vault_type}</span>
                            <div className="makerdao-inline-actions">
                              {renderCopyButton(item.urn_address, `urn:${key}`, '复制 urn')}
                              <button
                                type="button"
                                className="makerdao-copy-btn"
                                onClick={() => setExpandedVaultKey(expanded ? '' : key)}
                              >
                                {expanded ? '收起' : '详情'}
                              </button>
                            </div>
                          </div>
                        </td>
                        <td>
                          <div className="makerdao-vault-cell">
                            <strong>{item.collateral_symbol || '--'}</strong>
                            <span title={item.urn_address}>
                              urn {shortAddress(item.urn_address)}
                            </span>
                            {renderCopyButton(
                              item.collateral_token_address,
                              `collateral:${key}`,
                              '复制 token',
                            )}
                          </div>
                        </td>
                        <td className="right mono">{formatTokenAmount(item.collateral_amount)}</td>
                        <td className="right mono bold green-text">
                          {formatUsd(item.collateral_value_usd)}
                        </td>
                        <td className="right">
                          <div className="makerdao-debt-cell">
                            <strong className="red-text">{formatUsd(item.debt_value_usd)}</strong>
                            <span className="mono">
                              {formatTokenAmount(item.debt_amount)} {item.debt_symbol || ''}
                            </span>
                          </div>
                        </td>
                        <td className="right mono">{formatPercentRatio(item.liquidation_ratio)}</td>
                        <td className="right mono">{formatUsd(item.liquidation_price_usd)}</td>
                        <td
                          className={`right mono ${healthFactorClassName}`}
                          style={{
                            color: healthFactorTone.color,
                            fontWeight: healthFactorTone.fontWeight,
                          }}
                        >
                          {healthFactorDisplay}
                        </td>
                      </tr>
                      {expanded ? (
                        <tr className="makerdao-detail-row">
                          <td colSpan={8}>
                            <div className="makerdao-detail-panel">
                              <div className="makerdao-detail-grid">
                                {renderAddressDetail(
                                  'Owner 地址',
                                  item.owner_address,
                                  `owner:${key}`,
                                )}
                                {renderAddressDetail(
                                  'Proxy 地址',
                                  item.proxy_address,
                                  `proxy:${key}`,
                                )}
                                {renderAddressDetail(
                                  'URN 地址',
                                  item.urn_address,
                                  `urn-detail:${key}`,
                                )}
                                {renderAddressDetail(
                                  '抵押 Token',
                                  item.collateral_token_address,
                                  `collateral-detail:${key}`,
                                )}
                                {renderAddressDetail(
                                  '债务 Token',
                                  item.debt_token_address,
                                  `debt-detail:${key}`,
                                )}
                                <div className="makerdao-detail-item">
                                  <span className="makerdao-detail-label">数据来源</span>
                                  <span className="makerdao-detail-value">
                                    {compactDataSource(item.data_source)}
                                  </span>
                                </div>
                                <div className="makerdao-detail-item">
                                  <span className="makerdao-detail-label">快照时间</span>
                                  <span className="makerdao-detail-value">
                                    {formatDateTime(item.snapshot_at)}
                                  </span>
                                </div>
                                <div className="makerdao-detail-item">
                                  <span className="makerdao-detail-label">链上区块</span>
                                  <span className="makerdao-detail-value">
                                    {formatDateTime(item.block_timestamp)} · #
                                    {item.block_number || '--'}
                                  </span>
                                </div>
                              </div>

                              <div className="makerdao-assets-section">
                                <div className="makerdao-assets-header">
                                  <span className="card-title">资产明细</span>
                                  <span className="badge badge-brand-soft">
                                    {(item.assets ?? []).length} 项
                                  </span>
                                </div>
                                {renderAssetRows(item.assets ?? [], item.vault_id)}
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
        )}
      </div>
    </div>
  );
}
