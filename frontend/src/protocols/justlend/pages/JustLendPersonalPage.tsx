import { AddressInput } from '../../../components/AddressInput';
import { JustLendPersonalDashboard } from '../../../components/JustLendPersonalDashboard';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { PageHero } from '../../../shared/components/PageHero';
import { ResultPanel } from '../../../shared/components/ResultPanel';

interface JustLendPersonalPageProps {
  address: string;
  error: string;
  onSearch: (address: string) => void;
}

export function JustLendPersonalPage({ address, error, onSearch }: JustLendPersonalPageProps) {
  return (
    <>
      <PageHero title="JustLend 个人账户分析" subtitle="TRON 链当前仓位、风险缓冲与资产结构分析" />

      <AddressInput
        onSearch={onSearch}
        loading={false}
        historyKey="search_history_justlend"
        placeholder="输入 JustLend / TRON 钱包地址 (T...)"
        addressType="tron"
      />
      <ErrorNotice message={error} />

      {address ? (
        <div className="results-container">
          <ResultPanel>
            <JustLendPersonalDashboard address={address} />
          </ResultPanel>
        </div>
      ) : null}
    </>
  );
}
