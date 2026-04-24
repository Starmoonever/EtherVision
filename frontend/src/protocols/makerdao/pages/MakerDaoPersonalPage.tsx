import { AddressInput } from '../../../components/AddressInput';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { PageHero } from '../../../shared/components/PageHero';
import { ResultPanel } from '../../../shared/components/ResultPanel';
import { MakerDaoPersonalDashboard } from '../components/MakerDaoPersonalDashboard';

interface MakerDaoPersonalPageProps {
  address: string;
  error: string;
  onSearch: (address: string) => void;
}

export function MakerDaoPersonalPage({ address, error, onSearch }: MakerDaoPersonalPageProps) {
  return (
    <>
      <PageHero
        title="MakerDAO 个人账户分析"
        subtitle="MakerDAO Vault 抵押债务、健康因子与清算价格概览"
      />

      <AddressInput
        onSearch={onSearch}
        loading={false}
        historyKey="search_history_makerdao"
        placeholder="输入 MakerDAO owner / proxy / urn 地址 (0x...)"
      />
      <ErrorNotice message={error} />

      {address ? (
        <div className="results-container">
          <ResultPanel>
            <MakerDaoPersonalDashboard address={address} />
          </ResultPanel>
        </div>
      ) : null}
    </>
  );
}
