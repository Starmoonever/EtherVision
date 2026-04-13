import type { ProtocolDefinition } from '../shared/types/app';
import { AaveProtocolRoot } from './aave';
import { CompoundProtocolRoot } from './compound';
import { MorphoProtocolRoot } from './morpho';
import { JustLendProtocolRoot } from './justlend';

export const protocolRegistry: ProtocolDefinition[] = [
  {
    id: 'aave',
    label: 'Aave',
    Root: AaveProtocolRoot,
  },
  {
    id: 'compound',
    label: 'Compound',
    Root: CompoundProtocolRoot,
  },
  {
    id: 'morpho',
    label: 'Morpho',
    Root: MorphoProtocolRoot,
  },
  {
    id: 'justlend',
    label: 'JustLend',
    Root: JustLendProtocolRoot,
  },
];
