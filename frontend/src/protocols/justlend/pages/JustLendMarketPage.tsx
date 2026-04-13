import { JustLendMarketDashboard } from '../../../components/JustLendMarketDashboard';
import { PageHero } from '../../../shared/components/PageHero';

export function JustLendMarketPage() {
  return (
    <>
      <PageHero
        title="JustLend 宏观市场评估"
        subtitle="先搭好分析框架，等待 TRON 市场级接口与历史序列接入"
      />

      <JustLendMarketDashboard />
    </>
  );
}
