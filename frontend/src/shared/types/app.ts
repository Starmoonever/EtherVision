import type { ComponentType } from 'react';

export type ProtocolId = 'aave' | 'compound' | 'morpho' | 'justlend' | 'makerdao';
export type AppTab = 'personal' | 'market';

export interface ProtocolRootProps {
  active: boolean;
  activeTab: AppTab;
}

export interface ProtocolDefinition {
  id: ProtocolId;
  label: string;
  Root: ComponentType<ProtocolRootProps>;
}
