import type { UserPosition, BorrowPosition } from '../api';

// 定义用于渲染表格行的接口
interface PositionRow {
  tokenAddress: string;
  symbol: string;
  priceUSD: number;
  balance: string;
  valueUSD: number;
  isCollateral?: boolean;
}

interface PositionTableProps {
  data: UserPosition | BorrowPosition | null;
  loading: boolean;
  notFound: boolean;
  version: 'v2' | 'v3';
}


export function PositionTable({ data: position, loading, notFound, version }: PositionTableProps) {
  const versionLabel = version.toUpperCase();

  const headerBadge_found = (
    <span
      className="badge"
      style={{
        background: '#1e293b',
        color: '#a78bfa',
        border: '1px solid #4c1d95',
        fontWeight: 700,
      }}
    >
      {versionLabel}
    </span>
  );

  const headerBadge_empty = (
    <span
      className="badge"
      style={{ background: '#1e293b', color: '#64748b', border: '1px solid #334155' }}
    >
      {versionLabel}
    </span>
  );

  if (loading)
    return (
      <div
        className="card"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '120px',
          gap: '0.75rem',
        }}
      >
        <div
          className="spinner"
          style={{ width: '20px', height: '20px', borderWidth: '2px' }}
        ></div>
      </div>
    );

  if (notFound)
    return (
      <div
        className="card"
        style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', minHeight: '200px' }}
      >
        <div className="card-header">
          <span className="card-title">资产负债情况</span>
          {notFound ? headerBadge_empty : headerBadge_found}
        </div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <p className="empty-text" style={{ margin: 0 }}>
            该地址在 Aave {versionLabel} 暂无仓位记录
          </p>
        </div>
      </div>
    );

  if (!position) return null;

  // 筛选抵押资产: use_as_collateral 为 true
  const supplies: PositionRow[] = position.reserves
    .filter(r => r.use_as_collateral)
    .map(r => ({
      tokenAddress: r.token_address,
      symbol: r.symbol,
      priceUSD: parseFloat(r.price_usd || '0'),
      balance: r.supply_amount,
      valueUSD: parseFloat(r.supply_usd || '0'),
      isCollateral: true
    }));

  // 筛选负债: total_debt_amount 不为 0
  const borrows: PositionRow[] = position.reserves
    .filter(r => parseFloat(r.total_debt_amount || '0') !== 0)
    .map(r => ({
      tokenAddress: r.token_address,
      symbol: r.symbol,
      priceUSD: parseFloat(r.price_usd || '0'),
      balance: r.total_debt_amount,
      valueUSD: parseFloat(r.total_debt_usd || '0')
    }));

  return (
    <div className="positions-wrap">
      {/* ── 供给仓位 ── */}
      <div className="card">
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span className="card-title">资产 (Supplied)</span>
            {headerBadge_found}
          </div>
          <span className="badge green-badge">{supplies.length} 项</span>
        </div>

        {supplies.length === 0 ? (
          <p className="empty-text">该地址还没有抵押资产记录</p>
        ) : (
          <div className="table-wrap">
            <table className="pos-table">
              <thead>
                <tr>
                  <th>资产</th>
                  <th className="right">单价 (USD)</th>
                  <th className="right">抵押数量</th>
                  <th className="right">抵押价值 (USD)</th>
                </tr>
              </thead>
              <tbody>
                {supplies.map((r) => (
                  <tr key={r.tokenAddress}>
                    <td>
                      <span className="token-symbol">{r.symbol}</span>
                    </td>
                    <td className="right mono">
                      $
                      {r.priceUSD.toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}
                    </td>
                    <td className="right mono">
                      {parseFloat(r.balance).toLocaleString(undefined, {
                        minimumFractionDigits: 6,
                        maximumFractionDigits: 6,
                      })}
                    </td>
                    <td className="right mono bold">
                      $
                      {r.valueUSD.toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── 借贷仓位 ── */}
      <div className="card">
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span className="card-title">负债 (Borrowed)</span>
            {headerBadge_found}
            {Number(position.available_borrows_usd) > 0 && (
              <span
                className="badge"
                style={{
                  backgroundColor: '#1e293b',
                  color: '#94a3b8',
                  fontSize: '0.75rem',
                  fontWeight: 'normal',
                  border: '1px solid #334155',
                }}
              >
                可借额度: $
                {parseFloat(position.available_borrows_usd).toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </span>
            )}
          </div>
          <span className="badge red-badge">{borrows.length} 项</span>
        </div>

        {borrows.length === 0 ? (
          <p className="empty-text">该地址还没有负债记录</p>
        ) : (
          <div className="table-wrap">
            <table className="pos-table">
              <thead>
                <tr>
                  <th>资产</th>
                  <th className="right">单价 (USD)</th>
                  <th className="right">借出数量</th>
                  <th className="right">借出价值 (USD)</th>
                </tr>
              </thead>
              <tbody>
                {borrows.map((r) => (
                  <tr key={r.tokenAddress}>
                    <td>
                      <span className="token-symbol">{r.symbol}</span>
                    </td>
                    <td className="right mono">
                      $
                      {r.priceUSD.toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}
                    </td>
                    <td className="right mono bold">
                      {parseFloat(r.balance).toLocaleString(undefined, {
                        minimumFractionDigits: 6,
                        maximumFractionDigits: 6,
                      })}
                    </td>
                    <td className="right mono bold red-text">
                      $
                      {r.valueUSD.toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}
                    </td>
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
