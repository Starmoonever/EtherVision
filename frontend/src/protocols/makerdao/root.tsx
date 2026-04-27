import { useState } from 'react';
import type { ProtocolRootProps } from '../../shared/types/app';
import { MakerDaoMarketPage } from './pages/MakerDaoMarketPage';
import { MakerDaoPersonalPage } from './pages/MakerDaoPersonalPage';
import './styles.css';

export function MakerDaoProtocolRoot({ active, activeTab }: ProtocolRootProps) {
  const [error, setError] = useState('');
  const [address, setAddress] = useState('');

  if (!active) return null;

  return activeTab === 'personal' ? (
    <MakerDaoPersonalPage
      address={address}
      error={error}
      onSearch={(nextAddress) => {
        setError('');
        setAddress(nextAddress);
      }}
    />
  ) : (
    <MakerDaoMarketPage active={active} />
  );
}
