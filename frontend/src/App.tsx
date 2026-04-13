import { useState } from 'react';
import { AppHeader } from './shared/components/AppHeader';
import { protocolRegistry } from './protocols/registry';
import type { AppTab, ProtocolId } from './shared/types/app';
import './App.css';

export default function App() {
  const [protocol, setProtocol] = useState<ProtocolId>('aave');
  const [activeTab, setActiveTab] = useState<AppTab>('personal');

  return (
    <div className="app">
      <AppHeader
        protocol={protocol}
        activeTab={activeTab}
        protocols={protocolRegistry}
        onProtocolChange={setProtocol}
        onTabChange={setActiveTab}
      />

      <main className="app-main">
        {protocolRegistry.map(({ id, Root }) => (
          <Root key={id} active={protocol === id} activeTab={activeTab} />
        ))}
      </main>

      <footer className="app-footer">数据来源：内网 API | Ethereum Mainnet / TRON</footer>
    </div>
  );
}
