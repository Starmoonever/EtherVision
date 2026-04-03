import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { AggregatedRequestMeta } from '../api/requestMeta';

export interface ExplainItem {
  term: string;
  formula?: string;
  meaning: string;
  riskHint: string;
}

interface ChartInfoButtonProps {
  title: string;
  items: ExplainItem[];
}

interface ChartDataStatusProps {
  meta: AggregatedRequestMeta;
  scenarioLabel?: string;
}

function formatTime(timestamp: number | null): string {
  if (!timestamp) return '--';
  return new Date(timestamp).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function cacheStatusLabel(status: AggregatedRequestMeta['cacheStatus']): string {
  if (status === 'hit') return '缓存命中';
  if (status === 'miss') return '网络请求';
  if (status === 'mixed') return '部分命中';
  return '未记录';
}

function cacheStatusColor(status: AggregatedRequestMeta['cacheStatus']): string {
  if (status === 'hit') return '#10b981';
  if (status === 'miss') return '#38bdf8';
  if (status === 'mixed') return '#f59e0b';
  return '#64748b';
}

export function ChartInfoButton({ title, items }: ChartInfoButtonProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [panelStyle, setPanelStyle] = useState<{ top: number; left: number; width: number }>({
    top: 0,
    left: 16,
    width: 360,
  });

  useEffect(() => {
    if (!open) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  useLayoutEffect(() => {
    if (!open) return;

    const updatePosition = () => {
      const triggerRect = wrapRef.current?.getBoundingClientRect();
      if (!triggerRect) return;

      const viewportPadding = 16;
      const maxWidth = Math.min(360, window.innerWidth - viewportPadding * 2);
      const panelWidth = Math.max(260, maxWidth);
      const desiredLeft = triggerRect.left + triggerRect.width / 2 - panelWidth / 2;
      const clampedLeft = Math.min(
        Math.max(viewportPadding, desiredLeft),
        window.innerWidth - panelWidth - viewportPadding,
      );

      setPanelStyle({
        top: Math.min(triggerRect.bottom + 8, window.innerHeight - 24),
        left: clampedLeft,
        width: panelWidth,
      });
    };

    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);

    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [open]);

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        style={{
          width: '20px',
          height: '20px',
          borderRadius: '999px',
          border: '1px solid #334155',
          background: open ? '#334155' : '#0f172a',
          color: '#cbd5e1',
          fontWeight: 700,
          cursor: 'pointer',
          padding: 0,
          fontSize: '0.75rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
        title="查看指标解释"
      >
        ?
      </button>

      {open && (
        <div
          ref={panelRef}
          style={{
            position: 'fixed',
            top: `${panelStyle.top}px`,
            left: `${panelStyle.left}px`,
            width: `${panelStyle.width}px`,
            maxWidth: 'calc(100vw - 32px)',
            maxHeight: 'min(70vh, 560px)',
            overflowY: 'auto',
            zIndex: 1000,
            background: '#0b1220',
            border: '1px solid #334155',
            borderRadius: '10px',
            padding: '0.9rem',
            boxShadow: '0 12px 24px rgba(2,6,23,0.55)',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.8rem',
          }}
        >
          <div style={{ color: '#e2e8f0', fontWeight: 700, fontSize: '0.92rem' }}>{title}</div>
          {items.map((item) => (
            <div
              key={item.term}
              style={{
                borderTop: '1px solid #1e293b',
                paddingTop: '0.75rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.32rem',
              }}
            >
              <div style={{ color: '#f8fafc', fontWeight: 600, fontSize: '0.84rem' }}>
                {item.term}
              </div>
              {item.formula && (
                <div style={{ color: '#93c5fd', fontSize: '0.78rem', lineHeight: 1.5 }}>
                  公式：{item.formula}
                </div>
              )}
              <div style={{ color: '#94a3b8', fontSize: '0.78rem', lineHeight: 1.55 }}>
                含义：{item.meaning}
              </div>
              <div style={{ color: '#fbbf24', fontSize: '0.78rem', lineHeight: 1.55 }}>
                观察重点：{item.riskHint}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ChartDataStatus({ meta, scenarioLabel }: ChartDataStatusProps) {
  const items = [
    {
      label: '最后刷新',
      value: formatTime(meta.lastUpdatedAt),
      color: '#cbd5e1',
    },
    {
      label: '数据来源',
      value: cacheStatusLabel(meta.cacheStatus),
      color: cacheStatusColor(meta.cacheStatus),
    },
  ];

  if (scenarioLabel) {
    items.push({
      label: '联动场景',
      value: scenarioLabel,
      color: '#fbbf24',
    });
  }

  return (
    <div
      style={{
        display: 'flex',
        gap: '0.5rem',
        alignItems: 'center',
        flexWrap: 'wrap',
        justifyContent: 'flex-end',
      }}
    >
      {items.map((item) => (
        <div
          key={item.label}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            background: '#0f172a',
            border: '1px solid #1e293b',
            borderRadius: '999px',
            padding: '0.22rem 0.6rem',
            fontSize: '0.72rem',
            lineHeight: 1.2,
          }}
        >
          <span style={{ color: '#64748b' }}>{item.label}</span>
          <span style={{ color: item.color, fontWeight: 600 }}>{item.value}</span>
        </div>
      ))}
    </div>
  );
}
