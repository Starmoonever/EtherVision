import { PageHero } from '../../../shared/components/PageHero';

export function MakerDaoMarketPage() {
  return (
    <>
      <PageHero
        title="MakerDAO 宏观市场评估"
        subtitle="MakerDAO 市场页接口接入中，当前先提供个人 Vault 分析入口。"
      />

      <div className="card makerdao-placeholder-card">
        <span className="card-title">市场视图待接入</span>
        <p>
          目前已接入 <code>/api/makerdao/position</code> 用于个人账户分析；后续拿到市场接口后，
          可以在这里扩展 Vault 分布、抵押品规模、债务规模与清算风险看板。
        </p>
      </div>
    </>
  );
}
