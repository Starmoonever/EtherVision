import { useEffect, useMemo, useState } from 'react';
import {
  fetchMakerDaoPositionWithMeta,
  type MakerDaoPositionResponse,
  type MakerDaoVaultPosition,
} from '../../../api/makerdao';
import { mergeRequestMetas, type AggregatedRequestMeta } from '../../../api/requestMeta';
import { ChartDataStatus } from '../../../components/ChartAssist';

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
  const [meta, setMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError('');

      try {
        const result = await fetchMakerDaoPositionWithMeta({ address, includeEmpty: true });
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

  const positions = data?.positions ?? [];
  const summary = useMemo(() => {
    const totalCollateralUsd = positions.reduce(
      (sum, item) => sum + toNum(item.collateral_value_usd),
      0,
    );
    const totalDebtUsd = positions.reduce((sum, item) => sum + toNum(item.debt_value_usd), 0);
    const healthyCount = positions.filter((item) => item.is_healthy).length;
    const vaultTypes = new Set(
      positions.map((item) => item.ilk || item.vault_type).filter(Boolean),
    );
    const worstVault = findWorstVault(positions);

    return {
      totalCollateralUsd,
      totalDebtUsd,
      healthyCount,
      vaultTypes: vaultTypes.size,
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

          <div className="justlend-overview-side">
            <div className="justlend-overview-pills">
              {overviewMetaItems.map((item) => (
                <div key={item.label} className="justlend-overview-pill">
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
            <span className="metric-label">Vault 数量</span>
            <span className="metric-value blue">{data.total_positions ?? positions.length}</span>
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
            <span className="metric-label">健康因子</span>
            <span className={`metric-value ${healthTone(worstVault?.health_factor)}`}>
              {formatHealthFactor(worstVault?.health_factor)}
            </span>
          </div>
          <div className="metric-box">
            <span className="metric-label">健康 Vault</span>
            <span className="metric-value green">
              {summary.healthyCount}/{positions.length}
            </span>
          </div>
          <div className="metric-box">
            <span className="metric-label">抵押类型</span>
            <span className="metric-value blue">{summary.vaultTypes}</span>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Vault 明细</span>
          <span className="badge green-badge">{positions.length} 项</span>
        </div>

        {positions.length === 0 ? (
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
                  <th>数据时间</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((item) => (
                  <tr key={item.vault_uid || `${item.vault_id}-${item.urn_address}`}>
                    <td>
                      <div className="makerdao-vault-cell">
                        <strong>#{item.vault_id}</strong>
                        <span>{item.ilk || item.vault_type}</span>
                      </div>
                    </td>
                    <td>
                      <div className="makerdao-vault-cell">
                        <strong>{item.collateral_symbol || '--'}</strong>
                        <span title={item.urn_address}>urn {shortAddress(item.urn_address)}</span>
                      </div>
                    </td>
                    <td className="right mono">{formatTokenAmount(item.collateral_amount)}</td>
                    <td className="right mono bold green-text">
                      {formatUsd(item.collateral_value_usd)}
                    </td>
                    <td className="right mono bold red-text">{formatUsd(item.debt_value_usd)}</td>
                    <td className="right mono">{formatPercentRatio(item.liquidation_ratio)}</td>
                    <td className="right mono">{formatUsd(item.liquidation_price_usd)}</td>
                    <td className={`right mono bold ${healthTone(item.health_factor)}-text`}>
                      {formatHealthFactor(item.health_factor)}
                    </td>
                    <td>{formatDateTime(item.snapshot_at || item.block_timestamp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
