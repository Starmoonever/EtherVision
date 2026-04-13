import { SegmentedControl } from './SegmentedControl';
import type { AppTab, ProtocolDefinition, ProtocolId } from '../types/app';

interface AppHeaderProps {
  protocol: ProtocolId;
  activeTab: AppTab;
  protocols: ProtocolDefinition[];
  onProtocolChange: (value: ProtocolId) => void;
  onTabChange: (value: AppTab) => void;
}

export function AppHeader({
  protocol,
  activeTab,
  protocols,
  onProtocolChange,
  onTabChange,
}: AppHeaderProps) {
  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="header-brand">
          <div className="logo">
            <span className="logo-icon">⚡</span>
            <span className="logo-text">ETH 市场清算风险监测</span>
          </div>
        </div>

        <div className="header-nav">
          <SegmentedControl
            ariaLabel="Page tabs"
            value={activeTab}
            onChange={onTabChange}
            options={[
              {
                value: 'personal',
                label: '个人账户分析',
                wide: true,
                activeClassName: 'active-purple',
              },
              {
                value: 'market',
                label: '宏观市场评估',
                wide: true,
                activeClassName: 'active-purple',
              },
            ]}
          />
        </div>

        <div className="header-protocol">
          <SegmentedControl
            ariaLabel="Protocol switch"
            value={protocol}
            onChange={onProtocolChange}
            options={protocols.map((item) => ({
              value: item.id,
              label: item.label,
            }))}
          />
        </div>
      </div>
    </header>
  );
}
