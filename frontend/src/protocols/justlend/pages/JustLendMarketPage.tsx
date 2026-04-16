import { JustLendMarketDashboard } from '../../../components/JustLendMarketDashboard';
import { PageHero } from '../../../shared/components/PageHero';

export function JustLendMarketPage() {
  return (
    <>
      <PageHero
        title="JustLend 宏观市场评估"
        subtitle="JustLend 市场规模、流动性、利率参数与风险状态综合分析"
      />

      <JustLendMarketDashboard />
    </>
  );
}
