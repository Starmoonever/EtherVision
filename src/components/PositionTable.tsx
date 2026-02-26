import type { ReservePosition } from '../lib/aave';

interface Props {
  reserves: ReservePosition[];
}

export function PositionTable({ reserves }: Props) {
  const supplies = reserves.filter((r) => r.supplyBalanceRaw > 0n);
  const borrows = reserves.filter((r) => r.stableDebtRaw > 0n || r.variableDebtRaw > 0n);

  return (
    <div className="positions-wrap">
      {/* ── 供给仓位 ── */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">供给 (Supplied)</span>
          <span className="badge green-badge">{supplies.length} 项</span>
        </div>

        {supplies.length === 0 ? (
          <p className="empty-text">该地址在 Aave V3 上没有供给仓位</p>
        ) : (
          <div className="table-wrap">
            <table className="pos-table">
              <thead>
                <tr>
                  <th>资产</th>
                  <th className="right">余额</th>
                  <th className="center">用作抵押品</th>
                </tr>
              </thead>
              <tbody>
                {supplies.map((r) => (
                  <tr key={r.tokenAddress}>
                    <td>
                      <span className="token-symbol">{r.symbol}</span>
                    </td>
                    <td className="right mono">{r.supplyBalance}</td>
                    <td className="center">
                      {r.usageAsCollateralEnabled ? (
                        <span className="pill green-pill">是</span>
                      ) : (
                        <span className="pill gray-pill">否</span>
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
          <span className="card-title">借贷 (Borrowed)</span>
          <span className="badge red-badge">{borrows.length} 项</span>
        </div>

        {borrows.length === 0 ? (
          <p className="empty-text">该地址在 Aave V3 上没有借贷仓位</p>
        ) : (
          <div className="table-wrap">
            <table className="pos-table">
              <thead>
                <tr>
                  <th>资产</th>
                  <th className="right">稳定借贷</th>
                  <th className="right">浮动借贷</th>
                  <th className="right">合计</th>
                </tr>
              </thead>
              <tbody>
                {borrows.map((r) => (
                  <tr key={r.tokenAddress}>
                    <td>
                      <span className="token-symbol">{r.symbol}</span>
                    </td>
                    <td className="right mono">
                      {r.stableDebtRaw > 0n ? r.stableDebt : '—'}
                    </td>
                    <td className="right mono">
                      {r.variableDebtRaw > 0n ? r.variableDebt : '—'}
                    </td>
                    <td className="right mono bold">{r.totalDebt}</td>
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
