import { useState } from 'react';
import type { ProtocolRootProps } from '../../shared/types/app';
import { JustLendMarketPage } from './pages/JustLendMarketPage';
import { JustLendPersonalPage } from './pages/JustLendPersonalPage';

export function JustLendProtocolRoot({ active, activeTab }: ProtocolRootProps) {
  const [error, setError] = useState('');
  const [address, setAddress] = useState('');

  if (!active) return null;

  return activeTab === 'personal' ? (
    <JustLendPersonalPage
      address={address}
      error={error}
      onSearch={(nextAddress) => {
        setError('');
        setAddress(nextAddress);
      }}
    />
  ) : (
    <JustLendMarketPage />
  );
}
