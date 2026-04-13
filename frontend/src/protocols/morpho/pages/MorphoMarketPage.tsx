import { PageHero } from '../../../shared/components/PageHero';

export function MorphoMarketPage() {
  return (
    <>
      <PageHero
        title="Morpho 宏观市场评估"
        subtitle="市场级接口尚未接入，当前先支持单 market id 的个人仓位查询"
      />

      <div className="card">
        <div className="card-header">
          <span className="card-title">接入状态</span>
          <span className="badge badge-brand-soft">Morpho Blue</span>
        </div>
        <p className="empty-text" style={{ margin: 0 }}>
          当前已接入个人页 `address + market id` 查询流程。等提供 `markets`、`market state`、
          `replay` 或 `liquidation` 接口后，这里可以继续扩成完整市场分析页。
        </p>
      </div>
    </>
  );
}
