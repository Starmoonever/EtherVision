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

function isBorrowPosition(data: UserPosition | BorrowPosition): data is BorrowPosition {
  return (data as BorrowPosition).weth_debt_amount !== undefined;
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

  let supplies: PositionRow[] = [];
  let borrows: PositionRow[] = [];

  if (isBorrowPosition(position)) {
    // 处理借贷端数据 (Detailed Reserves)
    position.reserves.forEach(r => {
        const supplyAmount = parseFloat(r.supply_amount || '0');
        const debtAmount = parseFloat(r.total_debt_amount || '0');
        
        if (supplyAmount > 0) {
            supplies.push({
                tokenAddress: r.token_address,
                symbol: r.symbol,
                priceUSD: parseFloat(r.price_usd || '0'),
                balance: r.supply_amount,
                valueUSD: parseFloat(r.supply_usd || '0'),
                isCollateral: r.use_as_collateral
            });
        }

        if (debtAmount > 0) {
            borrows.push({
                tokenAddress: r.token_address, // or use symbol as key if address not unique per row (unlikely)
                symbol: r.symbol,
                priceUSD: parseFloat(r.price_usd || '0'),
                balance: r.total_debt_amount,
                valueUSD: parseFloat(r.total_debt_usd || '0'),
            });
        }
    });
  } else {
    // 处理抵押端数据 (Simplified UserPosition)
    // 解析数值
    const ethAmount = parseFloat(position.eth_collateral_amount || '0');
    const ethValue = parseFloat(position.eth_collateral_usd || '0');
    const debtValue = parseFloat(position.total_debt_usd || '0');

    // 构建供给列表 (仅 ETH)
    if (ethAmount > 0) {
      supplies.push({
        tokenAddress: 'ETH',
        symbol: 'ETH',
        priceUSD: ethAmount > 0 ? ethValue / ethAmount : 0,
        balance: position.eth_collateral_amount,
        valueUSD: ethValue,
        isCollateral: true // Assuming ETH is collateral in this view
      });
    }

    // 构建借贷列表 (仅显示总债务)
    if (debtValue > 0) {
      borrows.push({
        tokenAddress: 'TOTAL_DEBT',
        symbol: 'Total Debt',
        priceUSD: 1, // Placeholder
        balance: position.total_debt_usd, // Showing value as balance for Total Debt row? Or maybe '0'? 
        // Original code used total_debt_usd as balance? No, let's check.
        // original: balance: position.total_debt_usd
        // It seems in the simplified view, balance was used for value.
        valueUSD: debtValue,
      });
    }
  }

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
                  <th className="right">余额</th>
                  <th className="right">估值 (USD)</th>
                  <th className="center">用作抵押品</th>
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
                    <td className="center">
                      {r.isCollateral !== undefined ? (
                          <span className={`pill ${r.isCollateral ? 'green-pill' : 'gray-pill'}`}>
                            {r.isCollateral ? '是' : '否'}
                          </span>
                      ) : (
                          <span className="pill green-pill">是</span> // Default for old view
                      )}
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
            {/* Show available borrows only for UserPosition or if we had it in BorrowPosition? 
                BorrowPosition doesn't seem to have available_borrows_usd in JSON. 
                So hide it if not present. 
            */}
            {!isBorrowPosition(position) && Number(position.available_borrows_usd) > 0 && (
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
                  <th className="right">合计借贷 (USD)</th>
                  <th className="right">估值 (USD)</th>
                </tr>
              </thead>
              <tbody>
                {borrows.map((r) => (
                  <tr key={r.tokenAddress}>
                    <td>
                      <span className="token-symbol">{r.symbol}</span>
                    </td>
                    <td className="right mono bold">
                      {parseFloat(r.balance).toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
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
