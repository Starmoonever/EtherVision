import type { ReactNode } from 'react';

interface ResultPanelProps {
  children: ReactNode;
  className?: string;
}

export function ResultPanel({ children, className }: ResultPanelProps) {
  return <div className={['result-panel', className].filter(Boolean).join(' ')}>{children}</div>;
}
